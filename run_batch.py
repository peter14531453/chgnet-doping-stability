"""
Unattended batch runner — safe for nohup, no interactive menu needed.

Usage:
    nohup python run_batch.py > output.log 2>&1 &

Check progress while running:
    tail -f output.log
    ls -lt relaxed_structures/ | head -20
    ls -lt reports/

Per-temperature MD caching: relaxed structures are shared across temperatures
(computed once), but MD trajectories and analysis go into separate subdirs
(md_runs/T200/, analysis/T200/, etc.) so two temperatures never overwrite each
other's results.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date

import torch
from chgnet.model.model import CHGNet

from dopant_database import DOPANTS
from run_md import MDRunSpec
from run_workflow import HOSTS, WorkflowConfig, run

# ── Queue definition ──────────────────────────────────────────────────────────

# NCO + KCO: 8 dopants, both layers, MD at 200 °C and 300 °C
NCO_KCO_DOPANTS: list[str] = ["Cr", "Fe", "Ca", "Al", "Ni", "Zn", "Mn", "Mg"]
NCO_KCO_TEMPS: list[float] = [200.0, 300.0]

# LCO: all colored elements from the reference periodic table that are in the
# dopant database.  Excluded (not in DB): Ce, Pb, Bi.
LCO_DOPANTS: list[str] = [
    "Al", "Ca", "Sc", "Ti", "Cr", "Mn", "Fe", "Ni", "Cu", "Zn",
    "Sr", "Y", "Nb", "Sn", "Sb", "Ba", "La",
]
LCO_TEMPS: list[float] = [320.0, 350.0]

# ── Load CHGNet once ──────────────────────────────────────────────────────────

print("=" * 70)
print("CHGNet batch runner — loading model...")
chgnet = CHGNet.load(model_name="r2scan")
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Device: {device}")
if device == "cuda":
    print(f"GPU: {torch.cuda.get_device_name(0)}")
print("=" * 70)

# ── Build job list ────────────────────────────────────────────────────────────
# Each job = (host_key, dopant, temperature_C)

jobs: list[tuple[str, str, float]] = []

for host_key in ("NaCoO2", "KCoO2"):
    for dopant in NCO_KCO_DOPANTS:
        for temp in NCO_KCO_TEMPS:
            jobs.append((host_key, dopant, temp))

for dopant in LCO_DOPANTS:
    for temp in LCO_TEMPS:
        jobs.append(("LiCoO2", dopant, temp))

print(f"\nTotal jobs queued: {len(jobs)}")
print(f"  NCO: {len(NCO_KCO_DOPANTS)} dopants × {len(NCO_KCO_TEMPS)} temps = "
      f"{len(NCO_KCO_DOPANTS)*len(NCO_KCO_TEMPS)} configs")
print(f"  KCO: {len(NCO_KCO_DOPANTS)} dopants × {len(NCO_KCO_TEMPS)} temps = "
      f"{len(NCO_KCO_DOPANTS)*len(NCO_KCO_TEMPS)} configs")
print(f"  LCO: {len(LCO_DOPANTS)} dopants × {len(LCO_TEMPS)} temps = "
      f"{len(LCO_DOPANTS)*len(LCO_TEMPS)} configs")
print(f"\n  (Relaxed structures are cached and shared across temperatures.)")
print(f"  (MD and analysis use per-temperature subdirectories.)\n")

# ── Run all jobs ──────────────────────────────────────────────────────────────

run_date = date.today().isoformat()
errors: list[str] = []

for i, (host_key, dopant, temp_C) in enumerate(jobs, 1):
    host_cfg = HOSTS[host_key]
    alkali = host_cfg["alkali_site"]
    temp_tag = f"T{int(temp_C)}"

    print(f"\n{'#'*70}")
    print(f"#  JOB {i}/{len(jobs)}: {dopant} on {host_cfg['host_formula']}  "
          f"sites=[Co, {alkali}]  T={temp_C} °C")
    print(f"{'#'*70}")

    config = WorkflowConfig(
        primitive_cell_file=host_cfg["primitive_cell_file"],
        host_formula=host_cfg["host_formula"],
        target_elements=["Co", alkali],
        dopant=dopant,
        compensation_ref=host_cfg["compensation_ref"],
        dopant_oxidation_state=DOPANTS[dopant].oxidation_state,
        run_md=True,
        # Relaxed structures are temperature-independent — share across all runs.
        relaxed_dir="relaxed_structures",
        # MD trajectories and analysis are temperature-specific.
        analysis_dir=f"analysis/{temp_tag}",
        reports_dir=f"reports/{run_date}/{temp_tag}",
        md_spec=MDRunSpec(
            temperature_C=temp_C,
            timestep_fs=2.0,
            equilibration_steps=1250,
            production_steps=12500,
            loginterval=10,
            output_dir=f"md_runs/{temp_tag}",
        ),
    )

    try:
        run(config, chgnet=chgnet)
    except Exception as exc:
        msg = f"JOB {i} FAILED: {dopant}@{host_key} {temp_C}°C — {exc}"
        print(f"\n  !! {msg}")
        errors.append(msg)
        print("  Continuing to next job...\n")
        continue

# ── Final summary ─────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("BATCH COMPLETE")
print(f"  {len(jobs) - len(errors)}/{len(jobs)} jobs finished successfully.")
if errors:
    print(f"\n  {len(errors)} job(s) failed:")
    for e in errors:
        print(f"    - {e}")
print("=" * 70)
