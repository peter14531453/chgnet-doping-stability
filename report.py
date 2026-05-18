"""
Stability report module.

Aggregates results from relaxation + MD and prints a structured verdict
based on the doping-stability criteria:

    1. Formation energy E_f below threshold
    2. Dopant MSD plateaus (no runaway diffusion)
    3. Local coordination stays chemically sensible
    4. No structural collapse (volume / space group preserved)

Plus the interpretive rules:
    - High E_f but MD stable           -> METASTABLE
    - Low E_f but MD shows migration   -> dopant prefers a different site
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


EF_THRESHOLD_FAVORABLE = 0.0
EF_THRESHOLD_OK = 1.0
MSD_PLATEAU_SLOPE_A2_PER_PS = 0.005
COORDINATION_TOLERANCE = 1
VOLUME_CHANGE_TOLERANCE_PCT = 5.0


def _fmt(value, fmt="{:.3f}", na="n/a"):
    return na if value is None else fmt.format(value)


def _tag(passed):
    if passed is None:
        return "[ SKIP ]"
    return "[ PASS ]" if passed else "[ FAIL ]"


@dataclass
class StabilityReport:
    test_name: str
    host_formula: str
    dopant: str
    target_site_element: str
    site_index: int
    supercell_size: int

    formation_energy_eV: float | None = None
    pristine_energy_eV: float | None = None
    doped_energy_eV: float | None = None
    mu_dopant_eV: float | None = None
    mu_removed_eV: float | None = None

    relaxed_space_group: str | None = None
    relaxed_coordination: int | None = None
    relaxed_mean_nn_distance_A: float | None = None
    relaxed_nn_distances_A: list[float] = field(default_factory=list)

    md_temperature_K: float | None = None
    md_duration_ps: float | None = None
    md_msd_slope_A2_per_ps: float | None = None
    md_msd_final_A2: float | None = None
    md_max_displacement_A: float | None = None
    md_coordination_min: int | None = None
    md_coordination_max: int | None = None
    md_coordination_mean: float | None = None
    md_volume_change_pct: float | None = None
    md_space_group: str | None = None
    md_mean_nn_distance_A: float | None = None

    notes: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def ef_pass(self):
        if self.formation_energy_eV is None:
            return None
        return self.formation_energy_eV < EF_THRESHOLD_OK

    @property
    def ef_favorable(self):
        if self.formation_energy_eV is None:
            return None
        return self.formation_energy_eV < EF_THRESHOLD_FAVORABLE

    @property
    def msd_pass(self):
        if self.md_msd_slope_A2_per_ps is None:
            return None
        return self.md_msd_slope_A2_per_ps < MSD_PLATEAU_SLOPE_A2_PER_PS

    @property
    def coordination_pass(self):
        if (
            self.relaxed_coordination is None
            or self.md_coordination_min is None
            or self.md_coordination_max is None
        ):
            return None
        low = abs(self.md_coordination_min - self.relaxed_coordination)
        high = abs(self.md_coordination_max - self.relaxed_coordination)
        return max(low, high) <= COORDINATION_TOLERANCE

    @property
    def lattice_pass(self):
        if self.md_volume_change_pct is None:
            return None
        return abs(self.md_volume_change_pct) < VOLUME_CHANGE_TOLERANCE_PCT

    @property
    def space_group_preserved(self):
        if self.relaxed_space_group is None or self.md_space_group is None:
            return None
        return self.relaxed_space_group == self.md_space_group

    @property
    def verdict(self):
        ef = self.ef_pass
        msd = self.msd_pass
        coord = self.coordination_pass
        latt = self.lattice_pass

        if msd is None:
            if ef is None:
                return "INCOMPLETE"
            return "FAVORABLE (relaxation only)" if ef else "UNFAVORABLE (relaxation only)"

        structural_ok = (coord is not False) and (latt is not False)

        if ef and msd and structural_ok:
            return "STABLE"
        if (ef is False) and msd and structural_ok:
            return "METASTABLE"
        if ef and (msd is False) and structural_ok:
            return "MIGRATION (favorable site but dopant relocates during MD)"
        if (msd is False) and not structural_ok:
            return "UNSTABLE (migration + structural distortion)"
        if not structural_ok:
            return "STRUCTURAL COLLAPSE"
        if msd is False:
            return "MIGRATION / UNFAVORABLE"
        return "UNSTABLE"

    def to_dict(self):
        d = asdict(self)
        d["verdict"] = self.verdict
        d["ef_pass"] = self.ef_pass
        d["msd_pass"] = self.msd_pass
        d["coordination_pass"] = self.coordination_pass
        d["lattice_pass"] = self.lattice_pass
        d["space_group_preserved"] = self.space_group_preserved
        return d

    def save(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    def print_report(self):
        line = "=" * 78
        print()
        print(line)
        print(f" STABILITY REPORT  -  {self.test_name}")
        print(f" Generated: {self.timestamp}")
        print(line)
        print(f"  Host:           {self.host_formula}  (supercell {self.supercell_size}^3)")
        print(
            f"  Doping:         {self.dopant} -> {self.target_site_element} "
            f"(site index {self.site_index})"
        )
        print()

        print("--- Phase 3: Formation energy ----------------------------------------------")
        print(f"  E(doped)     = {_fmt(self.doped_energy_eV)} eV")
        print(f"  E(pristine)  = {_fmt(self.pristine_energy_eV)} eV")
        print(f"  mu({self.dopant})       = {_fmt(self.mu_dopant_eV)} eV/atom")
        print(f"  mu({self.target_site_element})       = {_fmt(self.mu_removed_eV)} eV/atom")
        print(
            f"  E_f          = {_fmt(self.formation_energy_eV)} eV   "
            f"{_tag(self.ef_pass)}  (threshold {EF_THRESHOLD_OK} eV)"
        )
        if self.ef_favorable:
            print("                 -> very favorable (E_f < 0)")
        print(f"  Relaxed space group:        {self.relaxed_space_group or 'n/a'}")
        print(f"  Relaxed coordination (NN):  {self.relaxed_coordination or 'n/a'}")
        print(f"  Mean NN distance:           {_fmt(self.relaxed_mean_nn_distance_A)} A")
        print()

        print("--- Phase 4-5: Finite-temperature MD ---------------------------------------")
        if self.md_msd_slope_A2_per_ps is None:
            print("  (no MD data on this run)")
        else:
            print(f"  Temperature:                {_fmt(self.md_temperature_K, '{:.0f}')} K")
            print(f"  Duration:                   {_fmt(self.md_duration_ps, '{:.1f}')} ps")
            print(
                f"  Dopant MSD slope:           "
                f"{_fmt(self.md_msd_slope_A2_per_ps, '{:.4f}')} A^2/ps   "
                f"{_tag(self.msd_pass)}  (plateau if < {MSD_PLATEAU_SLOPE_A2_PER_PS})"
            )
            print(f"  Final MSD:                  {_fmt(self.md_msd_final_A2, '{:.3f}')} A^2")
            print(f"  Max displacement:           {_fmt(self.md_max_displacement_A)} A")
            print(
                f"  Coordination (min/mean/max): "
                f"{self.md_coordination_min}/"
                f"{_fmt(self.md_coordination_mean, '{:.1f}')}/"
                f"{self.md_coordination_max}   "
                f"{_tag(self.coordination_pass)}"
            )
            print(f"  Mean NN distance during MD: {_fmt(self.md_mean_nn_distance_A)} A")
            print(
                f"  Volume change:              "
                f"{_fmt(self.md_volume_change_pct, '{:+.2f}')} %   "
                f"{_tag(self.lattice_pass)}  (tolerance +/- {VOLUME_CHANGE_TOLERANCE_PCT}%)"
            )
            print(
                f"  Space group during MD:      {self.md_space_group or 'n/a'}   "
                f"{_tag(self.space_group_preserved)}"
            )
        print()

        print("--- Verdict ----------------------------------------------------------------")
        print(f"  {self.verdict}")
        print()
        print("  Interpretation:")
        print(self._interpretation_lines())
        if self.notes:
            print()
            print("  Notes:")
            for note in self.notes:
                print(f"    - {note}")
        print(line)
        print()

    def _interpretation_lines(self):
        v = self.verdict
        if v.startswith("STABLE"):
            return (
                "    Dopant is thermodynamically favorable and kinetically stable\n"
                "    at this site at the simulated temperature. Site occupancy is\n"
                "    consistent throughout MD and the lattice is preserved."
            )
        if v.startswith("METASTABLE"):
            return (
                "    E_f is above the favorable threshold but MD shows the dopant\n"
                "    sits stably on this site without migration or structural collapse.\n"
                "    Achievable via non-equilibrium synthesis (e.g. quench, ion-exchange)."
            )
        if v.startswith("MIGRATION"):
            return (
                "    Dopant MSD does not plateau -- the dopant is moving during MD.\n"
                "    The relaxed site is NOT where the dopant actually ends up.\n"
                "    Inspect the trajectory: the late-time dopant position reveals the\n"
                "    true preferred site (interstitial, neighboring substitutional, or\n"
                "    surface segregation)."
            )
        if v.startswith("STRUCTURAL"):
            return (
                "    Lattice volume or symmetry changes significantly during MD.\n"
                "    The doped phase is not mechanically stable at this temperature\n"
                "    and concentration. Reduce dopant concentration or temperature."
            )
        if v.startswith("FAVORABLE"):
            return (
                "    Relaxation indicates a favorable formation energy. Run the MD\n"
                "    phase to confirm finite-temperature stability."
            )
        if v.startswith("UNFAVORABLE"):
            return (
                "    Formation energy exceeds the threshold. Dopant is unlikely to\n"
                "    incorporate at this site under equilibrium conditions."
            )
        if v == "INCOMPLETE":
            return "    Run relaxation (and ideally MD) to populate the report."
        return "    See per-criterion flags above."


def write_summary_table(reports, path):
    """Write a CSV-style summary across multiple reports."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    header = [
        "test_name",
        "site_index",
        "E_f_eV",
        "relaxed_SG",
        "coord_relaxed",
        "MSD_slope",
        "MSD_final",
        "vol_change_pct",
        "MD_SG",
        "verdict",
    ]
    with open(path, "w") as f:
        f.write(",".join(header) + "\n")
        for r in reports:
            row = [
                r.test_name,
                str(r.site_index),
                _fmt(r.formation_energy_eV, "{:.4f}"),
                r.relaxed_space_group or "",
                str(r.relaxed_coordination or ""),
                _fmt(r.md_msd_slope_A2_per_ps, "{:.4f}"),
                _fmt(r.md_msd_final_A2, "{:.3f}"),
                _fmt(r.md_volume_change_pct, "{:.2f}"),
                r.md_space_group or "",
                r.verdict,
            ]
            f.write(",".join(row) + "\n")
