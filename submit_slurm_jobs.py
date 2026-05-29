"""
SLURM submission + resume manager for the doping-stability workflow.

Designed for a cluster with a hard wall-time limit (e.g. 4 h) where each
workflow run is a separate sbatch job and long MD runs often time out. It:

  1. Scans the on-disk caches to classify every job as FINISHED or, if not,
     which phase it would resume from (pristine relax / doped relax / MD /
     analysis+report). MD resume is automatic inside run_workflow.py — see
     run_md._fold_segment — so re-submitting the same command continues a
     timed-out MD from its last checkpointed timestep.
  2. Prints the finished cases and the jobs that will be submitted.
  3. Writes one .sbatch per pending job (customised --output, --job-name and
     the run_workflow.py command) and submits it with
     subprocess.call("sbatch <file>", shell=True).

Usage
-----
    python submit_slurm_jobs.py --status     # classify only, submit nothing
    python submit_slurm_jobs.py --dry-run    # write .sbatch files + print, no sbatch
    python submit_slurm_jobs.py              # write + submit pending jobs

Notes
-----
- All jobs run at run_workflow.py's default MD temperature (250 C). This CLI
  path does not vary temperature; add a --temperature flag to run_workflow.py
  first if you need multiple temperatures per (host, dopant).
- A job already queued/running in SLURM (matched by job name) is skipped to
  avoid duplicate submissions.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from glob import glob
from pathlib import Path

# ── Paths / cache locations ───────────────────────────────────────────────────
RELAXED_DIR = Path("relaxed_structures")
MD_DIR = Path("md_runs")
REPORTS_DIR = Path("reports")
SBATCH_DIR = Path("slurm_scripts")

# MD step budget — mirrors MDRunSpec built in run_workflow.config_from_args.
MD_LOGINTERVAL = 10
MD_TOTAL_STEPS = 1250 + 12500  # equilibration + production

# Host alkali sites — mirror of run_workflow.HOSTS[...]['alkali_site'].
HOST_ALKALI: dict[str, str] = {"NaCoO2": "Na", "KCoO2": "K", "LiCoO2": "Li"}

SBATCH_TEMPLATE = """#!/bin/bash
#SBATCH --partition secondary
#SBATCH --nodes 1
#SBATCH --ntasks 1
#SBATCH --cpus-per-task 1
#SBATCH --time 4:00:00
#SBATCH --output {jobname}.log
#SBATCH --job-name {jobname}
module load anaconda/2023-Mar/3
export OMP_NUM_THREADS=1

