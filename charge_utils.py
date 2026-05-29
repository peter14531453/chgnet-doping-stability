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

from dopant_database import DOPANTS

# Oxidation states for host-lattice and anion species that are NOT dopants.
# Dopant oxidation states live in the dopant database (single source of truth);
# this table covers the alkali sites, the Co host site, and common anions so
# charge_mismatch can be computed for any (dopant, host-site) pair.
_BASE_OXIDATION_STATES: dict[str, int] = {
    # Alkali sites
    "Li": 1, "Na": 1, "K": 1, "Rb": 1, "Cs": 1,
    # Host transition metal
    "Co": 3,
    # Anions
    "O": -2, "F": -1, "Cl": -1, "S": -2,
}


def get_oxidation_state(element: str, override: int | None = None) -> int:
    if override is not None:
        return override
    if element in DOPANTS:
        return DOPANTS[element].oxidation_state
    if element in _BASE_OXIDATION_STATES:
        return _BASE_OXIDATION_STATES[element]
    raise KeyError(
        f"No default oxidation state for '{element}'. "
        "Add it to the dopant database or set "
        "dopant_oxidation_state=/target_oxidation_state= in WorkflowConfig."
    )


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
    """Build a charge-compensated doped supercell.

    Returns (doped_structure, compensation_applied: bool, warnings: list[str]).

    Strategy
    --------
    mismatch > 0  (dopant brings MORE positive charge, e.g. Mn4+ → Co3+, Ca2+ → Na+)
        Remove |mismatch| Na/K atoms from the supercell to restore charge
        neutrality. This physically corresponds to Na loss during synthesis
        or electrochemical de-sodiation. The E_f formula adds +mu(Na) for
        each removed atom (handled in enumerate_and_relax).

    mismatch == 0  (isovalent, e.g. Al3+ → Co3+, Mn3+ → Co3+)
        Plain substitution, no structural modification. E_f is reliable.

    mismatch < 0  (dopant brings LESS positive charge, e.g. Mg2+/Zn2+ → Co3+)
        Compensation requires adding Na interstitials or oxidising Co3+→Co4+,
        neither of which is possible in a charge-neutral MLIP. Run plain
        substitution and flag E_f as approximate.
    """
    doped = structure.copy()
    doped.replace(site_index, dopant)
    warnings: list[str] = []

    if mismatch <= 0:
        if mismatch < 0:
            warnings.append(
                f"Charge deficit ({mismatch:+d}) cannot be compensated in CHGNet "
                f"(would require adding {compensation_ref} interstitials or oxidising Co). "
                "Running single substitution without compensation. E_f is approximate."
            )
        return doped, False, warnings

    n_remove = mismatch
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

    # Rank Na sites by distance from dopant (descending) and remove the
    # furthest ones — this maximises dopant-vacancy separation and reduces
    # artificial defect-defect interaction in the finite supercell.
    dopant_frac = doped[site_index].frac_coords
    lattice = doped.lattice
    distances = []
    for i in ref_indices:
        d = doped[i].frac_coords - dopant_frac
        d -= np.round(d)   # minimum image
        distances.append((i, np.linalg.norm(lattice.get_cartesian_coords(d))))

    distances.sort(key=lambda x: x[1], reverse=True)
    # Remove highest-index sites first so lower indices stay valid
    to_remove = sorted([idx for idx, _ in distances[:n_remove]], reverse=True)
    doped.remove_sites(to_remove)

    return doped, True, warnings
