"""
Charge compensation utilities for aliovalent doping.

Determines the charge mismatch when dopant X replaces host atom Y, then
builds a charge-compensated supercell by removing alkali ions (Na by
default) to restore charge neutrality when the mismatch is negative
(dopant brings less positive charge than the host atom it replaced).

Positive mismatch (dopant brings MORE charge) cannot be compensated
within CHGNet's charge-neutral framework -- these cases run as plain
single substitutions with a warning in the report.

Limitations
-----------
- CHGNet predicts atomic forces from a charge-neutral potential. It does
  not model polaron formation, electron/hole localisation, or image-charge
  effects. The E_f values for charged defects are approximate.
- Freysoldt/Kumagai electrostatic finite-size corrections require the
  host dielectric tensor and the DFT electrostatic potential -- neither
  is available from a neural-network interatomic potential. These
  corrections are therefore NOT applied here.
- The compensation mechanism (Na vacancy) is the most physically
  motivated one for layered-oxide cathodes under Na-rich conditions.
  Under other synthesis environments different compensation mechanisms
  may dominate.
"""
from __future__ import annotations

import numpy as np

OXIDATION_STATES: dict[str, int] = {
    # Alkali metals
    "Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1,
    # Alkaline earth
    "Mg": 2, "Ca": 2, "Sr": 2, "Ba": 2,
    # Group 13
    "Al": 3, "Ga": 3, "In": 3,
    # 3d transition metals (typical oxidation state in layered oxides)
    "Ti": 4, "V": 3, "Cr": 3, "Mn": 3, "Fe": 3,
    "Co": 3, "Ni": 3, "Cu": 2, "Zn": 2,
    # 4d / 5d (common in cathodes)
    "Nb": 5, "Mo": 4, "W": 4, "Ru": 4,
    # Anions
    "O": -2, "F": -1, "Cl": -1, "S": -2,
}


def get_oxidation_state(element: str, override: int | None = None) -> int:
    if override is not None:
        return override
    if element not in OXIDATION_STATES:
        raise KeyError(
            f"No default oxidation state for '{element}'. "
            "Set dopant_oxidation_state= or target_oxidation_state= in WorkflowConfig."
        )
    return OXIDATION_STATES[element]


def charge_mismatch(
    dopant: str,
    target_element: str,
    dopant_ox: int | None = None,
    target_ox: int | None = None,
) -> int:
    """
    mismatch = oxidation_state(dopant) - oxidation_state(target)

    Negative  -> dopant brings less positive charge; remove Na to compensate.
    Zero      -> isovalent; no compensation needed.
    Positive  -> dopant brings more positive charge; cannot compensate in CHGNet.
    """
    d = get_oxidation_state(dopant, dopant_ox)
    t = get_oxidation_state(target_element, target_ox)
    return d - t


def describe_compensation(mismatch: int, compensation_ref: str = "Na") -> str:
    if mismatch == 0:
        return "isovalent — no charge compensation needed"
    if mismatch < 0:
        n = abs(mismatch)
        return (
            f"aliovalent (mismatch {mismatch:+d}): "
            f"compensated by removing {n} {compensation_ref} per dopant"
        )
    return (
        f"aliovalent (mismatch {mismatch:+d}): "
        f"charge surplus cannot be modelled in CHGNet — "
        f"running uncompensated single substitution (E_f approximate)"
    )


def build_compensated_supercell(
    structure,
    site_index: int,
    dopant: str,
    mismatch: int,
    compensation_ref: str = "Na",
):
    """
    Return (doped_structure, compensation_applied: bool, warnings: list[str]).

    For mismatch < 0: substitute dopant at site_index, then remove
    abs(mismatch) compensation_ref atoms that are furthest from the
    dopant site (minimises defect-defect interaction).

    For mismatch >= 0: substitute only (no structural compensation).
    """
    doped = structure.copy()
    doped.replace(site_index, dopant)
    warnings: list[str] = []

    if mismatch >= 0:
        if mismatch > 0:
            warnings.append(
                f"Charge surplus (+{mismatch}) cannot be modelled in CHGNet. "
                "Running single substitution without compensation. E_f is approximate."
            )
        return doped, False, warnings

    n_remove = abs(mismatch)
    ref_indices = [
        i for i, s in enumerate(doped) if s.specie.symbol == compensation_ref
    ]

    if len(ref_indices) < n_remove:
        warnings.append(
            f"Not enough {compensation_ref} sites to remove "
            f"({len(ref_indices)} available, need {n_remove}). "
            "Running without compensation."
        )
        return doped, False, warnings

    dopant_frac = doped[site_index].frac_coords
    lattice = doped.lattice
    distances = []
    for i in ref_indices:
        d = doped[i].frac_coords - dopant_frac
        d -= np.round(d)
        distances.append((i, np.linalg.norm(lattice.get_cartesian_coords(d))))

    distances.sort(key=lambda x: x[1], reverse=True)
    to_remove = sorted([idx for idx, _ in distances[:n_remove]], reverse=True)
    doped.remove_sites(to_remove)

    return doped, True, warnings
