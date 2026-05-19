"""
Phase 1 - Reference chemical potentials.

Computes per-atom CHGNet energies of the dopant and the substituted host
element in their elemental ground states. These mu values are reference
'metal-rich' chemical potentials, suitable as a first-pass approximation
for defect formation energies.

To switch to oxide references (Al-poor / Co-poor limits), build the relevant
oxide structures and pass them through `mu_from_structure` instead.
"""
from __future__ import annotations

import json
from pathlib import Path

from pymatgen.core import Lattice, Structure
from chgnet.model import StructOptimizer
from chgnet.model.model import CHGNet


REFERENCES_FILE = "references.json"


def _al_fcc():
    a = 4.046
    return Structure(
        Lattice.cubic(a),
        ["Al", "Al", "Al", "Al"],
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
    )


def _co_hcp():
    a, c = 2.507, 4.069
    return Structure(
        Lattice.hexagonal(a, c),
        ["Co", "Co"],
        [[1 / 3, 2 / 3, 0.25], [2 / 3, 1 / 3, 0.75]],
    )


def _ca_fcc():
    a = 5.588
    return Structure(
        Lattice.cubic(a),
        ["Ca", "Ca", "Ca", "Ca"],
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
    )


def _na_bcc():
    a = 4.225
    return Structure(
        Lattice.cubic(a),
        ["Na", "Na"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


def _mn_bcc():
    # BCC Mn used as a computationally tractable reference.
    # True ground state is alpha-Mn (58-atom complex cell); this simpler
    # cell gives a consistent reference within CHGNet's energy frame.
    a = 2.911
    return Structure(
        Lattice.cubic(a),
        ["Mn", "Mn"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


REFERENCE_BUILDERS = {
    "Al": _al_fcc,
    "Co": _co_hcp,
    "Ca": _ca_fcc,
    "Na": _na_bcc,
    "Mn": _mn_bcc,
}


def mu_from_structure(structure, target_element, chgnet, optimizer=None, fmax=0.01, steps=300):
    """Relax a structure and return per-atom energy of `target_element` in eV.

    Only valid for single-element structures (elemental reference).
    """
    elements = {site.specie.symbol for site in structure}
    if elements != {target_element}:
        raise ValueError(
            f"mu_from_structure expects single-element {target_element} cell, got {elements}"
        )
    optimizer = optimizer or StructOptimizer(model=chgnet)
    result = optimizer.relax(structure, steps=steps, fmax=fmax, verbose=False)
    energies = result["trajectory"].energies
    final_energy = energies[-1]
    return final_energy / len(result["final_structure"])


def compute_references(elements, chgnet=None, model_name="r2scan", save_path=REFERENCES_FILE):
    """Compute mu (eV/atom) for each element in `elements` and save to JSON."""
    chgnet = chgnet or CHGNet.load(model_name=model_name)
    optimizer = StructOptimizer(model=chgnet)
    mus = {}
    for element in elements:
        if element not in REFERENCE_BUILDERS:
            raise KeyError(
                f"No built-in elemental reference for '{element}'. "
                "Add a builder to REFERENCE_BUILDERS or pass a Structure to mu_from_structure."
            )
        structure = REFERENCE_BUILDERS[element]()
        mus[element] = float(mu_from_structure(structure, element, chgnet, optimizer=optimizer))
        print(f"  mu({element}) = {mus[element]:.4f} eV/atom")
    Path(save_path).write_text(json.dumps(mus, indent=2))
    print(f"Saved chemical potentials -> {save_path}")
    return mus


def load_references(path=REFERENCES_FILE):
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def get_or_compute_references(elements, chgnet=None, path=REFERENCES_FILE, force=False):
    if not force:
        cached = load_references(path)
        if cached is not None and all(e in cached for e in elements):
            print(f"Loaded chemical potentials from {path}: "
                  + ", ".join(f"mu({e})={cached[e]:.4f}" for e in elements))
            return cached
    return compute_references(elements, chgnet=chgnet, save_path=path)


if __name__ == "__main__":
    compute_references(["Al", "Co"])
