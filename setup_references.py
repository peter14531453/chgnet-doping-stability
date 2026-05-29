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


def _k_bcc():
    a = 5.225
    return Structure(
        Lattice.cubic(a),
        ["K", "K"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


def _li_bcc():
    a = 3.510
    return Structure(
        Lattice.cubic(a),
        ["Li", "Li"],
        [[0, 0, 0], [0.5, 0.5, 0.5]],
    )


def _ga_fcc():
    # alpha-Ga is orthorhombic (Cmce, 8-atom cell) and is not produced by
    # ase.build.bulk. A simple fcc cell serves as a computationally tractable
    # metallic reference; CHGNet relaxes it to a consistent per-atom energy
    # (same rationale as _mn_bcc).
    a = 4.510
    return Structure(
        Lattice.cubic(a),
        ["Ga", "Ga", "Ga", "Ga"],
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
    )


def _ni_fcc():
    a = 3.524
    return Structure(
        Lattice.cubic(a),
        ["Ni", "Ni", "Ni", "Ni"],
        [[0, 0, 0], [0.5, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0.5]],
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
    "K": _k_bcc,
    "Li": _li_bcc,
    "Ni": _ni_fcc,
    "Mn": _mn_bcc,
    "Ga": _ga_fcc,
}


def _ase_bulk_reference(element):
    """Build an elemental reference crystal via ASE's known reference states.

    ase.build.bulk(element) returns the experimental ground-state crystal for
    essentially every metal we screen, removing the need to hand-code a cell
    per dopant. CHGNet then relaxes it to a per-atom chemical potential.
    """
    from ase.build import bulk
    from pymatgen.io.ase import AseAtomsAdaptor

    try:
        atoms = bulk(element)
    except Exception as exc:  # noqa: BLE001 - surface a clear, actionable error
        raise KeyError(
            f"No elemental reference available for '{element}'. "
            "ase.build.bulk could not build it; add a builder to "
            "REFERENCE_BUILDERS in setup_references.py."
        ) from exc
    return AseAtomsAdaptor.get_structure(atoms)


def reference_structure(element):
    """Return the elemental reference Structure for `element`.

    Prefers a validated hand-coded builder (REFERENCE_BUILDERS); otherwise
    falls back to ASE's reference states. This keeps existing mu values stable
    while letting any database dopant be referenced automatically.
    """
    if element in REFERENCE_BUILDERS:
        return REFERENCE_BUILDERS[element]()
    return _ase_bulk_reference(element)


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


def compute_references(
    elements,
    chgnet=None,
    model_name="r2scan",
    save_path=REFERENCES_FILE,
    existing: dict | None = None,
):
    """Compute mu (eV/atom) for each element in `elements` and save to JSON."""
    chgnet = chgnet or CHGNet.load(model_name=model_name)
    optimizer = StructOptimizer(model=chgnet)
    mus = dict(existing or {})
    for element in elements:
        structure = reference_structure(element)
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
    cached = None if force else load_references(path)
    if cached is not None and all(e in cached for e in elements):
        print(
            f"Loaded chemical potentials from {path}: "
            + ", ".join(f"mu({e})={cached[e]:.4f}" for e in elements)
        )
        return {e: cached[e] for e in elements}

    missing = list(elements) if cached is None else [e for e in elements if e not in cached]
    return compute_references(
        missing, chgnet=chgnet, save_path=path, existing=cached,
    )


if __name__ == "__main__":
    compute_references(["Al", "Co"])
