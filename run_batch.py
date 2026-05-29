"""
Unattended batch runner with crash-safe resume — built for the 24h Jupyter cap.

The host (e.g. an ICRN Jupyter notebook) may end the session after ~24h without
warning. Finished work is preserved on disk; this script lets a new session pick
up exactly where the last one stopped, with all reports for one sweep collected
in a single folder.

Key behaviours
--------------
- Stable run folder: reports live under  reports/<run_id>/T###/  where run_id is
  fixed when the sweep first starts (NOT today's date), so a restart on a later
  day keeps writing into the same folder instead of creating a new dated one.
- Continuation rename: resuming on a later day renames the folder to
  reports/<run_id>__cont_<latest_day>. Only the most recent continuation date is
  kept — a third-day restart shows __cont_<3rd day>, not a chain of every date.
  So the name is always "started date __cont_ latest day worked".
- Resume: a job is "done" when its <host>_<dopant>_final.json exists on disk.
  Finished jobs are skipped. Partial MD is recovered frame-by-frame by run_md
  (md_segment.traj is folded back in), so an interrupted MD continues mid-run.
- Status: `python run_batch.py --status` prints done/remaining and exits (no
  compute, fast).
- Fresh:  `python run_batch.py --fresh` archives the old manifest and starts a
  brand-new sweep.

Usage
-----
    python run_batch.py --status                       # inspect progress
    nohup python run_batch.py >> output.log 2>&1 &     # run or resume

(tmux is not installed on this server — use nohup to survive a browser close.)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from dopant_database import DOPANTS
from report import run_report_stem

# ── Queue definition ──────────────────────────────────────────────────────────

# NCO + KCO: 8 dopants, both layers (Co + alkali), MD at 200 and 300 C.
NCO_KCO_DOPANTS: list[str] = ["Cr", "Fe", "Ca", "Al", "Ni", "Zn", "Mn", "Mg"]
NCO_KCO_TEMPS: list[float] = [200.0, 300.0]

# LCO: colored elements from the reference periodic table that are in the
# dopant database. Excluded (not in DB): Ce, Pb, Bi. MD at 320 and 350 C.
LCO_DOPANTS: list[str] = [
    "Al", "Ca", "Sc", "Ti", "Cr", "Mn", "Fe", "Ni", "Cu", "Zn",
    "Sr", "Y", "Nb", "Sn", "Sb", "Ba", "La",
]
LCO_TEMPS: list[float] = [320.0, 350.0]

STATE_FILE = Path("batch_state.json")
REPORTS_BASE = Path("reports")
EST_MIN_PER_JOB = 40  # ~2 MD runs x ~19 min, for a rough ETA only


def build_jobs() -> list[dict]:
    """Deterministic job list. Each job = one (host, dopant, temperature)."""
    jobs: list[dict] = []
    for host_key in ("NaCoO2", "KCoO2"):
        for dopant in NCO_KCO_DOPANTS:
            for temp in NCO_KCO_TEMPS:
                jobs.append({"host": host_key, "dopant": dopant, "temp": temp})
    for dopant in LCO_DOPANTS:
        for temp in LCO_TEMPS:
            jobs.append({"host": "LiCoO2", "dopant": dopant, "temp": temp})
    return jobs


# ── Manifest (batch_state.json) ───────────────────────────────────────────────

def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return None


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, STATE_FILE)  # atomic on the same filesystem


def new_state() -> dict:
    today = date.today().isoformat()
    return {
        "run_id": today,
        "created": today,
        "last_continued": None,
        "status": "running",
        "n_jobs": len(build_jobs()),
    }


def run_dir_name(state: dict) -> str:
    lc = state.get("last_continued")
    if lc and lc != state["run_id"]:
        return f"{state['run_id']}__cont_{lc}"
    return state["run_id"]


def run_dir(state: dict) -> Path:
    return REPORTS_BASE / run_dir_name(state)


def ensure_session(state: dict) -> None:
    """On a new calendar day, set the continuation suffix to *today* (replacing
    any earlier one) and rename the run folder accordingly."""
    today = date.today().isoformat()
    if today == state["run_id"] or today == state.get("last_continued"):
        return  # same day as start, or already continued today
    old_dir = run_dir(state)
    state["last_continued"] = today
    new_dir = run_dir(state)
    if old_dir.exists() and old_dir.resolve() != new_dir.resolve():
        if new_dir.exists():
            print(f"  warning: {new_dir} already exists; leaving folders as-is.")
        else:
            old_dir.rename(new_dir)
            print(f"  continuation: renamed {old_dir} -> {new_dir}")
    save_state(state)


# ── Resume reconciliation (disk is the source of truth) ───────────────────────

def job_final_path(job: dict, rdir: Path) -> Path:
    stem = run_report_stem(job["host"], job["dopant"])  # host == host_formula
    return rdir / f"T{int(job['temp'])}" / f"{stem}_final.json"


def split_done(jobs: list[dict], rdir: Path) -> tuple[list[dict], list[dict]]:
    done, remaining = [], []
    for job in jobs:
        (done if job_final_path(job, rdir).exists() else remaining).append(job)
    return done, remaining


def print_summary(state: dict, jobs: list[dict]) -> tuple[list[dict], list[dict]]:
    rdir = run_dir(state)
    done, remaining = split_done(jobs, rdir)
    print("=" * 70)
    print(f"  Run ID:    {state['run_id']}")
    print(f"  Folder:    {rdir}")
    if state.get("last_continued"):
        print(f"  Continued: {state['last_continued']}")
    print(f"  Status:    {state.get('status')}")
    print(f"  Progress:  {len(done)}/{len(jobs)} done, {len(remaining)} remaining")
    if remaining:
        eta_h = len(remaining) * EST_MIN_PER_JOB / 60
        print(f"  ETA:       ~{eta_h:.1f} h  (~{EST_MIN_PER_JOB} min/job)")
        print("  Next up:")
        for job in remaining[:8]:
            print(f"    - {job['dopant']:<3} on {job['host']:<7} @ {int(job['temp'])} C")
        if len(remaining) > 8:
            print(f"    ... and {len(remaining) - 8} more")
    else:
        print("  All jobs complete.")
    print("=" * 70)
    return done, remaining


# ── Run / resume ──────────────────────────────────────────────────────────────

def run_all(args: argparse.Namespace) -> int:
    import torch
    from chgnet.model.model import CHGNet
    from run_workflow import HOSTS, WorkflowConfig, run
    from run_md import MDRunSpec

    jobs = build_jobs()
    state = load_state()

    if args.fresh and state is not None:
        backup = Path(f"batch_state_{state['run_id']}.json")
        if not backup.exists():
            STATE_FILE.replace(backup)
            print(f"--fresh: archived previous manifest -> {backup}")
        state = None

    if state is None:
        state = new_state()
        save_state(state)
        print(f"Started new sweep (run_id={state['run_id']}).")
    else:
        ensure_session(state)  # rename folder if it's a new calendar day
        print(f"Resuming sweep (run_id={state['run_id']}).")

    state["status"] = "running"
    save_state(state)

    done, remaining = print_summary(state, jobs)
    if not remaining:
        state["status"] = "completed"
        save_state(state)
        print("Nothing to do — sweep already complete. Use --fresh to start over.")
        return 0

    if sys.stdin.isatty() and not args.yes:
        ans = input(f"Continue with {len(remaining)} remaining job(s)? [Y/n] ").strip().lower()
        if ans in ("n", "no"):
            print("Aborted — nothing run.")
            return 0
    else:
        print(f"(non-interactive) auto-continuing {len(remaining)} remaining job(s).")

    print("Loading CHGNet (shared across all jobs)...")
    chgnet = CHGNet.load(model_name="r2scan")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {dev}" + (f" ({torch.cuda.get_device_name(0)})" if dev == "cuda" else ""))

    rdir = run_dir(state)
    errors: list[str] = []

    for i, job in enumerate(remaining, 1):
        host_cfg = HOSTS[job["host"]]
        alkali = host_cfg["alkali_site"]
        temp_tag = f"T{int(job['temp'])}"

        print("\n" + "#" * 70)
        print(f"# JOB {i}/{len(remaining)} (overall {len(done) + i}/{len(jobs)}): "
              f"{job['dopant']} on {host_cfg['host_formula']}  "
              f"sites=[Co, {alkali}]  T={job['temp']} C")
        print("#" * 70)

        config = WorkflowConfig(
            primitive_cell_file=host_cfg["primitive_cell_file"],
            host_formula=host_cfg["host_formula"],
            target_elements=["Co", alkali],
            dopant=job["dopant"],
            compensation_ref=host_cfg["compensation_ref"],
            dopant_oxidation_state=DOPANTS[job["dopant"]].oxidation_state,
            run_md=True,
            relaxed_dir="relaxed_structures",          # shared cache
            analysis_dir=f"analysis/{temp_tag}",       # per-temperature
            reports_dir=str(rdir / temp_tag),          # per-temperature, in run folder
            md_spec=MDRunSpec(
                temperature_C=job["temp"],
                timestep_fs=2.0,
                equilibration_steps=1250,
                production_steps=12500,
                loginterval=10,
                output_dir=f"md_runs/{temp_tag}",      # per-temperature cache
            ),
        )

        try:
            run(config, chgnet=chgnet)
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            msg = f"{job['dopant']}@{job['host']} {job['temp']}C — {exc}"
            print(f"\n  !! JOB FAILED: {msg}\n  continuing to next job...")
            errors.append(msg)
            continue

    _, still = split_done(jobs, rdir)
    state["status"] = "completed" if not still else "interrupted"
    save_state(state)

    print("\n" + "=" * 70)
    print(f"BATCH RUN ENDED. {len(jobs) - len(still)}/{len(jobs)} complete; "
          f"{len(still)} still remaining.")
    if errors:
        print(f"  {len(errors)} job(s) errored this session:")
        for e in errors:
            print(f"    - {e}")
    print(f"  Reports folder: {rdir}")
    print("=" * 70)
    return 0


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crash-safe batch runner for the doping workflow.")
    p.add_argument("--status", action="store_true",
                   help="Print done/remaining for the current sweep and exit.")
    p.add_argument("--fresh", action="store_true",
                   help="Archive the existing manifest and start a brand-new sweep.")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip the interactive confirm prompt (for TTY use).")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.status:
        state = load_state() or new_state()
        print_summary(state, build_jobs())
        return 0
    return run_all(args)


if __name__ == "__main__":
    sys.exit(main())
