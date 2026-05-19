"""
Phase 4 - Finite-temperature NVT molecular dynamics.

Supports:
  - Per-test caching: a `md.complete.json` marker means the trajectory is
    final and a rerun skips this phase entirely.
  - Mid-run resume: if `md.traj` exists but is partial, the last frame is
    used as the new starting point and the trajectory is concatenated when
    the remaining steps finish. Velocities are preserved across the resume.
  - Progress callback: pass a TestProgress and the bar advances every
    `loginterval` MD steps.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ase.io import read as ase_read
from ase.io.trajectory import Trajectory
from pymatgen.io.ase import AseAtomsAdaptor
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


def _completion_info(spec, T, traj_path, log_path):
    duration_ps = spec.production_steps * spec.timestep_fs / 1000
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


def _read_partial(traj_path):
    if not traj_path.exists():
        return []
    try:
        return ase_read(str(traj_path), index=":")
    except Exception as exc:
        print(f"  warning: trajectory at {traj_path} unreadable ({exc}); restarting from scratch")
        traj_path.unlink()
        return []


def _concat_trajectories(traj_paths, output_path):
    with Trajectory(str(output_path), "w") as out_traj:
        for tp in traj_paths:
            for atoms in ase_read(str(tp), index=":"):
                out_traj.write(atoms)


def run_md(structure, chgnet, label, spec=None, progress=None):
    spec = spec or MDRunSpec()
    out_dir = Path(spec.output_dir) / label
    out_dir.mkdir(parents=True, exist_ok=True)
    traj_path = out_dir / "md.traj"
    log_path = out_dir / "md.log"
    complete_path = out_dir / "md.complete.json"

    T = temperature_K(spec)
    total_steps = spec.equilibration_steps + spec.production_steps
    info = _completion_info(spec, T, traj_path, log_path)

    if complete_path.exists():
        print(f"  [cached] MD already complete for {label} -> {traj_path}")
        if progress:
            progress.md_complete()
        return info

    existing_frames = _read_partial(traj_path)
    steps_already_done = len(existing_frames) * spec.loginterval
    steps_remaining = total_steps - steps_already_done

    if steps_remaining <= 0:
        complete_path.write_text(json.dumps(info, indent=2))
        if progress:
            progress.md_complete()
        return info

    if existing_frames:
        starting_atoms = existing_frames[-1].copy()
        print(
            f"  resuming MD from step {steps_already_done}/{total_steps} "
            f"({len(existing_frames)} frames preserved)"
        )
        if progress:
            progress.md(steps_already_done)
    else:
        starting_atoms = AseAtomsAdaptor.get_atoms(structure)

    print(
        f"Starting MD: {label}  T = {T:.1f} K ({spec.temperature_C} C)  "
        f"dt = {spec.timestep_fs} fs  steps remaining = {steps_remaining}"
    )
    if progress:
        progress.phase("md_setup")

    segment_traj = out_dir / "md_segment.traj"
    if segment_traj.exists():
        segment_traj.unlink()

    md = MolecularDynamics(
        atoms=starting_atoms,
        model=chgnet,
        ensemble="nvt",
        temperature=T,
        timestep=spec.timestep_fs,
        trajectory=str(segment_traj),
        logfile=str(log_path),
        loginterval=spec.loginterval,
    )

    if progress:
        def update_progress(_md=md, _base=steps_already_done):
            progress.md(_base + _md.dyn.nsteps)
        md.dyn.attach(update_progress, interval=spec.loginterval)

    md.run(steps_remaining)

    if existing_frames:
        backup_old = traj_path.with_suffix(".traj.prev")
        traj_path.replace(backup_old)
        _concat_trajectories([backup_old, segment_traj], traj_path)
        backup_old.unlink()
        segment_traj.unlink()
    else:
        if traj_path.exists():
            traj_path.unlink()
        segment_traj.replace(traj_path)

    complete_path.write_text(json.dumps(info, indent=2))
    if progress:
        progress.md_complete()
    print(f"MD complete -> {traj_path}")
    return info
