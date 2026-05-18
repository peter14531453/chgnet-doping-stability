"""
Phase 2 + 3 - Enumerate symmetrically distinct substitution sites,
relax each, compute formation energies.

E_f = E(doped) - E(pristine) + mu(removed) - mu(dopant)

`relax_pristine` and `relax_doped` each run CHGNet relaxation.
`enumerate_sites` returns symmetrically distinct sites of `target_element`.
"""
from __future__ import annotations

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


def relax(structure, chgnet, steps=500, fmax=0.01):
    optimizer = StructOptimizer(model=chgnet)
    result = optimizer.relax(structure, steps=steps, fmax=fmax, verbose=False)
    final = result["final_structure"]
    energy = result["trajectory"].energies[-1]
    return final, float(energy)


def neighbor_info(structure, site_index, cutoff_A=3.2):
    site = structure[site_index]
    neighbors = structure.get_neighbors(site, cutoff_A)
    distances = sorted(n.nn_distance for n in neighbors)
    return distances, len(distances)


def relax_pristine(primitive_cif, supercell_size, chgnet, output_dir="relaxed_structures"):
    primitive, supercell = build_supercell(primitive_cif, supercell_size)
    print(f"Pristine supercell: {supercell.composition.reduced_formula}  ({len(supercell)} atoms)")
    final, energy = relax(supercell, chgnet)
    sg = "{} ({})".format(*final.get_space_group_info())
    out_path = Path(output_dir) / f"{primitive.composition.reduced_formula}_pristine_{supercell_size}.cif"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.to(filename=str(out_path))
    print(f"  E(pristine) = {energy:.4f} eV   SG = {sg}   -> {out_path}")
    return primitive, supercell, final, energy, sg


def relax_doped(supercell, site_index, dopant, target_element, chgnet, output_dir="relaxed_structures", label=None):
    doped = substitute(supercell, site_index, dopant)
    label = label or f"site{site_index}"
    final, energy = relax(doped, chgnet)
    sg = "{} ({})".format(*final.get_space_group_info())
    distances, coord = neighbor_info(final, site_index)
    out_path = Path(output_dir) / f"{supercell.composition.reduced_formula}_{dopant}@{target_element}_{label}.cif"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.to(filename=str(out_path))
    print(
        f"  [{label}] E = {energy:.4f} eV   SG = {sg}   "
        f"coord({dopant}) = {coord}   mean d = {sum(distances)/len(distances):.3f} A   -> {out_path}"
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


def formation_energy(doped_energy, pristine_energy, mu_removed, mu_dopant):
    return doped_energy - pristine_energy + mu_removed - mu_dopant
