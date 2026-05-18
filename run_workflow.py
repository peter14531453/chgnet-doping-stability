"""
Orchestrator for the full doping-stability workflow.

  Phase 1: chemical potentials (setup_references)
  Phase 2: enumerate symmetrically distinct host sites (enumerate_and_relax)
  Phase 3: relax pristine + every candidate, compute E_f
  Phase 4: NVT MD on each candidate (or just the top-N, configurable)
  Phase 5: trajectory analysis
  Phase 6: stability report per test, plus a summary table

Edit the CONFIG block at the bottom of this file to change dopant, host,
supercell size, or MD parameters. Then run:

    python run_workflow.py
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from chgnet.model.model import CHGNet

from setup_references import get_or_compute_references
from enumerate_and_relax import (
    build_supercell,
    enumerate_sites,
    formation_energy,
    relax_doped,
    relax_pristine,
)
from run_md import MDRunSpec, run_md
from analyze_trajectory import analyze
from report import StabilityReport, write_summary_table


@dataclass
class WorkflowConfig:
    primitive_cell_file: str = "primitive_cells/NaCoO2.cif"
    host_formula: str = "NaCoO2"
    target_element: str = "Co"
    dopant: str = "Al"
    supercell_size: int = 2
    chgnet_model: str = "r2scan"
    run_md: bool = True
    md_top_n: int = 1                       # MD on this many lowest-E_f sites
    md_spec: MDRunSpec = None
    reports_dir: str = "reports"
    relaxed_dir: str = "relaxed_structures"
    analysis_dir: str = "analysis"
    references_file: str = "references.json"

    def __post_init__(self):
        if self.md_spec is None:
            self.md_spec = MDRunSpec()


def header(title):
    bar = "#" * 78
    print("\n" + bar)
    print(f"# {title}")
    print(bar)


def run(config):
    Path(config.reports_dir).mkdir(parents=True, exist_ok=True)

    header("Loading CHGNet")
    chgnet = CHGNet.load(model_name=config.chgnet_model)

    header(f"Phase 1: chemical potentials for {config.dopant}, {config.target_element}")
    mus = get_or_compute_references(
        [config.dopant, config.target_element],
        chgnet=chgnet,
        path=config.references_file,
    )

    header(f"Phase 2-3: pristine supercell + site enumeration")
    primitive, supercell, pristine_final, pristine_energy, pristine_sg = relax_pristine(
        config.primitive_cell_file, config.supercell_size, chgnet, output_dir=config.relaxed_dir
    )
    candidates = enumerate_sites(pristine_final, config.target_element)
    print(f"Found {len(candidates)} symmetrically distinct {config.target_element} site(s):")
    for c in candidates:
        print(f"  site {c.site_index}  multiplicity={c.multiplicity}  frac={c.fractional_coords}")

    header("Phase 3: relax each doped configuration + formation energies")
    configurations = []
    for candidate in candidates:
        label = f"site{candidate.site_index}"
        relaxed = relax_doped(
            pristine_final, candidate.site_index, config.dopant, config.target_element,
            chgnet, output_dir=config.relaxed_dir, label=label,
        )
        e_f = formation_energy(
            relaxed.final_energy_eV,
            pristine_energy,
            mu_removed=mus[config.target_element],
            mu_dopant=mus[config.dopant],
        )
        print(f"  [{label}] E_f = {e_f:+.4f} eV")
        configurations.append((candidate, relaxed, e_f))

    configurations.sort(key=lambda x: x[2])

    reports = []
    for rank, (candidate, relaxed, e_f) in enumerate(configurations):
        test_name = f"{config.dopant}@{config.target_element}_site{candidate.site_index}_rank{rank+1}"
        do_md = config.run_md and rank < config.md_top_n
        header(f"Test {rank+1}/{len(configurations)}: {test_name}  (run_md={do_md})")

        report = StabilityReport(
            test_name=test_name,
            host_formula=config.host_formula,
            dopant=config.dopant,
            target_site_element=config.target_element,
            site_index=candidate.site_index,
            supercell_size=config.supercell_size,
            formation_energy_eV=e_f,
            pristine_energy_eV=pristine_energy,
            doped_energy_eV=relaxed.final_energy_eV,
            mu_dopant_eV=mus[config.dopant],
            mu_removed_eV=mus[config.target_element],
            relaxed_space_group=relaxed.relaxed_space_group,
            relaxed_coordination=relaxed.coordination_number,
            relaxed_mean_nn_distance_A=(
                sum(relaxed.nn_distances_A) / len(relaxed.nn_distances_A)
                if relaxed.nn_distances_A else None
            ),
            relaxed_nn_distances_A=relaxed.nn_distances_A,
        )
        report.notes.append(
            f"Symmetric multiplicity of this site in the pristine supercell: {candidate.multiplicity}"
        )

        if do_md:
            md_result = run_md(relaxed.final_structure, chgnet, label=test_name, spec=config.md_spec)
            analysis = analyze(
                md_result,
                dopant_symbol=config.dopant,
                output_dir=config.analysis_dir,
            )
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

        report.print_report()
        report_path = Path(config.reports_dir) / f"{test_name}.json"
        report.save(report_path)
        print(f"  saved report -> {report_path}")
        reports.append(report)

    header("Summary across all candidates")
    summary_path = Path(config.reports_dir) / "summary.csv"
    write_summary_table(reports, summary_path)
    print(f"Wrote summary -> {summary_path}")
    print("\nRanked by E_f (lowest = most favorable):")
    print(f"  {'site':>6}  {'E_f (eV)':>10}  {'verdict'}")
    for r in reports:
        print(f"  {r.site_index:>6}  {r.formation_energy_eV:>+10.4f}  {r.verdict}")
    return reports


if __name__ == "__main__":
    config = WorkflowConfig(
        primitive_cell_file="primitive_cells/NaCoO2.cif",
        host_formula="NaCoO2",
        target_element="Co",
        dopant="Al",
        supercell_size=2,
        chgnet_model="r2scan",
        run_md=True,
        md_top_n=1,
        md_spec=MDRunSpec(
            temperature_C=250.0,
            timestep_fs=2.0,
            equilibration_steps=2500,
            production_steps=25000,
            loginterval=10,
        ),
    )
    run(config)
