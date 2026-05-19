"""
Phase 2 + 3 - Enumerate symmetrically distinct substitution sites,
relax each, compute formation energies.

E_f = E(doped) - E(pristine) + mu(removed) - mu(dopant)

`relax_pristine` and `relax_doped` each run CHGNet relaxation.
`enumerate_sites` returns symmetrically distinct sites of `target_element`.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path

from pymatgen.core import Structure
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from chgnet.model import StructOptimizer


@dataclass
class CandidateSite:
    site_index: int
    element: str
    fractional_coords: tuple
    multiplicity: int


@dataclass
class RelaxedConfiguration:
    site_index: int
    dopant: str
    target_element: str
    final_structure: Structure
    final_energy_eV: float
    relaxed_space_group: str
    nn_distances_A: list
    coordination_number: int


def build_supercell(primitive_cif, size):
    primitive = Structure.from_file(primitive_cif)
    supercell = primitive.copy()
    supercell.make_supercell([size, size, size])
    return primitive, supercell


def enumerate_sites(structure, target_element, symprec=1e-3):
    """Return symmetrically distinct sites of `target_element` in `structure`."""
    analyzer = SpacegroupAnalyzer(structure, symprec=symprec)
    dataset = analyzer.get_symmetry_dataset()
    equiv = dataset.equivalent_atoms if hasattr(dataset, "equivalent_atoms") else dataset["equivalent_atoms"]

    seen = {}
    for i, site in enumerate(structure):
        if site.specie.symbol != target_element:
            continue
        rep = int(equiv[i])
        if rep not in seen:
            seen[rep] = {"first_index": i, "count": 1}
        else:
            seen[rep]["count"] += 1

    candidates = []
    for rep, info in seen.items():
        site = structure[info["first_index"]]
        candidates.append(
            CandidateSite(
                site_index=info["first_index"],
                element=target_element,
                fractional_coords=tuple(site.frac_coords),
                multiplicity=info["count"],
            )
        )
    return candidates


def substitute(structure, site_index, dopant):
    doped = structure.copy()
    doped.replace(site_index, dopant)
    return doped


def relax(structure, chgnet, steps=500, fmax=0.01, quiet=True):
    """Relax `structure` with CHGNet. quiet=True silences CHGNet's per-call
    "CHGNet will run on cpu" prints so the progress bar isn't drowned."""
    buf = io.StringIO()
    if quiet:
        with redirect_stdout(buf), redirect_stderr(buf):
            optimizer = StructOptimizer(model=chgnet)
            result = optimizer.relax(structure, steps=steps, fmax=fmax, verbose=False)
    else:
        optimizer = StructOptimizer(model=chgnet)
        result = optimizer.relax(structure, steps=steps, fmax=fmax, verbose=False)
    final = result["final_structure"]
    energy = result["trajectory"].energies[-1]
    return final, float(energy)


def neighbor_info(structure, site_index, cutoff_A=2.5):
    site = structure[site_index]
    neighbors = structure.get_neighbors(site, cutoff_A)
    distances = sorted(float(n.nn_distance) for n in neighbors)
    return distances, len(distances)


def _pristine_paths(output_dir, formula, supercell_size):
    base = Path(output_dir) / f"{formula}_pristine_{supercell_size}"
    return base.with_suffix(".cif"), base.with_suffix(".json")


def _doped_paths(output_dir, formula, dopant, target_element, label):
    base = Path(output_dir) / f"{formula}_{dopant}@{target_element}_{label}"
    return base.with_suffix(".cif"), base.with_suffix(".json")


def relax_pristine(primitive_cif, supercell_size, chgnet, output_dir="relaxed_structures", force=False):
    primitive, supercell = build_supercell(primitive_cif, supercell_size)
    formula = primitive.composition.reduced_formula
    cif_path, meta_path = _pristine_paths(output_dir, formula, supercell_size)

    if not force and cif_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            final = Structure.from_file(str(cif_path))
            print(
                f"  [cached] E(pristine) = {meta['energy_eV']:.4f} eV   "
                f"SG = {meta['space_group']}   -> {cif_path}"
            )
            return primitive, supercell, final, float(meta["energy_eV"]), meta["space_group"]
        except Exception as exc:
            print(f"  warning: pristine cache unreadable ({exc}); recomputing")

    print(f"Pristine supercell: {supercell.composition.reduced_formula}  ({len(supercell)} atoms)")
    final, energy = relax(supercell, chgnet)
    sg = "{} ({})".format(*final.get_space_group_info())
    cif_path.parent.mkdir(parents=True, exist_ok=True)
    final.to(filename=str(cif_path))
    meta_path.write_text(json.dumps({"energy_eV": float(energy), "space_group": sg}, indent=2))
    print(f"  E(pristine) = {energy:.4f} eV   SG = {sg}   -> {cif_path}")
    return primitive, supercell, final, energy, sg


