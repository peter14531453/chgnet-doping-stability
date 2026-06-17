"""
Compare CHGNet bulk solution energies to Table I of Boev et al. (2024).

Phys. Rev. Materials 8, 055403 (2024) — "Origin of surface segregation in LiCoO2:
A DFT+U study"

Replicates bulk solution energies Es [Eq. (1)], M-O bond distances, Shannon ionic
radii ratios deltaR, and reference-phase space groups using:
  - 128-atom LiCoO2 supercell (32 formula units), matching the paper
  - LiMO2 ground-state references from Materials Project via pymatgen MPRester (MP_API_KEY required)
  - LiMO2 (R-3m) template references from Co -> M substitution in LiCoO2
  - Mg reference: E(MgO) + 0.5 * E(Li2O2) per the paper footnote

Table II (surface segregation at the (104) slab) is out of scope.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from chgnet.model.model import CHGNet
from pymatgen.core import Structure
from pymatgen.ext.matproj import MPRester
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

from enumerate_and_relax import relax, substitute


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LCO_CIF = Path("primitive_cells/LiCoO2.cif")
CACHE_DIR = Path("relaxed_structures/paper_compare")
N_FORMULA_UNITS = 32  # 128-atom supercell

DOPANTS = ["Mg", "Al", "Ti", "V", "Cr", "Mn", "Fe", "Ni"]

# Shannon ionic radii (A), 6-coord unless noted. Co3+ LS = paper denominator.
R_CO3_LS = 0.545
SHANNON_RADII = {
    "Mg": 0.720,   # Mg2+ 6-coord
    "Al": 0.535,   # Al3+ 6-coord
    "Ti": 0.605,   # Ti4+ 6-coord
    "V": 0.580,    # V4+ 6-coord
    "Cr": 0.615,   # Cr3+ HS 6-coord
    "Mn": 0.645,   # Mn3+ HS 6-coord
    "Fe": 0.645,   # Fe3+ HS 6-coord
    "Ni": 0.560,   # Ni3+ LS 6-coord
}

# Paper Table I reference values for side-by-side comparison.
PAPER_TABLE_I = {
    "Mg": {
        "mo_dist": "2.02x2, 2.03x2, 2.06x2",
        "sg": "MgO+0.5Li2O2",
        "mu_m": 0.0,
        "mu_ap": 1.02,
        "es_sg": 0.08,
        "es_r3m": -0.78,
        "delta_r": 1.32,
    },
    "Al": {
        "mo_dist": "1.93x6",
        "sg": "P41212",
        "mu_m": 0.0,
        "mu_ap": 0.01,
        "es_sg": -0.07,
        "es_r3m": None,
        "delta_r": 0.98,
    },
    "Ti": {
        "mo_dist": "1.94x2, 1.99x2, 2.03x2",
        "sg": "I41/amd",
        "mu_m": 0.01,
        "mu_ap": 2.68,
        "es_sg": -0.47,
        "es_r3m": -0.56,
        "delta_r": 1.11,
    },
    "V": {
        "mo_dist": "1.91x2, 1.99x2, 2.00x2",
        "sg": "R-3m",
        "mu_m": 1.03,
        "mu_ap": 2.68,
        "es_sg": 0.39,
        "es_r3m": 0.39,
        "delta_r": 1.06,
    },
    "Cr": {
        "mo_dist": "2.00x6",
        "sg": "R-3m",
        "mu_m": 2.96,
        "mu_ap": None,
        "es_sg": 0.10,
        "es_r3m": 0.10,
        "delta_r": 1.13,
    },
    "Mn": {
        "mo_dist": "1.93x2, 2.06x4",
        "sg": "C2/m",
        "mu_m": 3.82,
        "mu_ap": None,
        "es_sg": 0.38,
        "es_r3m": 0.22,
        "delta_r": 1.18,
    },
    "Fe": {
        "mo_dist": "2.01x6",
        "sg": "Pmmn",
        "mu_m": 4.24,
        "mu_ap": None,
        "es_sg": 0.14,
        "es_r3m": 0.06,
        "delta_r": 1.18,
    },
    "Ni": {
        "mo_dist": "1.94x4, 2.04x2",
        "sg": "P2/c",
        "mu_m": 1.29,
        "mu_ap": None,
        "es_sg": 0.06,
        "es_r3m": -0.01,
        "delta_r": 1.03,
    },
}

# Dopants whose ground-state LiMO2 phase is R-3m (Es(SG) == Es(R-3m) in paper).
R3M_GROUND_STATE = {"V", "Cr"}


@dataclass
class ReferencePhase:
    label: str
    structure: Structure
    energy_eV: float
    energy_per_fu_eV: float
    space_group: str
    mp_id: str | None = None


@dataclass
class DopantResult:
    dopant: str
    site_index: int
    mo_dist_str: str
    mo_distances: list[tuple[float, int]]
    space_group: str
    mu_m: float | None
    mu_ap: float | None
    es_sg: float
    es_r3m: float
    delta_r: float
    e_doped_eV: float
    ref_sg: ReferencePhase
    ref_r3m: ReferencePhase
    mp_id_sg: str | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Structure building
# ---------------------------------------------------------------------------

def build_128atom_supercell(cif_path: Path = LCO_CIF) -> tuple[Structure, Structure]:
    """Return (4-atom primitive, 128-atom supercell) for LiCoO2."""
    hex_cell = Structure.from_file(str(cif_path))
    sga = SpacegroupAnalyzer(hex_cell, symprec=0.1)
    primitive = sga.get_primitive_standard_structure()
    supercell = primitive.copy()
    supercell.make_supercell([4, 4, 2])
    if len(supercell) != 128:
        raise ValueError(
            f"Expected 128-atom supercell, got {len(supercell)} atoms "
            f"(primitive has {len(primitive)} atoms)."
        )
    return primitive, supercell


def build_limo2_r3m(dopant: str, primitive_lco: Structure) -> Structure:
    """Build LiMO2 in R-3m by substituting Co in the LiCoO2 primitive cell."""
    structure = primitive_lco.copy()
    co_indices = [i for i, site in enumerate(structure) if site.specie.symbol == "Co"]
    if not co_indices:
        raise ValueError("No Co site found in LiCoO2 primitive cell.")
    structure.replace(co_indices[0], dopant)
    return structure


def first_co_site_index(structure: Structure) -> int:
    for i, site in enumerate(structure):
        if site.specie.symbol == "Co":
            return i
    raise ValueError("No Co site found in structure.")


# ---------------------------------------------------------------------------
# Energy helpers
# ---------------------------------------------------------------------------

def li_formula_units(structure: Structure) -> float:
    """Number of LiCoO2 / LiMO2 formula units (= Li count)."""
    return structure.composition.get("Li", 0)


def mgo_formula_units(structure: Structure) -> float:
    return structure.composition.get("Mg", 0)


def li2o2_formula_units(structure: Structure) -> float:
    return structure.composition.get("Li", 0) / 2.0


def energy_per_fu(structure: Structure, energy_eV: float, fu_type: str = "limo2") -> float:
    if fu_type == "limo2":
        n_fu = li_formula_units(structure)
    elif fu_type == "mgo":
        n_fu = mgo_formula_units(structure)
    elif fu_type == "li2o2":
        n_fu = li2o2_formula_units(structure)
    else:
        raise ValueError(f"Unknown fu_type: {fu_type}")
    if n_fu <= 0:
        raise ValueError(f"Cannot compute formula units for {fu_type} in {structure.composition}")
    return energy_eV / n_fu


def compute_solution_energy(
    e_doped: float,
    e_pristine_fu: float,
    e_limo2_fu: float,
    n: int = N_FORMULA_UNITS,
) -> float:
    """Eq. (1): Es = Etot - (n-1)*E_LiCoO2 - E_LiMO2 (all per f.u.)."""
    return e_doped - (n - 1) * e_pristine_fu - e_limo2_fu


def delta_r(dopant: str) -> float:
    return SHANNON_RADII[dopant] / R_CO3_LS


# ---------------------------------------------------------------------------
# Materials Project (pymatgen.ext.matproj.MPRester + MP_API_KEY)
# ---------------------------------------------------------------------------


def require_mp_api_key() -> str:
    key = os.environ.get("MP_API_KEY")
    if not key:
        raise EnvironmentError(
            "MP_API_KEY environment variable is required for LiMO2 reference phases."
        )
    return key


def _as_structure(obj: Structure | dict) -> Structure:
    if isinstance(obj, Structure):
        return obj
    return Structure.from_dict(obj)


def fetch_structure_by_material_id(material_id: str, api_key: str) -> Structure:
    with MPRester(api_key) as mpr:
        return mpr.get_structure_by_material_id(material_id)


def fetch_limo2_groundstate(dopant: str, api_key: str) -> tuple[Structure, str, str]:
    """Fetch lowest-energy LiMO2 polymorph from Materials Project."""
    formula = f"Li{dopant}O2"
    with MPRester(api_key) as mpr:
        docs = mpr.summary_search(
            formula=formula,
            nelements=3,
            _fields="material_id,structure,energy_per_atom,symmetry",
            _limit=100,
        )
    if not docs:
        raise ValueError(f"No Materials Project entry found for {formula}.")
    best = min(docs, key=lambda d: d["energy_per_atom"])
    sg = (best.get("symmetry") or {}).get("symbol", "unknown")
    return _as_structure(best["structure"]), sg, best["material_id"]


def fetch_mgo_li2o2_references(api_key: str) -> tuple[tuple[Structure, str], tuple[Structure, str]]:
    """Fetch MgO and Li2O2 reference structures from MP (paper footnote a)."""
    mgo = fetch_structure_by_material_id("mp-1265", api_key)
    li2o2 = fetch_structure_by_material_id("mp-841", api_key)
    return (mgo, "mp-1265"), (li2o2, "mp-841")


# ---------------------------------------------------------------------------
# Relaxation + caching
# ---------------------------------------------------------------------------

def _cache_paths(label: str) -> tuple[Path, Path]:
    base = CACHE_DIR / label
    return base.with_suffix(".cif"), base.with_suffix(".json")


def relax_structure(
    structure: Structure,
    label: str,
    chgnet: CHGNet,
    force: bool = False,
    steps: int = 500,
    fmax: float = 0.01,
) -> tuple[Structure, float]:
    cif_path, meta_path = _cache_paths(label)

    if not force and cif_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        cached = Structure.from_file(str(cif_path))
        print(f"  [cached] {label}: E = {meta['energy_eV']:.4f} eV")
        return cached, float(meta["energy_eV"])

    print(f"  Relaxing {label} ({len(structure)} atoms)...")
    final, energy = relax(structure, chgnet, steps=steps, fmax=fmax)
    sg = "{} ({})".format(*final.get_space_group_info())
    cif_path.parent.mkdir(parents=True, exist_ok=True)
    final.to(filename=str(cif_path))
    meta_path.write_text(
        json.dumps(
            {
                "label": label,
                "energy_eV": float(energy),
                "space_group": sg,
                "n_atoms": len(final),
            },
            indent=2,
        )
    )
    print(f"  {label}: E = {energy:.4f} eV   SG = {sg}")
    return final, float(energy)


def relax_reference_phase(
    structure: Structure,
    label: str,
    fu_type: str,
    chgnet: CHGNet,
    force: bool = False,
    mp_id: str | None = None,
) -> ReferencePhase:
    final, energy = relax_structure(structure, label, chgnet, force=force)
    sg = "{} ({})".format(*final.get_space_group_info())
    e_fu = energy_per_fu(final, energy, fu_type=fu_type)
    return ReferencePhase(
        label=label,
        structure=final,
        energy_eV=energy,
        energy_per_fu_eV=e_fu,
        space_group=sg,
        mp_id=mp_id,
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def get_mo_distances(
    structure: Structure,
    site_index: int,
    cutoff: float = 2.5,
    tol: float = 0.015,
) -> tuple[list[tuple[float, int]], str]:
    """Return ([(distance, multiplicity), ...], formatted string)."""
    site = structure[site_index]
    o_dists = sorted(
        float(n.nn_distance)
        for n in structure.get_neighbors(site, cutoff)
        if n.specie.symbol == "O"
    )
    if not o_dists:
        return [], "—"

    groups: list[tuple[float, int]] = []
    current_dist = o_dists[0]
    current_count = 1
    for dist in o_dists[1:]:
        if abs(dist - current_dist) <= tol:
            current_count += 1
        else:
            groups.append((round(current_dist, 2), current_count))
            current_dist = dist
            current_count = 1
    groups.append((round(current_dist, 2), current_count))

    dist_str = ", ".join(f"{d:.2f}x{c}" for d, c in groups)
    return groups, dist_str


def get_magnetic_moments(structure: Structure) -> dict[int, float]:
    """Extract magmom from site properties if CHGNet populated them."""
    if "magmom" not in structure.site_properties:
        return {}
    moments = {}
    for i, m in enumerate(structure.site_properties["magmom"]):
        if m is None:
            continue
        val = float(m)
        if abs(val) > 1e-6:
            moments[i] = val
    return moments


def find_dopant_site_index(structure: Structure, dopant: str) -> int:
    indices = [i for i, site in enumerate(structure) if site.specie.symbol == dopant]
    if not indices:
        raise ValueError(f"Dopant {dopant} not found in relaxed structure.")
    return indices[0]


def nearest_co_neighbors(structure: Structure, dopant_index: int, n: int = 6) -> list[int]:
    site = structure[dopant_index]
    neighbors = structure.get_neighbors(site, 3.5)
    co_neighbors = sorted(
        (int(n.index), float(n.nn_distance))
        for n in neighbors
        if n.specie.symbol == "Co"
    )
    return [idx for idx, _ in co_neighbors[:n]]


def extract_magnetic_moments(
    structure: Structure,
    dopant: str,
    dopant_index: int,
) -> tuple[float | None, float | None]:
    """
    Return (mu_B on dopant, mu_B on additional polaron Co neighbor).

    CHGNet does not produce DFT+U magnetic moments; returns None when unavailable.
    """
    moments = get_magnetic_moments(structure)
    if not moments:
        return None, None

    mu_m = moments.get(dopant_index)
    co_neighbors = nearest_co_neighbors(structure, dopant_index)
    co_moments = [(moments[i], i) for i in co_neighbors if i in moments]
    if not co_moments:
        return mu_m, None

    # AP = nearest Co with largest |magnetic moment|
    mu_ap = max(co_moments, key=lambda x: abs(x[0]))[0]
    return mu_m, mu_ap


def space_group_symbol(structure: Structure) -> str:
    return structure.get_space_group_info()[0]


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

def build_mg_reference(
    api_key: str,
    chgnet: CHGNet,
    force: bool,
) -> ReferencePhase:
    """Mg reference = E(MgO)/fu + 0.5 * E(Li2O2)/fu per paper footnote."""
    (mgo_struct, mgo_id), (li2o2_struct, li2o2_id) = fetch_mgo_li2o2_references(api_key)
    mgo_ref = relax_reference_phase(mgo_struct, "ref_MgO", "mgo", chgnet, force=force, mp_id=mgo_id)
    li2o2_ref = relax_reference_phase(
        li2o2_struct, "ref_Li2O2", "li2o2", chgnet, force=force, mp_id=li2o2_id
    )
    e_fu = mgo_ref.energy_per_fu_eV + 0.5 * li2o2_ref.energy_per_fu_eV
    return ReferencePhase(
        label="MgO+0.5Li2O2",
        structure=mgo_ref.structure,
        energy_eV=mgo_ref.energy_eV,
        energy_per_fu_eV=e_fu,
        space_group=f"MgO({mgo_ref.space_group})+0.5Li2O2({li2o2_ref.space_group})",
        mp_id=f"{mgo_id}+{li2o2_id}",
    )


def analyze_dopant(
    dopant: str,
    supercell: Structure,
    primitive: Structure,
    e_pristine_fu: float,
    chgnet: CHGNet,
    api_key: str,
    mg_ref: ReferencePhase | None,
    force: bool,
) -> DopantResult:
    notes: list[str] = []
    co_site = first_co_site_index(supercell)

    # Doped 128-atom supercell
    doped = substitute(supercell, co_site, dopant)
    doped_final, e_doped = relax_structure(
        doped, f"LCO_{dopant}_128atom", chgnet, force=force
    )
    dopant_index = find_dopant_site_index(doped_final, dopant)
    mo_groups, mo_str = get_mo_distances(doped_final, dopant_index)
    mu_m, mu_ap = extract_magnetic_moments(doped_final, dopant, dopant_index)
    if mu_m is None:
        notes.append("CHGNet does not provide magnetic moments (paper uses DFT+U).")

    # LiMO2 (R-3m) reference
    limo2_r3m = build_limo2_r3m(dopant, primitive)
    ref_r3m = relax_reference_phase(
        limo2_r3m,
        f"ref_Li{dopant}O2_R3m",
        "limo2",
        chgnet,
        force=force,
    )

    # LiMO2 ground-state reference from MP
    if dopant == "Mg":
        if mg_ref is None:
            raise RuntimeError("Mg reference phase was not initialized.")
        ref_sg = mg_ref
        mp_id = ref_sg.mp_id
    elif dopant in R3M_GROUND_STATE:
        ref_sg = ref_r3m
        mp_id = None
        notes.append(f"{dopant}: ground-state LiMO2 is R-3m; Es(SG) = Es(R-3m).")
    else:
        gs_struct, gs_sg, mp_id = fetch_limo2_groundstate(dopant, api_key)
        ref_sg = relax_reference_phase(
            gs_struct,
            f"ref_Li{dopant}O2_MP_{mp_id}",
            "limo2",
            chgnet,
            force=force,
            mp_id=mp_id,
        )
        notes.append(f"MP ground-state SG hint: {gs_sg} ({mp_id}).")

    es_sg = compute_solution_energy(e_doped, e_pristine_fu, ref_sg.energy_per_fu_eV)
    es_r3m = compute_solution_energy(e_doped, e_pristine_fu, ref_r3m.energy_per_fu_eV)

    return DopantResult(
        dopant=dopant,
        site_index=dopant_index,
        mo_dist_str=mo_str,
        mo_distances=mo_groups,
        space_group=space_group_symbol(doped_final),
        mu_m=mu_m,
        mu_ap=mu_ap,
        es_sg=es_sg,
        es_r3m=es_r3m,
        delta_r=delta_r(dopant),
        e_doped_eV=e_doped,
        ref_sg=ref_sg,
        ref_r3m=ref_r3m,
        mp_id_sg=mp_id,
        notes=notes,
    )


def _fmt_float(val: float | None, digits: int = 2) -> str:
    if val is None:
        return "—"
    return f"{val:.{digits}f}"


def print_comparison_table(results: list[DopantResult]) -> None:
    print("\n" + "=" * 120)
    print("TABLE I COMPARISON — CHGNet vs Boev et al. (2024) bulk solution energies")
    print("=" * 120)
    print(
        f"{'Dopant':<6} {'Quantity':<12} {'CHGNet':<22} {'Paper (DFT+U)':<22} {'Delta':<10}"
    )
    print("-" * 120)

    for res in results:
        paper = PAPER_TABLE_I[res.dopant]
        print(f"\n{res.dopant} (ref SG: {res.ref_sg.label}, MP: {res.mp_id_sg or '—'})")
        if res.notes:
            for note in res.notes:
                print(f"  note: {note}")

        rows = [
            ("M-O dist", res.mo_dist_str, paper["mo_dist"], None),
            ("deltaR", f"{res.delta_r:.2f}", f"{paper['delta_r']:.2f}", res.delta_r - paper["delta_r"]),
            ("Es(SG)", f"{res.es_sg:.2f}", _fmt_float(paper["es_sg"]), res.es_sg - paper["es_sg"] if paper["es_sg"] is not None else None),
            ("Es(R-3m)", f"{res.es_r3m:.2f}", _fmt_float(paper["es_r3m"]), res.es_r3m - paper["es_r3m"] if paper["es_r3m"] is not None else None),
            ("muB(M)", _fmt_float(res.mu_m), _fmt_float(paper["mu_m"]), None),
            ("muB(AP)", _fmt_float(res.mu_ap), _fmt_float(paper["mu_ap"]), None),
        ]
        for quantity, chgnet_val, paper_val, diff in rows:
            diff_str = f"{diff:+.2f}" if diff is not None else "—"
            print(f"{'':6} {quantity:<12} {chgnet_val:<22} {paper_val:<22} {diff_str:<10}")

    print("\n" + "-" * 120)
    print("Methodological notes:")
    print("  - Paper: VASP PBE+U, 128-atom bulk supercell, OMC spin-state control.")
    print("  - CHGNet: MLIP (no Hubbard U), implicit spin; magmom columns often N/A.")
    print("  - Es = E(doped) - 31*E(LiCoO2/fu) - E(LiMO2/ref per fu)  [Eq. (1), n=32]")
    print("  - Mg Es(SG) uses E(MgO) + 0.5*E(Li2O2) reference (paper footnote a).")
    print("  - Table II surface segregation energies are not computed here.")
    print("=" * 120)


def save_results_json(results: list[DopantResult], e_pristine_fu: float, path: Path) -> None:
    payload = {
        "paper": "Boev et al., Phys. Rev. Materials 8, 055403 (2024)",
        "supercell_atoms": 128,
        "n_formula_units": N_FORMULA_UNITS,
        "e_lco_fu_eV": e_pristine_fu,
        "results": [
            {
                "dopant": r.dopant,
                "mo_distances": r.mo_distances,
                "mo_dist_str": r.mo_dist_str,
                "relaxed_sg": r.space_group,
                "mu_m": r.mu_m,
                "mu_ap": r.mu_ap,
                "es_sg_eV": r.es_sg,
                "es_r3m_eV": r.es_r3m,
                "delta_r": r.delta_r,
                "e_doped_eV": r.e_doped_eV,
                "ref_sg": {
                    "label": r.ref_sg.label,
                    "space_group": r.ref_sg.space_group,
                    "energy_per_fu_eV": r.ref_sg.energy_per_fu_eV,
                    "mp_id": r.ref_sg.mp_id,
                },
                "ref_r3m": {
                    "label": r.ref_r3m.label,
                    "space_group": r.ref_r3m.space_group,
                    "energy_per_fu_eV": r.ref_r3m.energy_per_fu_eV,
                },
                "paper_table_I": PAPER_TABLE_I[r.dopant],
                "notes": r.notes,
            }
            for r in results
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    print(f"\nSaved results -> {path}")


def run(force: bool = False, model_name: str = "r2scan") -> list[DopantResult]:
    api_key = require_mp_api_key()
    print(f"Using Materials Project API (MP_API_KEY set, length={len(api_key)}).")

    print("\n--- Building 128-atom LiCoO2 supercell ---")
    primitive, supercell = build_128atom_supercell()
    print(f"  Primitive: {len(primitive)} atoms ({primitive.composition.reduced_formula})")
    print(f"  Supercell: {len(supercell)} atoms ({supercell.composition.reduced_formula})")
    print(f"  Formula units: {li_formula_units(supercell):.0f}")

    print("\n--- Loading CHGNet ---")
    chgnet = CHGNet.load(model_name=model_name)

    print("\n--- Relaxing pristine 128-atom LiCoO2 ---")
    pristine_final, e_pristine = relax_structure(
        supercell, "LCO_pristine_128atom", chgnet, force=force
    )
    e_pristine_fu = energy_per_fu(pristine_final, e_pristine, fu_type="limo2")
    print(f"  E(LiCoO2) per f.u. = {e_pristine_fu:.4f} eV")

    print("\n--- Fetching MgO + Li2O2 references from MP ---")
    mg_ref = build_mg_reference(api_key, chgnet, force=force)
    print(f"  Mg reference E/f.u. = {mg_ref.energy_per_fu_eV:.4f} eV  ({mg_ref.label})")

    results: list[DopantResult] = []
    for dopant in DOPANTS:
        print(f"\n--- Dopant: {dopant} ---")
        result = analyze_dopant(
            dopant,
            supercell,
            primitive,
            e_pristine_fu,
            chgnet,
            api_key,
            mg_ref,
            force=force,
        )
        print(
            f"  Es(SG)={result.es_sg:.3f} eV  Es(R-3m)={result.es_r3m:.3f} eV  "
            f"deltaR={result.delta_r:.2f}  M-O: {result.mo_dist_str}"
        )
        results.append(result)

    print_comparison_table(results)
    save_results_json(results, e_pristine_fu, CACHE_DIR / "table_I_comparison.json")
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare CHGNet bulk solution energies to Boev et al. (2024) Table I."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute all relaxations (ignore cache).",
    )
    parser.add_argument(
        "--model",
        default="r2scan",
        help="CHGNet model name (default: r2scan).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(force=args.force, model_name=args.model)
