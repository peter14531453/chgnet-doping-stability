"""
Curated dopant database for the layered ACoO2 doping-stability workflow.

Single source of truth for the dopant elements the workflow can screen.
Both `charge_utils` (oxidation states for charge compensation) and
`setup_references` (which elements need an elemental chemical-potential
reference) read from here, so the three element tables that used to live in
separate modules no longer drift apart.

Scope
-----
~25 metals commonly studied as substituents in layered-oxide cathodes,
spanning Z = 12 (Mg) to Z = 74 (W). Nonmetals, noble gases, and exotic /
radioactive metals are intentionally excluded.

Fields per dopant
-----------------
- symbol / Z             : element identity
- category               : display grouping for the interactive menu
- oxidation_state        : the typical formal charge in a layered oxide;
                           drives charge compensation in charge_utils
- alt_oxidation_states   : other charges the element commonly adopts
- ionic_radius_A         : Shannon six-coordinate ionic radius (informational;
                           compare against Co3+ ~0.55-0.61 A for size mismatch)
- reference_builder      : how setup_references builds its elemental reference
                           crystal: "ase_bulk" (auto via ase.build.bulk) or
                           "special:<Sym>" for a hand-coded cell

Notes on the charge model
--------------------------
A dopant whose oxidation state is HIGHER than the site it replaces (e.g.
Ti4+ or Nb5+ on Co3+, or any metal on the +1 alkali site) produces a
*positive* charge mismatch. CHGNet is charge-neutral and cannot model the
compensating electron, so those runs are flagged "approximate" by the
workflow rather than excluded -- the energetics still rank usefully.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DopantInfo:
    symbol: str
    Z: int
    category: str
    oxidation_state: int
    alt_oxidation_states: tuple[int, ...] = field(default_factory=tuple)
    ionic_radius_A: float | None = None
    reference_builder: str = "ase_bulk"


# Display order + human labels for the interactive menu sections.
CATEGORY_ORDER: tuple[str, ...] = (
    "alkaline_earth",
    "post_transition",
    "3d_transition",
    "4d_transition",
    "5d_transition",
)

CATEGORY_LABELS: dict[str, str] = {
    "alkaline_earth": "Alkaline earth",
    "post_transition": "Post-transition / main group",
    "3d_transition": "3d transition metals",
    "4d_transition": "4d transition metals",
    "5d_transition": "5d / rare-earth",
}


def _d(*args, **kwargs) -> tuple[str, DopantInfo]:
    info = DopantInfo(*args, **kwargs)
    return info.symbol, info


# Reference cobalt site charge for context (host transition-metal site).
HOST_TM_OXIDATION_STATE: int = 3  # Co3+

DOPANTS: dict[str, DopantInfo] = dict(
    [
        # --- Alkaline earth (divalent) -------------------------------------
        _d("Mg", 12, "alkaline_earth", 2, ionic_radius_A=0.72),
        _d("Ca", 20, "alkaline_earth", 2, ionic_radius_A=1.00),
        _d("Sr", 38, "alkaline_earth", 2, ionic_radius_A=1.18),
        _d("Ba", 56, "alkaline_earth", 2, ionic_radius_A=1.35),
        # --- Post-transition / main group ----------------------------------
        _d("Al", 13, "post_transition", 3, ionic_radius_A=0.535),
        _d("Ga", 31, "post_transition", 3, ionic_radius_A=0.62,
           reference_builder="special:Ga"),
        _d("Sn", 50, "post_transition", 4, alt_oxidation_states=(2,),
           ionic_radius_A=0.69),
        _d("Sb", 51, "post_transition", 5, alt_oxidation_states=(3,),
           ionic_radius_A=0.60),
        # --- 3d transition metals ------------------------------------------
        _d("Sc", 21, "3d_transition", 3, ionic_radius_A=0.745),
        _d("Ti", 22, "3d_transition", 4, alt_oxidation_states=(3,),
           ionic_radius_A=0.605),
        _d("V", 23, "3d_transition", 3, alt_oxidation_states=(4, 5),
           ionic_radius_A=0.64),
        _d("Cr", 24, "3d_transition", 3, alt_oxidation_states=(6,),
           ionic_radius_A=0.615),
        _d("Mn", 25, "3d_transition", 3, alt_oxidation_states=(2, 4),
           ionic_radius_A=0.645, reference_builder="special:Mn"),
        _d("Fe", 26, "3d_transition", 3, alt_oxidation_states=(2,),
           ionic_radius_A=0.645),
        _d("Ni", 28, "3d_transition", 3, alt_oxidation_states=(2,),
           ionic_radius_A=0.60),
        _d("Cu", 29, "3d_transition", 2, ionic_radius_A=0.73),
        _d("Zn", 30, "3d_transition", 2, ionic_radius_A=0.74),
        # --- 4d transition metals ------------------------------------------
        _d("Y", 39, "4d_transition", 3, ionic_radius_A=0.90),
        _d("Zr", 40, "4d_transition", 4, ionic_radius_A=0.72),
        _d("Nb", 41, "4d_transition", 5, alt_oxidation_states=(4,),
           ionic_radius_A=0.64),
        _d("Mo", 42, "4d_transition", 4, alt_oxidation_states=(6,),
           ionic_radius_A=0.65),
        _d("Ru", 44, "4d_transition", 4, ionic_radius_A=0.62),
        # --- 5d / rare-earth -----------------------------------------------
        _d("La", 57, "5d_transition", 3, ionic_radius_A=1.032),
        _d("Ta", 73, "5d_transition", 5, ionic_radius_A=0.64),
        _d("W", 74, "5d_transition", 4, alt_oxidation_states=(6,),
           ionic_radius_A=0.66),
    ]
)


def get_dopant(symbol: str) -> DopantInfo:
    """Return the DopantInfo for `symbol`, raising a helpful error if absent."""
    if symbol not in DOPANTS:
        raise KeyError(
            f"'{symbol}' is not in the dopant database. "
            f"Known dopants: {', '.join(sorted(DOPANTS))}."
        )
    return DOPANTS[symbol]


def all_symbols() -> list[str]:
    """Dopant symbols in periodic (Z) order."""
    return sorted(DOPANTS, key=lambda s: DOPANTS[s].Z)


def by_category(category: str) -> list[DopantInfo]:
    """Dopants in one category, ordered by Z (menu display order)."""
    return sorted(
        (d for d in DOPANTS.values() if d.category == category),
        key=lambda d: d.Z,
    )