source activate chgnet
python run_workflow.py --host {host} --dopant {dopant} --sites {sites} --temperature {temp}
"""

# ── Job list (edit me) ────────────────────────────────────────────────────────
# Each entry is ONE sbatch submission = one run_workflow.py call.
#   sites: list of --sites tokens; ["Co", "alkali"] tests both layers.
#   temp:  MD temperature in C (one job per temperature).
# Keep (host, dopant, temp) unique — detection keys on those.
NCO_KCO_DOPANTS = ["Cr", "Fe", "Ca", "Al", "Ni", "Zn", "Mn", "Mg"]
NCO_KCO_TEMPS = [200, 300]
LCO_DOPANTS = [
    "Al", "Ca", "Sc", "Ti", "Cr", "Mn", "Fe", "Ni", "Cu", "Zn",
    "Sr", "Y", "Nb", "Sn", "Sb", "Ba", "La",
]
LCO_TEMPS = [320, 350]


def default_jobs() -> list[dict]:
    jobs: list[dict] = []
    for host in ("NaCoO2", "KCoO2"):
        for dopant in NCO_KCO_DOPANTS:
            for temp in NCO_KCO_TEMPS:
                jobs.append({"host": host, "dopant": dopant,
                             "sites": ["Co", "alkali"], "temp": temp})
    for dopant in LCO_DOPANTS:
        for temp in LCO_TEMPS:
            jobs.append({"host": "LiCoO2", "dopant": dopant,
                         "sites": ["Co", "alkali"], "temp": temp})
    return jobs


# ── Helpers ───────────────────────────────────────────────────────────────────

def temp_tag(job: dict) -> str:
    return f"T{int(job['temp'])}"


def job_name(job: dict) -> str:
    return f"chgnet_{job['host']}_{job['dopant']}_{'_'.join(job['sites'])}_{temp_tag(job)}"


def resolve_targets(host: str, sites: list[str]) -> list[str]:
    """Map --sites tokens to host element symbols (mirrors run_workflow)."""
    alkali = HOST_ALKALI[host]
    out: list[str] = []
    for s in sites:
        tok = s.lower()
        if tok == "co":
            out.append("Co")
        elif tok in ("alkali", "na", "k", "li"):
            out.append(alkali)
        else:
            raise ValueError(f"Unknown site token {s!r} for host {host}")
    seen: set[str] = set()
    uniq: list[str] = []
    for e in out:
        if e not in seen:
            seen.add(e)
            uniq.append(e)
    return uniq


def _count_frames(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        from ase.io.trajectory import Trajectory
        n = 0
        with Trajectory(str(path), "r") as traj:
            for _ in traj:
                n += 1
        return n
    except Exception:
        return 0


def _md_steps_done(md_subdir: Path) -> int:
    frames = _count_frames(md_subdir / "md.traj") + _count_frames(md_subdir / "md_segment.traj")
    return frames * MD_LOGINTERVAL


def _target_md_dirs(host: str, dopant: str, target: str, tag: str) -> list[Path]:
    # MD/analysis are namespaced by temperature (md_runs/T###); relaxations are not.
    return [Path(p) for p in glob(str(MD_DIR / tag / f"{host}_{dopant}@{target}_site*"))]


def _target_relaxed(host: str, dopant: str, target: str) -> bool:
    return bool(glob(str(RELAXED_DIR / f"{host}_{dopant}@{target}_*site*.cif")))


def _final_report_exists(host: str, dopant: str, tag: str) -> bool:
    return bool(glob(str(REPORTS_DIR / "**" / tag / f"{host}_{dopant}_final.json"),
                     recursive=True))


def job_status(job: dict) -> dict:
    """Classify a job. Returns {finished: bool, phase: str}."""
    host, dopant = job["host"], job["dopant"]
    tag = temp_tag(job)
    targets = resolve_targets(host, job["sites"])

    if not (RELAXED_DIR / f"{host}_pristine_2.cif").exists():
        return {"finished": False, "phase": "Phase 2 (pristine relaxation)"}

    needs_relax: list[str] = []
    md_partial: list[tuple[str, int]] = []
    md_start: list[str] = []

    for t in targets:
        dirs = _target_md_dirs(host, dopant, t, tag)
        if any((d / "md.complete.json").exists() for d in dirs):
            continue  # MD done for this target
        if not _target_relaxed(host, dopant, t):
            needs_relax.append(t)
            continue
        steps = max((_md_steps_done(d) for d in dirs), default=0)
        if steps > 0:
            md_partial.append((t, steps))
        else:
            md_start.append(t)

    if needs_relax:
        return {"finished": False, "phase": f"Phase 3 (doped relaxation: {', '.join(needs_relax)})"}
    if md_partial:
        t, steps = md_partial[0]
        pct = 100 * steps / MD_TOTAL_STEPS
        return {"finished": False,
                "phase": f"Phase 4 (MD resume {t}: ~{steps}/{MD_TOTAL_STEPS} steps, {pct:.0f}%)"}
    if md_start:
        return {"finished": False, "phase": f"Phase 4 (MD start: {', '.join(md_start)})"}
    if not _final_report_exists(host, dopant, tag):
        return {"finished": False, "phase": "Phase 5-6 (analysis + report)"}
    return {"finished": True, "phase": "complete"}


def _already_queued(name: str) -> bool:
    """True if a SLURM job with this name is pending/running for the user."""
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    try:
        out = subprocess.run(
            ["squeue", "-h", "-o", "%j", "-u", user],
            capture_output=True, text=True, timeout=15,
        )
        return name in out.stdout.split()
    except Exception:
        return False


def write_sbatch(job: dict) -> Path:
    SBATCH_DIR.mkdir(exist_ok=True)
    name = job_name(job)
    content = SBATCH_TEMPLATE.format(
        jobname=name,
        host=job["host"],
        dopant=job["dopant"],
        sites=" ".join(job["sites"]),
        temp=job["temp"],
    )
    path = SBATCH_DIR / f"{name}.sbatch"
    path.write_text(content)
    return path


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SLURM submit + resume manager.")
    parser.add_argument("--status", action="store_true",
                        help="Only classify jobs and print; submit nothing.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Write .sbatch files and print, but do not run sbatch.")
    args = parser.parse_args(argv)

    jobs = default_jobs()
    finished, pending = [], []
    for job in jobs:
        st = job_status(job)
        (finished if st["finished"] else pending).append((job, st))

    print("=" * 72)
    print(f"  Jobs: {len(jobs)} total - {len(finished)} finished, {len(pending)} to run")
    print("=" * 72)

    print(f"\nFINISHED ({len(finished)}):")
    if finished:
        for job, _ in finished:
            print(f"  [done] {job['host']} {job['dopant']} "
                  f"({'+'.join(job['sites'])}) @ {job['temp']} C")
    else:
        print("  (none yet)")

    print(f"\nTO SUBMIT ({len(pending)}):")
    for job, st in pending:
        print(f"  [{st['phase']}]  {job['host']} {job['dopant']} "
              f"({'+'.join(job['sites'])}) @ {job['temp']} C")

    if args.status:
        print("\n--status: nothing submitted.")
        return 0

    if not pending:
        print("\nAll jobs finished — nothing to submit.")
        return 0

    have_sbatch = shutil.which("sbatch") is not None
    if not have_sbatch and not args.dry_run:
        print("\n  'sbatch' not found on PATH — generating scripts only (no submission).")

    print()
    submitted = skipped = 0
    for job, st in pending:
        name = job_name(job)
        if _already_queued(name):
            print(f"  [skip] {name} already in SLURM queue")
            skipped += 1
            continue
        path = write_sbatch(job)
        if args.dry_run or not have_sbatch:
            print(f"  [would submit] {path}  ->  resume at {st['phase']}")
        else:
            print(f"  [submit] {path}  ->  resume at {st['phase']}")
            subprocess.call(f"sbatch {path}", shell=True)
            submitted += 1

    print("\n" + "=" * 72)
    if args.dry_run or not have_sbatch:
        print(f"  Dry run: {len(pending) - skipped} script(s) written to {SBATCH_DIR}/, "
              f"{skipped} skipped (already queued).")
    else:
        print(f"  Submitted {submitted} job(s); skipped {skipped} already-queued.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