def relax_doped(supercell, site_index, dopant, target_element, chgnet, output_dir="relaxed_structures", label=None, force=False):
    label = label or f"site{site_index}"
    formula = supercell.composition.reduced_formula
    cif_path, meta_path = _doped_paths(output_dir, formula, dopant, target_element, label)

    if not force and cif_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            final = Structure.from_file(str(cif_path))
            print(
                f"  [cached][{label}] E = {meta['energy_eV']:.4f} eV   "
                f"SG = {meta['space_group']}   coord = {meta['coordination']}"
            )
            return RelaxedConfiguration(
                site_index=int(meta["site_index"]),
                dopant=dopant,
                target_element=target_element,
                final_structure=final,
                final_energy_eV=float(meta["energy_eV"]),
                relaxed_space_group=meta["space_group"],
                nn_distances_A=[float(d) for d in meta["nn_distances_A"]],
                coordination_number=int(meta["coordination"]),
            )
        except Exception as exc:
            print(f"  warning: doped cache unreadable for {label} ({exc}); recomputing")

    doped = substitute(supercell, site_index, dopant)
    final, energy = relax(doped, chgnet)
    sg = "{} ({})".format(*final.get_space_group_info())
    distances, coord = neighbor_info(final, site_index)
    cif_path.parent.mkdir(parents=True, exist_ok=True)
    final.to(filename=str(cif_path))
    meta_path.write_text(json.dumps({
        "site_index": int(site_index),
        "energy_eV": float(energy),
        "space_group": sg,
        "coordination": int(coord),
        "nn_distances_A": [float(d) for d in distances],
    }, indent=2))
    print(
        f"  [{label}] E = {energy:.4f} eV   SG = {sg}   "
        f"coord({dopant}) = {coord}   mean d = {sum(distances)/len(distances):.3f} A   -> {cif_path}"
    )
    return RelaxedConfiguration(
        site_index=site_index,
        dopant=dopant,
        target_element=target_element,
        final_structure=final,
        final_energy_eV=energy,
        relaxed_space_group=sg,
        nn_distances_A=distances,
        coordination_number=coord,
    )


def formation_energy(doped_energy, pristine_energy, mu_removed_list, mu_dopant):
    """
    E_f = E(doped) - E(pristine) + sum(mu of every removed atom) - mu(dopant)

    mu_removed_list accepts either a single float (backward compat) or a
    list of floats covering the substituted site atom plus any
    charge-compensation atoms removed from the supercell.
    """
    if isinstance(mu_removed_list, (int, float)):
        mu_removed_list = [mu_removed_list]
    return doped_energy - pristine_energy + sum(mu_removed_list) - mu_dopant


def relax_doped_compensated(
    supercell,
    site_index,
    dopant,
    target_element,
    chgnet,
    mismatch,
    compensation_ref="Na",
    output_dir="relaxed_structures",
    label=None,
    force=False,
):
    """
    Build a charge-compensated doped supercell, relax it, and cache the result.
    Returns (RelaxedConfiguration, compensation_applied, comp_warnings).
    """
    from charge_utils import build_compensated_supercell

    label = label or f"site{site_index}"
    formula = supercell.composition.reduced_formula
    tag = "comp" if mismatch != 0 else "iso"
    cif_path, meta_path = _doped_paths(output_dir, formula, dopant, target_element, f"{label}_{tag}")

    if not force and cif_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            final = Structure.from_file(str(cif_path))
            comp_applied = meta.get("compensation_applied", False)
            print(
                f"  [cached][{label}] E = {meta['energy_eV']:.4f} eV  "
                f"comp={comp_applied}  coord = {meta['coordination']}"
            )
            return (
                RelaxedConfiguration(
                    site_index=int(meta["site_index"]),
                    dopant=dopant,
                    target_element=target_element,
                    final_structure=final,
                    final_energy_eV=float(meta["energy_eV"]),
                    relaxed_space_group=meta["space_group"],
                    nn_distances_A=[float(d) for d in meta["nn_distances_A"]],
                    coordination_number=int(meta["coordination"]),
                ),
                comp_applied,
                meta.get("comp_warnings", []),
            )
        except Exception as exc:
            print(f"  warning: compensated cache unreadable for {label} ({exc}); recomputing")

    doped, comp_applied, comp_warnings = build_compensated_supercell(
        supercell, site_index, dopant, mismatch, compensation_ref
    )

    final, energy = relax(doped, chgnet)
    sg = "{} ({})".format(*final.get_space_group_info())
    distances, coord = neighbor_info(final, site_index)
    cif_path.parent.mkdir(parents=True, exist_ok=True)
    final.to(filename=str(cif_path))
    meta_path.write_text(json.dumps({
        "site_index": int(site_index),
        "energy_eV": float(energy),
        "space_group": sg,
        "coordination": int(coord),
        "nn_distances_A": [float(d) for d in distances],
        "compensation_applied": comp_applied,
        "comp_warnings": comp_warnings,
    }, indent=2))
    mean_d = sum(distances) / len(distances) if distances else 0
    print(
        f"  [{label}] E = {energy:.4f} eV  SG = {sg}  "
        f"coord({dopant}) = {coord}  mean d = {mean_d:.3f} A  comp={comp_applied}  -> {cif_path}"
    )
    return (
        RelaxedConfiguration(
            site_index=site_index,
            dopant=dopant,
            target_element=target_element,
            final_structure=final,
            final_energy_eV=energy,
            relaxed_space_group=sg,
            nn_distances_A=distances,
            coordination_number=coord,
        ),
        comp_applied,
        comp_warnings,
    )
