"""
Orchestrator for the full doping-stability workflow.

Supports:
  - Multiple target layers in one run (e.g. target_elements=["Co","Na"])
    so the program automatically tests every layer and ranks site preference.
  - Charge compensation: for aliovalent dopants with negative charge mismatch
    (dopant brings less positive charge than the atom it replaces), Na atoms
    are removed from the supercell to restore charge neutrality. Positive
    mismatch cases run uncompensated with a warning.
  - Per-phase caching and MD mid-run resume (see checkpoint files).
  - Bottom-pinned tqdm progress bar per test.

Configure the WorkflowConfig block at the bottom and run:

    python run_workflow.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chgnet.model.model import CHGNet

from charge_utils import (
    charge_mismatch as compute_charge_mismatch,
    describe_compensation,
)
from setup_references import get_or_compute_references
from enumerate_and_relax import (
    enumerate_sites,
    formation_energy,
    relax_doped_compensated,
    relax_pristine,
)
from run_md import MDRunSpec, run_md
from analyze_trajectory import analyze
from report import StabilityReport, write_summary_table
from progress import info, loop_progress_bar, test_progress_bar


@dataclass
class WorkflowConfig:
    primitive_cell_file: str = "primitive_cells/NaCoO2.cif"
    host_formula: str = "NaCoO2"
    target_elements: list = field(default_factory=lambda: ["Co"])
    dopant: str = "Al"
    supercell_size: int = 2
    chgnet_model: str = "r2scan"
    run_md: bool = True
    md_top_n: int = 1           # MD runs per target element
    md_spec: MDRunSpec = None
    reports_dir: str = "reports"
    relaxed_dir: str = "relaxed_structures"
    analysis_dir: str = "analysis"
    references_file: str = "references.json"
    force_recompute: bool = False
    coordination_cutoff_A: float = 2.5
    charge_compensate: bool = True
    compensation_ref: str = "Na"
    dopant_oxidation_state: int | None = None
    target_oxidation_states: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.md_spec is None:
            self.md_spec = MDRunSpec()


def header(title):
    bar = "#" * 78
    info()
    info(bar)
    info(f"# {title}")
    info(bar)


def _cross_site_summary(reports):
    header("SITE PREFERENCE SUMMARY")
    info(f"  {'Test':<45} {'Target':>6} {'E_f (eV)':>10} {'Comp':>5} {'Verdict'}")
    info("  " + "-" * 78)
    for r in sorted(reports, key=lambda x: x.formation_energy_eV):
        comp = "Y" if r.compensation_applied else "N"
        info(
            f"  {r.test_name:<45} {r.target_site_element:>6} "
            f"{r.formation_energy_eV:>+10.4f} {comp:>5}  {r.verdict}"
        )
    info()

    best = min(reports, key=lambda x: x.formation_energy_eV)
    info(f"  Lowest E_f: {best.target_site_element} site ({best.formation_energy_eV:+.4f} eV)")

    target_bests = {}
    for r in reports:
        t = r.target_site_element
        if t not in target_bests or r.formation_energy_eV < target_bests[t].formation_energy_eV:
            target_bests[t] = r

    if len(target_bests) > 1:
        ordered = sorted(target_bests.values(), key=lambda r: r.formation_energy_eV)
        info()
        info("  Per-layer best:")
        for r in ordered:
            info(f"    {r.target_site_element} site: E_f = {r.formation_energy_eV:+.4f} eV  "
                 f"({r.charge_mismatch:+d} charge mismatch)  →  {r.verdict}")
        info()
        winner = ordered[0]
        info(f"  >>> Dopant prefers the {winner.target_site_element} layer "
             f"(delta E_f = {ordered[1].formation_energy_eV - ordered[0].formation_energy_eV:+.4f} eV) <<<")


def run(config):
    Path(config.reports_dir).mkdir(parents=True, exist_ok=True)

    header("Loading CHGNet")
    chgnet = CHGNet.load(model_name=config.chgnet_model)

    all_ref_elements = sorted({config.dopant, config.compensation_ref} | set(config.target_elements))
    header(f"Phase 1: chemical potentials — {', '.join(all_ref_elements)}")
    mus = get_or_compute_references(
        all_ref_elements, chgnet=chgnet,
        path=config.references_file, force=config.force_recompute,
    )

    header("Phase 2: pristine supercell")
    primitive, supercell, pristine_final, pristine_energy, pristine_sg = relax_pristine(
        config.primitive_cell_file, config.supercell_size, chgnet,
        output_dir=config.relaxed_dir, force=config.force_recompute,
    )

    all_configurations = []

    for target_element in config.target_elements:
        target_ox = config.target_oxidation_states.get(target_element)
        mismatch = compute_charge_mismatch(
            config.dopant, target_element,
            dopant_ox=config.dopant_oxidation_state,
            target_ox=target_ox,
        )
        comp_desc = describe_compensation(mismatch, config.compensation_ref)

        header(
            f"Phase 3: {config.dopant} → {target_element} site  "
            f"(mismatch {mismatch:+d})  {comp_desc}"
        )

        candidates = enumerate_sites(pristine_final, target_element)
        info(f"  {len(candidates)} symmetrically distinct {target_element} site(s)")

        with loop_progress_bar(len(candidates), f"Relaxing {config.dopant}@{target_element}") as bar:
            for i, candidate in enumerate(candidates):
                label = f"{target_element}_site{candidate.site_index}"
                relaxed, comp_applied, comp_warnings = relax_doped_compensated(
                    pristine_final, candidate.site_index, config.dopant, target_element,
                    chgnet, mismatch=mismatch,
                    compensation_ref=config.compensation_ref,
                    output_dir=config.relaxed_dir, label=label,
                    force=config.force_recompute,
                )

                mu_removed_list = [mus[target_element]]
                if comp_applied:
                    mu_removed_list += [mus[config.compensation_ref]] * abs(mismatch)

                e_f = formation_energy(
                    relaxed.final_energy_eV, pristine_energy,
                    mu_removed_list, mus[config.dopant],
                )
                info(f"  [{label}] E_f = {e_f:+.4f} eV  comp={comp_applied}")
                bar.update(1)
                info(f"  >>> Phase 3 progress: {i+1}/{len(candidates)} ({(i+1)/len(candidates)*100:.1f}%) [{target_element}] <<<")

                all_configurations.append({
                    "candidate": candidate,
                    "relaxed": relaxed,
                    "e_f": e_f,
                    "target_element": target_element,
                    "mismatch": mismatch,
                    "comp_applied": comp_applied,
                    "comp_warnings": comp_warnings,
                    "comp_desc": comp_desc,
                    "candidate_rank_within_target": None,
                })

    all_configurations.sort(key=lambda x: x["e_f"])

    for target_element in config.target_elements:
        target_cfgs = [c for c in all_configurations if c["target_element"] == target_element]
        for rank, cfg in enumerate(target_cfgs):
            cfg["candidate_rank_within_target"] = rank

    md_total_steps = config.md_spec.equilibration_steps + config.md_spec.production_steps
    reports = []

    for cfg in all_configurations:
        candidate = cfg["candidate"]
        relaxed = cfg["relaxed"]
        e_f = cfg["e_f"]
        target_element = cfg["target_element"]
        mismatch = cfg["mismatch"]
        comp_applied = cfg["comp_applied"]
        comp_warnings = cfg["comp_warnings"]
        rank_within_target = cfg["candidate_rank_within_target"]

        do_md = config.run_md and rank_within_target < config.md_top_n
        test_name = (
            f"{config.dopant}@{target_element}_site{candidate.site_index}"
        )
        header(f"Test: {test_name}  (run_md={do_md})")

        report = StabilityReport(
            test_name=test_name,
            host_formula=config.host_formula,
            dopant=config.dopant,
            target_site_element=target_element,
            site_index=candidate.site_index,
            supercell_size=config.supercell_size,
            formation_energy_eV=e_f,
            pristine_energy_eV=pristine_energy,
            doped_energy_eV=relaxed.final_energy_eV,
            mu_dopant_eV=mus[config.dopant],
            mu_removed_eV=mus[target_element],
            relaxed_space_group=relaxed.relaxed_space_group,
            relaxed_coordination=relaxed.coordination_number,
            relaxed_mean_nn_distance_A=(
                sum(relaxed.nn_distances_A) / len(relaxed.nn_distances_A)
                if relaxed.nn_distances_A else None
            ),
            relaxed_nn_distances_A=relaxed.nn_distances_A,
            charge_mismatch=mismatch,
            compensation_applied=comp_applied,
            compensation_description=cfg["comp_desc"],
        )
        report.notes.append(
            f"Symmetric multiplicity: {candidate.multiplicity}"
        )
        for w in comp_warnings:
            report.notes.append(f"WARNING: {w}")

        with test_progress_bar(test_name, md_total_steps) as progress:
            progress.phase("doped_relax")

            if do_md:
                md_result = run_md(
                    relaxed.final_structure, chgnet, label=test_name,
                    spec=config.md_spec, progress=progress,
                )
                analysis = analyze(
                    md_result, dopant_symbol=config.dopant,
                    cutoff_A=config.coordination_cutoff_A,
                    output_dir=config.analysis_dir,
                    force=config.force_recompute,
                )
                progress.phase("analysis")

                report.md_temperature_K = md_result["temperature_K"]
                report.md_duration_ps = md_result["duration_ps"]
                report.md_msd_slope_A2_per_ps = analysis["msd_slope_A2_per_ps"]
                report.md_msd_final_A2 = analysis["msd_final_A2"]
                report.md_max_displacement_A = analysis["max_displacement_A"]
                report.md_coordination_min = analysis["coordination_min"]
                report.md_coordination_max = analysis["coordination_max"]
                report.md_coordination_mean = analysis["coordination_mean"]
                report.md_mean_nn_distance_A = analysis["mean_nn_distance_A"]
                report.md_volume_change_pct = analysis["volume_change_pct"]
                report.md_space_group = analysis["space_group"]
                report.notes.append(f"Analysis outputs in {analysis['output_dir']}")
            else:
                progress.md_complete()
                progress.phase("analysis")

            report.print_report()
            report_path = Path(config.reports_dir) / f"{test_name}.json"
            report.save(report_path)
            info(f"  saved report -> {report_path}")
            progress.phase("report")

        reports.append(report)

    _cross_site_summary(reports)

    summary_path = Path(config.reports_dir) / "summary.csv"
    write_summary_table(reports, summary_path)
    info(f"Wrote summary -> {summary_path}")
    return reports


if __name__ == "__main__":
    config = WorkflowConfig(
        primitive_cell_file="primitive_cells/NaCoO2.cif",
        host_formula="NaCoO2",
        target_elements=["Co", "Na"],   # test both layers
        dopant="Mn",
        supercell_size=2,
        chgnet_model="r2scan",
        run_md=True,
        md_top_n=1,                     # MD on best site per layer
        md_spec=MDRunSpec(
            temperature_C=250.0,
            timestep_fs=2.0,
            equilibration_steps=2500,
            production_steps=25000,
            loginterval=10,
        ),
        force_recompute=False,
        coordination_cutoff_A=2.5,
        charge_compensate=True,
        compensation_ref="Na",
        dopant_oxidation_state=3,       # Mn3+ most common in layered oxides
        # Mn3+ @ Co3+: mismatch = 0 (isovalent, no compensation needed)
        # Mn3+ @ Na+:  mismatch = +2 (surplus — runs uncompensated, E_f approximate)
    )
    run(config)
