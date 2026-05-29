"""
Interactive batch selector for the doping-stability workflow.

Lets you queue a *group* of trials in one session, mixing hosts and dopants
freely -- e.g. Al/Mn on LiCoO2, Ti on KCoO2, and Sb/Sr/Al/Mn on NaCoO2 -- then
runs them back to back with a single CHGNet load and a combined ranking at the
end.

Flow
----
1. Pick which primitive cells (hosts) to test.
2. For each chosen host, pick its dopants (all pre-selected; Ctrl+A select all,
   Alt+D deselect all, Ctrl+R invert) and which sites to substitute (Co and the
   host alkali, both pre-selected).
3. For each host, choose the MD temperature(s) in Celsius (e.g. "200, 300").
   Leave blank to skip MD for that host (relaxation + E_f screening only).
   Each selected dopant runs once per chosen temperature.
4. Review the queued runs, then confirm.

Run with:
    python interactive.py
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from charge_utils import charge_mismatch as compute_charge_mismatch
from dopant_database import (
    CATEGORY_LABELS,
    CATEGORY_ORDER,
    DOPANTS,
    by_category,
)
from progress import info
from report import write_summary_table
from run_md import MDRunSpec
from run_workflow import HOSTS, WorkflowConfig, run


# Keybindings shared by the dopant checkboxes: deselect-all is unbound by
# default in InquirerPy, so we wire Alt+D / Ctrl+D to it.
_DESELECT_ALL = {"toggle-all-false": [{"key": "alt-d"}, {"key": "c-d"}]}


@dataclass
class Job:
    host_key: str
    dopant: str
    sites: list[str]
    temperature: float = 250.0  # MD temperature in C (ignored when run_md is False)
    run_md: bool = True

    @property
    def alias(self) -> str:
        return HOSTS[self.host_key]["alias"]

    @property
    def temp_tag(self) -> str:
        return f"T{int(round(self.temperature))}"


def _host_label(host_key: str) -> str:
    cfg = HOSTS[host_key]
    return f"{cfg['host_formula']} ({cfg['alias']})"


def select_hosts() -> list[str]:
    choices = [
        Choice(value=key, name=_host_label(key), enabled=False)
        for key in HOSTS
    ]
    return inquirer.checkbox(
        message="Which primitive cells do you want to test?",
        choices=choices,
        instruction="(space: toggle, ctrl+a: all, enter: confirm)",
        keybindings=_DESELECT_ALL,
        validate=lambda result: len(result) >= 1,
        invalid_message="Select at least one host.",
        cycle=True,
        transformer=lambda result: ", ".join(result) if result else "none",
    ).execute()


def select_dopants(host_key: str) -> list[str]:
    """Grouped dopant checkbox for one host. All pre-selected (Enter = all)."""
    choices: list = []
    for category in CATEGORY_ORDER:
        members = by_category(category)
        if not members:
            continue
        choices.append(Separator(f"── {CATEGORY_LABELS[category]} ──"))
        for d in members:
            choices.append(
                Choice(
                    value=d.symbol,
                    name=f"{d.symbol}  ({d.oxidation_state:+d})",
                    enabled=True,
                )
            )

    return inquirer.checkbox(
        message=f"Dopants for {_host_label(host_key)}:",
        choices=choices,
        instruction="(space: toggle, ctrl+a: all, alt+d: none, ctrl+r: invert)",
        keybindings=_DESELECT_ALL,
        validate=lambda result: len(result) >= 1,
        invalid_message="Pick at least one dopant (or Ctrl+C to cancel).",
        cycle=True,
        transformer=lambda result: f"{len(result)} dopant(s): {', '.join(result)}",
    ).execute()


def select_sites(host_key: str) -> list[str]:
    """Site checkbox for one host: Co and the host alkali, both pre-selected."""
    alkali = HOSTS[host_key]["alkali_site"]
    choices = [
        Choice(value="Co", name="Co layer (transition-metal site)", enabled=True),
        Choice(value=alkali, name=f"{alkali} layer (alkali site)", enabled=True),
    ]
    return inquirer.checkbox(
        message=f"Sites for {_host_label(host_key)}:",
        choices=choices,
        instruction="(both run by default to compare site preference)",
        validate=lambda result: len(result) >= 1,
        invalid_message="Pick at least one site.",
        cycle=True,
        transformer=lambda result: ", ".join(result),
    ).execute()


def _parse_temps(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        return []
    return [float(p) for p in re.split(r"[,\s]+", text) if p]


def select_temperatures(host_key: str) -> list[float]:
    """Ask for this host's MD temperature(s). Blank = no MD (relaxation only)."""
    def _validate(s: str) -> bool:
        try:
            _parse_temps(s)
            return True
        except ValueError:
            return False

    return inquirer.text(
        message=f"MD temperature(s) for {_host_label(host_key)} in C "
                f"(comma-separated; blank = no MD, relaxation only):",
        default="",
        validate=_validate,
        invalid_message="Enter numbers like '200, 300', or leave blank to skip MD.",
        filter=_parse_temps,
    ).execute()


def build_jobs() -> list[Job]:
    hosts = select_hosts()
    jobs: list[Job] = []
    for host_key in hosts:
        info()
        info(f"══ Configure {_host_label(host_key)} ══")
        dopants = select_dopants(host_key)
        sites = select_sites(host_key)
        temps = select_temperatures(host_key)
        if temps:
            for dopant in dopants:
                for temp in temps:
                    jobs.append(Job(host_key=host_key, dopant=dopant, sites=sites,
                                    temperature=temp, run_md=True))
        else:
            for dopant in dopants:
                jobs.append(Job(host_key=host_key, dopant=dopant, sites=sites,
                                run_md=False))
    return jobs


