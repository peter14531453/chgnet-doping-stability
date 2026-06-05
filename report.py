"""
Stability report module.

Aggregates results from relaxation + MD and prints a structured verdict
based on the doping-stability criteria:

    1. Formation energy E_f below threshold
    2. Dopant MSD plateaus (no runaway diffusion)
    3. No structural collapse (lattice volume preserved)

Coordination number is still measured and reported, but — like the
time-averaged space group — it is NOT a pass/fail criterion: the
first-shell count is too sensitive to the bond-length cutoff to gate on
(large-ion dopants whose bonds sit near the cutoff at rest produced
spurious "collapse" verdicts). Lattice volume is the structural gate.

Plus the interpretive rules:
    - High E_f but MD stable           -> METASTABLE
    - Low E_f but MD shows migration   -> dopant prefers a different site
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


# --- Stability thresholds ---------------------------------------------------
# These control the PASS/FAIL criteria in StabilityReport. Adjust here if
# you want stricter or looser definitions for your material system.

# Formation energy: below 0 eV is thermodynamically very favourable;
# below 1 eV is marginally feasible under equilibrium conditions.
EF_THRESHOLD_FAVORABLE = 0.0      # eV — "very good" boundary
EF_THRESHOLD_OK = 1.0             # eV — overall PASS/FAIL boundary

# MSD slope: a dopant oscillating around one site has a slope near zero.
# Above the effective cutoff we call it "migrating". This value is an ABSOLUTE
# FLOOR -- the smallest slope ever treated as migration, even in an
# exceptionally quiet run -- corresponding to roughly one bond-length hop over
# the production run. The actual per-run cutoff (see msd_threshold_A2_per_ps)
# is the LARGER of this floor and the thermal-noise margin of error below, so
# the test can only become stricter than this floor, never looser.
MSD_PLATEAU_SLOPE_A2_PER_PS = 0.005

# Thermal-noise calibration. A dopant confined to its site still produces a
# nonzero late-time MSD slope purely from thermal vibration; the per-run
# standard error of that slope (analysis key "msd_slope_stderr_A2_per_ps",
# corrected for the MSD's strong autocorrelation) IS the margin of error of
# those thermal fluctuations. A slope smaller than a few stderr is
# statistically indistinguishable from a plateau. We require the slope to clear
# the noise by this many standard errors before calling it migration, so the
# cutoff sits at the edge of the thermal margin of error rather than at an
# arbitrary fixed number. 2.0 ~ a one-sided 97.5% confidence that the slope is
# real and not thermal jitter.
MSD_NOISE_SIGMA = 2.0

# Volume tolerance: >5% volume change during MD usually signals mechanical
# instability or a phase transition at the simulation temperature.
VOLUME_CHANGE_TOLERANCE_PCT = 5.0


def _fmt(value, fmt="{:.3f}", na="n/a"):
    return na if value is None else fmt.format(value)


def _tag(passed):
    if passed is None:
        return "[ SKIP ]"
    return "[ PASS ]" if passed else "[ FAIL ]"


def site_report_stem(
    host_formula: str,
    dopant: str,
    target_site_element: str,
    site_index: int,
) -> str:
    """Basename for per-site outputs: host, dopant, site layer, and site index."""
    return f"{host_formula}_{dopant}@{target_site_element}_site{site_index}"


def run_report_stem(host_formula: str, dopant: str) -> str:
    """Basename for run-level summary and final report files."""
    return f"{host_formula}_{dopant}"


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
    md_msd_slope_stderr_A2_per_ps: float | None = None
    md_msd_final_A2: float | None = None
    md_max_displacement_A: float | None = None
    md_coordination_min: int | None = None
    md_coordination_max: int | None = None
    md_coordination_mean: float | None = None
    md_volume_change_pct: float | None = None
    md_space_group: str | None = None
    md_mean_nn_distance_A: float | None = None

    charge_mismatch: int | None = None
    compensation_applied: bool = False
    compensation_description: str = ""

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
    def msd_threshold_A2_per_ps(self):
        """Effective migration cutoff for this run: the larger of the fixed
        floor and the thermal-noise margin of error (MSD_NOISE_SIGMA x the
        slope's standard error). Falls back to the floor alone when no stderr
        was recorded (e.g. analyses cached before noise calibration existed)."""
        floor = MSD_PLATEAU_SLOPE_A2_PER_PS
        se = self.md_msd_slope_stderr_A2_per_ps
        if se is None or se != se:    # None or NaN -> no calibration available
            return floor
        return max(floor, MSD_NOISE_SIGMA * se)

    @property
    def msd_pass(self):
        slope = self.md_msd_slope_A2_per_ps
        if slope is None or slope != slope:   # missing or NaN (no reliable fit)
            return None
        # Confined (pass) when the slope stays below the noise-calibrated cutoff;
        # a slope within +/- the thermal margin of error is just vibration.
        return slope < self.msd_threshold_A2_per_ps

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
        """Combine all PASS/FAIL criteria into a single human-readable verdict.

        Decision tree
        -------------
        No MD data yet:
            INCOMPLETE          — nothing has been calculated
            FAVORABLE/UNFAVORABLE (relaxation only) — E_f known, no MD yet

        MD data available:
            structural_ok = lattice volume preserved (or skipped)

            STABLE              — E_f ok  AND MSD plateaus AND structure intact
            METASTABLE          — E_f too high BUT MD shows dopant stays put;
                                  achievable via non-equilibrium synthesis
            MIGRATION           — E_f ok BUT dopant moves during MD;
                                  the relaxed site is not the true resting site
            STRUCTURAL COLLAPSE — lattice volume breaks down;
                                  doped phase is mechanically unstable at T
            UNSTABLE            — catch-all for other failure combinations
        """
        ef = self.ef_pass
        msd = self.msd_pass
        latt = self.lattice_pass

        if msd is None:
            if ef is None:
                return "INCOMPLETE"
            return "FAVORABLE (relaxation only)" if ef else "UNFAVORABLE (relaxation only)"

        # structural_ok is False only when the lattice volume actively fails (not None)
        structural_ok = (latt is not False)

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
        d["msd_threshold_A2_per_ps"] = self.msd_threshold_A2_per_ps
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
        if self.charge_mismatch is not None:
            mismatch_str = f"{self.charge_mismatch:+d}" if self.charge_mismatch != 0 else "0 (isovalent)"
            print(f"  Charge mismatch:{mismatch_str}")
            print(f"  Compensation:   {self.compensation_description or 'none'}")
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
            se = self.md_msd_slope_stderr_A2_per_ps
            se_str = f" +/- {se:.4f}" if (se is not None and se == se) else ""
            thr = self.msd_threshold_A2_per_ps
            noise_set = (se is not None and se == se
                         and MSD_NOISE_SIGMA * se > MSD_PLATEAU_SLOPE_A2_PER_PS)
            gate = (f"{MSD_NOISE_SIGMA:g}x thermal stderr"
                    if noise_set else f"{MSD_PLATEAU_SLOPE_A2_PER_PS} floor")
            print(
                f"  Dopant MSD slope:           "
                f"{_fmt(self.md_msd_slope_A2_per_ps, '{:.4f}')}{se_str} A^2/ps   "
                f"{_tag(self.msd_pass)}  (migration if > {thr:.4f}, set by {gate})"
            )
            print(f"  Final MSD:                  {_fmt(self.md_msd_final_A2, '{:.3f}')} A^2")
            print(f"  Max displacement:           {_fmt(self.md_max_displacement_A)} A")
            print(
                f"  Coordination (min/mean/max): "
                f"{self.md_coordination_min}/"
                f"{_fmt(self.md_coordination_mean, '{:.1f}')}/"
                f"{self.md_coordination_max}   "
                f"(informational — sensitive to bond cutoff, not used in verdict)"
            )
            print(f"  Mean NN distance during MD: {_fmt(self.md_mean_nn_distance_A)} A")
            print(
                f"  Volume change:              "
                f"{_fmt(self.md_volume_change_pct, '{:+.2f}')} %   "
                f"{_tag(self.lattice_pass)}  (tolerance +/- {VOLUME_CHANGE_TOLERANCE_PCT}%)"
            )
            print(
                f"  Space group during MD:      {self.md_space_group or 'n/a'}   "
                f"(informational only — MD thermal noise always yields P1)"
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
        "host",
        "dopant",
        "dopant_site",
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
                r.host_formula,
                r.dopant,
                r.target_site_element,
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


def write_final_report(
    reports,
    path,
    host_formula: str,
    dopant: str,
    target_elements: list[str],
):
    """Save aggregated run results (all sites) as JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(reports, key=lambda r: r.formation_energy_eV)
    best = ordered[0] if ordered else None
    per_layer: dict[str, dict] = {}
    for r in reports:
        layer = r.target_site_element
        if layer not in per_layer or r.formation_energy_eV < per_layer[layer]["formation_energy_eV"]:
            per_layer[layer] = {
                "test_name": r.test_name,
                "site_index": r.site_index,
                "formation_energy_eV": r.formation_energy_eV,
                "verdict": r.verdict,
            }
    payload = {
        "host_formula": host_formula,
        "dopant": dopant,
        "target_elements": target_elements,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "n_tests": len(reports),
        "best_overall": best.to_dict() if best else None,
        "best_per_layer": per_layer,
        "reports": [r.to_dict() for r in reports],
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
