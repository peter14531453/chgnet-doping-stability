"""
Phase 4 - Finite-temperature NVT molecular dynamics.

Default parameters target the user's 250 C use case but are exposed for tuning.
Equilibration is followed by production; only production frames feed the
trajectory analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chgnet.model.dynamics import MolecularDynamics


@dataclass
class MDRunSpec:
    temperature_C: float = 250.0
    timestep_fs: float = 2.0
    equilibration_steps: int = 2500
    production_steps: int = 25000
    loginterval: int = 10
    output_dir: str = "md_runs"


def temperature_K(spec):
    return 273.15 + spec.temperature_C


def run_md(structure, chgnet, label, spec=None):
    spec = spec or MDRunSpec()
    out_dir = Path(spec.output_dir) / label
    out_dir.mkdir(parents=True, exist_ok=True)
    traj_path = out_dir / "md.traj"
    log_path = out_dir / "md.log"

    T = temperature_K(spec)
    print(
        f"Starting MD: {label}  T = {T:.1f} K ({spec.temperature_C} C)  "
        f"dt = {spec.timestep_fs} fs"
    )
    print(
        f"  equilibration: {spec.equilibration_steps} steps "
        f"({spec.equilibration_steps * spec.timestep_fs / 1000:.1f} ps)"
    )
    print(
        f"  production:    {spec.production_steps} steps "
        f"({spec.production_steps * spec.timestep_fs / 1000:.1f} ps)"
    )

    md = MolecularDynamics(
        atoms=structure,
        model=chgnet,
        ensemble="nvt",
        temperature=T,
        timestep=spec.timestep_fs,
        trajectory=str(traj_path),
        logfile=str(log_path),
        loginterval=spec.loginterval,
    )
    total_steps = spec.equilibration_steps + spec.production_steps
    md.run(total_steps)

    duration_ps = spec.production_steps * spec.timestep_fs / 1000
    print(f"MD complete -> {traj_path}")
    return {
        "trajectory_path": str(traj_path),
        "log_path": str(log_path),
        "temperature_K": T,
        "duration_ps": duration_ps,
        "timestep_fs": spec.timestep_fs,
        "loginterval": spec.loginterval,
        "equilibration_frames": spec.equilibration_steps // spec.loginterval,
        "production_frames": spec.production_steps // spec.loginterval,
    }