def _positive_mismatch_sites(job: Job) -> list[tuple[str, int]]:
    """Sites where the dopant brings MORE charge than it replaces (E_f approx)."""
    flagged = []
    for site in job.sites:
        mismatch = compute_charge_mismatch(job.dopant, site)
        if mismatch > 0:
            flagged.append((site, mismatch))
    return flagged


def preflight_summary(jobs: list[Job]) -> None:
    info()
    info("#" * 70)
    info(f"#  QUEUED RUNS — {len(jobs)} (host × dopant × temperature)")
    info("#" * 70)

    by_host: dict[str, list[Job]] = {}
    for job in jobs:
        by_host.setdefault(job.host_key, []).append(job)

    warnings: set[str] = set()
    for host_key, host_jobs in by_host.items():
        sites = host_jobs[0].sites
        dopants = sorted({j.dopant for j in host_jobs})
        temps = sorted({j.temperature for j in host_jobs if j.run_md})
        info(f"  {_host_label(host_key)}")
        info(f"    dopants: {', '.join(dopants)}")
        info(f"    sites:   {', '.join(sites)}")
        if temps:
            info(f"    MD temps: {', '.join(f'{t:g} C' for t in temps)}")
        else:
            info("    MD: off (relaxation + E_f only)")
        for job in host_jobs:
            for site, mismatch in _positive_mismatch_sites(job):
                warnings.add(
                    f"{job.dopant} (+{DOPANTS[job.dopant].oxidation_state}) on "
                    f"{site} site of {job.alias}: +{mismatch} mismatch — "
                    f"uncompensated, E_f approximate"
                )

    if warnings:
        info()
        info("  ⚠ Charge-surplus cases (CHGNet cannot model the compensating electron):")
        for w in sorted(warnings):
            info(f"    - {w}")
    info("#" * 70)


def run_batch(jobs: list[Job]) -> None:
    from chgnet.model.model import CHGNet
    import torch

    run_date = date.today().isoformat()
    base_reports = f"reports/{run_date}"

    info()
    info("Loading CHGNet (shared across all queued runs)…")
    chgnet = CHGNet.load(model_name="r2scan")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    info(f"  Device: {device}")

    all_reports = []
    for i, job in enumerate(jobs, start=1):
        host_cfg = HOSTS[job.host_key]
        # MD/analysis/report outputs are namespaced by temperature so two
        # temperatures of the same dopant never collide on a shared cache;
        # relaxations (temperature-independent) stay in relaxed_structures/.
        if job.run_md:
            tag = job.temp_tag
            analysis_dir, reports_dir, md_output = (
                f"analysis/{tag}", f"{base_reports}/{tag}", f"md_runs/{tag}",
            )
            md_desc = f"{job.temperature:g} C"
        else:
            analysis_dir, reports_dir, md_output = "analysis", base_reports, "md_runs"
            md_desc = "no MD"

        info()
        info("=" * 70)
        info(f"  RUN {i}/{len(jobs)}: {job.dopant} on {_host_label(job.host_key)}  "
             f"sites={', '.join(job.sites)}  ({md_desc})")
        info("=" * 70)
        config = WorkflowConfig(
            primitive_cell_file=host_cfg["primitive_cell_file"],
            host_formula=host_cfg["host_formula"],
            target_elements=list(job.sites),
            dopant=job.dopant,
            compensation_ref=host_cfg["compensation_ref"],
            dopant_oxidation_state=DOPANTS[job.dopant].oxidation_state,
            run_md=job.run_md,
            analysis_dir=analysis_dir,
            reports_dir=reports_dir,
            md_spec=MDRunSpec(
                temperature_C=job.temperature,
                timestep_fs=2.0,
                equilibration_steps=1250,
                production_steps=12500,
                loginterval=10,
                output_dir=md_output,
            ),
        )
        reports = run(config, chgnet=chgnet)
        all_reports.extend(reports)

    _final_ranking(all_reports, base_reports)


def _final_ranking(reports, reports_dir: str) -> None:
    if not reports:
        info("No reports produced.")
        return

    summary_path = Path(reports_dir) / "batch_summary.csv"
    write_summary_table(reports, summary_path)

    info()
    info("#" * 70)
    info("#  COMBINED RANKING (all queued runs, lowest E_f first)")
    info("#" * 70)
    info(f"  {'Host':<10} {'Dopant':>6} {'Site':>5} {'T(C)':>6} {'E_f (eV)':>10}  Verdict")
    info("  " + "-" * 72)
    for r in sorted(reports, key=lambda x: x.formation_energy_eV):
        tc = f"{r.md_temperature_K - 273.15:.0f}" if r.md_temperature_K else "-"
        info(f"  {r.host_formula:<10} {r.dopant:>6} {r.target_site_element:>5} "
             f"{tc:>6} {r.formation_energy_eV:>+10.4f}  {r.verdict}")
    info()
    info(f"  Combined summary CSV -> {summary_path}")


def main() -> int:
    info("CHGNet doping-stability — interactive batch setup")
    try:
        jobs = build_jobs()
    except KeyboardInterrupt:
        info("\nCancelled.")
        return 130

    if not jobs:
        info("No runs queued.")
        return 0

    preflight_summary(jobs)

    try:
        start = inquirer.confirm(message="Start these runs now?", default=True).execute()
    except KeyboardInterrupt:
        info("\nCancelled.")
        return 130
    if not start:
        info("Aborted — nothing run.")
        return 0

    run_batch(jobs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
