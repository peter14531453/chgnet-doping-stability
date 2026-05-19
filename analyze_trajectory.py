"""
Phase 5 - Trajectory analysis.

Loads the production segment of an MD trajectory and computes:

    - Mean-squared displacement of the dopant atom + late-time slope
    - Coordination number of the dopant over time
    - Mean nearest-neighbor distance
    - Lattice volume change vs initial
    - Space group of the time-averaged structure
    - Radial distribution function around the dopant (saved as CSV / PNG)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase.io import read as ase_read
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


def load_production_frames(trajectory_path, equilibration_frames=0):
    """Skip the first `equilibration_frames` frames so analysis only covers
    the production (thermally equilibrated) portion of the trajectory."""
    frames = ase_read(str(trajectory_path), index=":")
    return frames[equilibration_frames:]


def find_dopant_index(atoms, dopant_symbol):
    """Return the atom index of the dopant in the first trajectory frame.
    Assumes only one dopant atom per supercell (one substitution per run)."""
    matches = [i for i, atom in enumerate(atoms) if atom.symbol == dopant_symbol]
    if not matches:
        raise ValueError(f"No {dopant_symbol} atom found in trajectory frame.")
    if len(matches) > 1:
        print(f"  warning: {len(matches)} {dopant_symbol} atoms found; using index {matches[0]}")
    return matches[0]


def unwrapped_displacements(frames, atom_index):
    """Return Nx3 array of unwrapped displacements from the first frame.

    Periodic boundary conditions cause atoms to 'jump' when they cross a
    cell boundary, which would give artificially large displacements.
    We track the cumulative fractional-coordinate step each frame and
    apply the minimum-image convention (subtract nearest integer) so each
    inter-frame displacement is at most half a lattice vector — then
    accumulate to get the true unwrapped path.
    """
    r0 = frames[0].get_positions()[atom_index]
    disps = np.zeros((len(frames), 3))
    prev_wrapped = r0.copy()
    cumulative = np.zeros(3)
    for i, atoms in enumerate(frames):
        r = atoms.get_positions()[atom_index]
        delta = r - prev_wrapped
        cell = np.asarray(atoms.get_cell())
        # Convert to fractional coordinates to apply minimum-image convention
        frac_delta = np.linalg.solve(cell.T, delta)
        frac_delta -= np.round(frac_delta)   # wrap to [-0.5, 0.5]
        delta_unwrapped = cell.T @ frac_delta
        cumulative += delta_unwrapped
        disps[i] = cumulative
        prev_wrapped = r
    return disps


def compute_msd(displacements):
    """Mean-squared displacement: MSD(t) = <|r(t) - r(0)|^2>.
    A plateau means the atom is confined (stable site).
    A linear increase means long-range diffusion (migration)."""
    return np.sum(displacements ** 2, axis=1)


def late_time_slope(time_ps, msd, fraction=0.5):
    """Fit a line to the last `fraction` of the MSD curve and return its slope.

    Using only the late-time portion avoids the initial ballistic/subdiffusive
    regime. Slope near zero = plateau (stable). Slope >> 0 = diffusing dopant.
    Threshold in report.py: MSD_PLATEAU_SLOPE_A2_PER_PS = 0.005 A^2/ps.
    """
    n = len(msd)
    start = int(n * (1 - fraction))
    if n - start < 4:   # too few points for a reliable fit
        return float("nan")
    t = time_ps[start:]
    m = msd[start:]
    slope, _ = np.polyfit(t, m, 1)
    return float(slope)


def coordination_history(frames, atom_index, cutoff_A=2.5):
    """Count the number of atoms within cutoff_A of the dopant at every frame.

    cutoff_A=2.5 A isolates the first coordination shell only (e.g. the 6
    nearest O neighbours for a dopant on an octahedral site in a layered
    oxide). A larger cutoff would count second-shell transition metals and
    give a misleadingly large coordination number — see the Al test which
    showed coord=18 with the old 3.2 A cutoff.

    Ca-O and Mn-O bonds can reach ~2.4 A, so use coordination_cutoff_A=2.7
    in WorkflowConfig when testing Ca or other large-ion dopants.
    """
    coords = []
    for atoms in frames:
        positions = atoms.get_positions()
        cell = atoms.get_cell()
        pbc = atoms.get_pbc()
        target = positions[atom_index]
        deltas = positions - target
        if any(pbc):
            # Apply minimum-image convention for periodic boundaries
            frac = np.linalg.solve(np.asarray(cell).T, deltas.T).T
            frac -= np.round(frac)
            deltas = (np.asarray(cell).T @ frac.T).T
        distances = np.linalg.norm(deltas, axis=1)
        distances[atom_index] = np.inf   # exclude self
        coords.append(int(np.sum(distances < cutoff_A)))
    return coords


def mean_nn_distance(frames, atom_index, cutoff_A=2.5):
    """Average distance from the dopant to all first-shell neighbours
    across all production frames. Comparing this to the relaxed (0 K)
    value shows whether the local bond length expands at temperature."""
    distances_all = []
    for atoms in frames:
        positions = atoms.get_positions()
        cell = atoms.get_cell()
        target = positions[atom_index]
        deltas = positions - target
        frac = np.linalg.solve(np.asarray(cell).T, deltas.T).T
        frac -= np.round(frac)
        deltas = (np.asarray(cell).T @ frac.T).T
        distances = np.linalg.norm(deltas, axis=1)
        distances[atom_index] = np.inf
        within = distances[distances < cutoff_A]
        if len(within) > 0:
            distances_all.extend(within.tolist())
    return float(np.mean(distances_all)) if distances_all else float("nan")


def volume_change_pct(frames):
    """Percentage change in unit-cell volume from the first to last frame.
    A large change (> ±5 %) indicates mechanical instability of the doped
    structure at the simulation temperature."""
    v0 = frames[0].get_volume()
    vT = frames[-1].get_volume()
    return float((vT - v0) / v0 * 100)


def average_space_group(frames, symprec=0.05, sample=20):
    """Estimate the space group of the time-averaged structure.

    NOTE: thermal motion breaks crystallographic symmetry — any MD run at
    finite temperature will appear as P1 if individual frames are analysed.
    Here we average atom positions over `sample` evenly spaced frames and
    then run SpacegroupAnalyzer on that averaged geometry. This is still
    approximate; the result is reported as informational only (not used in
    the PASS/FAIL verdict) because residual thermal noise often prevents
    recovery of the true space group even after averaging.
    """
    indices = np.linspace(0, len(frames) - 1, min(sample, len(frames)), dtype=int)
    sampled = [frames[i] for i in indices]
    positions = np.mean([atoms.get_positions() for atoms in sampled], axis=0)
    avg_atoms = sampled[-1].copy()
    avg_atoms.set_positions(positions)
    structure = AseAtomsAdaptor.get_structure(avg_atoms)
    try:
        sg = SpacegroupAnalyzer(structure, symprec=symprec).get_space_group_symbol()
        sg_num = SpacegroupAnalyzer(structure, symprec=symprec).get_space_group_number()
        return f"{sg} ({sg_num})"
    except Exception as exc:
        return f"undetermined ({exc.__class__.__name__})"


def save_rdf(frames, atom_index, output_path, r_max=6.0, n_bins=120):
    bins = np.linspace(0.0, r_max, n_bins + 1)
    counts = np.zeros(n_bins)
    n_atoms = len(frames[0])
    for atoms in frames:
        positions = atoms.get_positions()
        cell = atoms.get_cell()
        target = positions[atom_index]
        deltas = positions - target
        frac = np.linalg.solve(np.asarray(cell).T, deltas.T).T
        frac -= np.round(frac)
        deltas = (np.asarray(cell).T @ frac.T).T
        distances = np.linalg.norm(deltas, axis=1)
        distances[atom_index] = -1
        counts += np.histogram(distances, bins=bins)[0]
    centers = 0.5 * (bins[1:] + bins[:-1])
    n_frames = len(frames)
    shell_volume = 4 * np.pi * centers ** 2 * (bins[1] - bins[0])
    avg_volume = np.mean([atoms.get_volume() for atoms in frames])
    density = (n_atoms - 1) / avg_volume
    g = counts / (n_frames * shell_volume * density)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(output_path, np.column_stack([centers, g]), header="r_A,g(r)", comments="")
    return centers, g


def analyze(md_result, dopant_symbol, cutoff_A=2.5, output_dir="analysis", force=False):
    traj_path = md_result["trajectory_path"]
    eq = md_result.get("equilibration_frames", 0)
    timestep_fs = md_result["timestep_fs"]
    loginterval = md_result["loginterval"]

    label = Path(traj_path).parent.name
    out_dir = Path(output_dir) / label
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "analysis.json"

    if not force and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            print(f"  [cached] Trajectory analysis -> {cache_path}")
            return cached
        except Exception as exc:
            print(f"  warning: analysis cache unreadable ({exc}); recomputing")

    frames = load_production_frames(traj_path, equilibration_frames=eq)
    if not frames:
        raise RuntimeError(f"No production frames in {traj_path} after eq={eq}")
    dopant_index = find_dopant_index(frames[0], dopant_symbol)

    n_frames = len(frames)
    frame_dt_ps = timestep_fs * loginterval / 1000.0
    time_ps = np.arange(n_frames) * frame_dt_ps

    disps = unwrapped_displacements(frames, dopant_index)
    msd = compute_msd(disps)
    slope = late_time_slope(time_ps, msd)
    max_disp = float(np.max(np.linalg.norm(disps, axis=1)))

    coord = coordination_history(frames, dopant_index, cutoff_A=cutoff_A)
    nn = mean_nn_distance(frames, dopant_index, cutoff_A=cutoff_A)
    dv = volume_change_pct(frames)
    sg = average_space_group(frames)

    save_rdf(frames, dopant_index, out_dir / "rdf.csv")
    np.savetxt(out_dir / "msd.csv", np.column_stack([time_ps, msd]),
               header="time_ps,msd_A2", comments="")
    np.savetxt(out_dir / "coordination.csv",
               np.column_stack([time_ps, coord]),
               header="time_ps,coord", comments="", fmt=["%.4f", "%d"])

    result = {
        "msd_slope_A2_per_ps": float(slope),
        "msd_final_A2": float(msd[-1]),
        "max_displacement_A": float(max_disp),
        "coordination_min": int(min(coord)),
        "coordination_max": int(max(coord)),
        "coordination_mean": float(np.mean(coord)),
        "mean_nn_distance_A": float(nn),
        "volume_change_pct": float(dv),
        "space_group": sg,
        "n_frames": int(n_frames),
        "output_dir": str(out_dir),
    }
    cache_path.write_text(json.dumps(result, indent=2))
    return result
