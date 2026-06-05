"""
Plain-English Markdown report generator for doping stability results.

Produces a .md file that explains simulation results in a way accessible
to readers without materials science or computational chemistry background.
Every number is accompanied by a plain-English sentence saying what it
means and whether it is good or bad.

Called automatically at the end of run_workflow.run(), and also usable
as a standalone script:

    python generate_md_report.py reports/2026-05-21/NaCoO2_Al_final.json
    python generate_md_report.py reports/2026-05-21/
    python generate_md_report.py reports/2026-05-21/NaCoO2_Al@Co_site24.json reports/2026-05-21/NaCoO2_Al@Na_site0.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds — must match report.py
# ---------------------------------------------------------------------------
EF_THRESHOLD_OK = 1.0
MSD_PLATEAU_SLOPE = 0.005
VOLUME_TOLERANCE_PCT = 5.0


# ---------------------------------------------------------------------------
# Verdict badge helpers
# ---------------------------------------------------------------------------

def _verdict_badge(verdict: str) -> str:
    if "STABLE" in verdict and "METASTABLE" not in verdict:
        return f"✅ **{verdict}**"
    if "METASTABLE" in verdict:
        return f"⚠️ **{verdict}**"
    if "MIGRATION" in verdict:
        return f"⚠️ **{verdict}**"
    if "COLLAPSE" in verdict or "UNSTABLE" in verdict or "UNFAVORABLE" in verdict:
        return f"❌ **{verdict}**"
    if "FAVORABLE" in verdict:
        return f"🔷 **{verdict}**"
    return f"❓ **{verdict}**"


def _pass_fail(passed: bool | None) -> str:
    if passed is True:
        return "✅ PASS"
    if passed is False:
        return "❌ FAIL"
    return "— (not tested)"


# ---------------------------------------------------------------------------
# Narrative helpers — plain English explanations
# ---------------------------------------------------------------------------

def _ef_plain(ef: float, mismatch: int, dopant: str, target: str) -> str:
    approx_note = ""
    if mismatch > 0:
        approx_note = (
            "\n\n> **Note on accuracy:** This formation energy is approximate. "
            "The dopant carries a different electric charge than the atom it replaced, "
            "and the simulation model (CHGNet) cannot fully account for that electrical imbalance. "
            "Treat this value as an estimate rather than an exact number."
        )

    if ef < -3.0:
        plain = (
            f"The formation energy is **{ef:+.3f} eV** — an exceptionally large negative value. "
            f"In simple terms: the crystal strongly 'wants' to incorporate {dopant} at the "
            f"{target} site. A large negative value means the process releases a lot of energy, "
            f"making it thermodynamically driven. This is as favorable as it gets."
        )
    elif ef < -1.0:
        plain = (
            f"The formation energy is **{ef:+.3f} eV** — strongly negative. "
            f"Placing {dopant} on the {target} site releases energy, so the process happens "
            f"spontaneously under normal conditions. The material is very likely to accept "
            f"this dopant."
        )
    elif ef < 0:
        plain = (
            f"The formation energy is **{ef:+.3f} eV** — slightly negative. "
            f"Incorporating {dopant} at the {target} site releases a small amount of energy. "
            f"The process is thermodynamically favorable, though not by a wide margin."
        )
    elif ef < 0.5:
        plain = (
            f"The formation energy is **{ef:+.3f} eV** — slightly positive. "
            f"A small amount of energy must be supplied to place {dopant} at the {target} site. "
            f"This is not spontaneous under equilibrium conditions, but may be achievable through "
            f"controlled synthesis techniques."
        )
    elif ef < EF_THRESHOLD_OK:
        plain = (
            f"The formation energy is **{ef:+.3f} eV** — moderately positive. "
            f"Incorporating {dopant} at the {target} site requires energy input and is unlikely "
            f"under standard conditions. Non-equilibrium synthesis routes (e.g., ion exchange, "
            f"rapid quenching) might still achieve this configuration."
        )
    else:
        plain = (
            f"The formation energy is **{ef:+.3f} eV** — large and positive. "
            f"A significant amount of energy is required to place {dopant} at the {target} site. "
            f"Under most synthesis conditions this dopant configuration would not form."
        )

    return plain + approx_note


def _msd_plain(slope: float, final: float, max_disp: float,
               threshold: float = MSD_PLATEAU_SLOPE) -> str:
    if slope < threshold:
        if slope < 0.2 * threshold:
            mobility = (
                f"An MSD slope this close to zero ({slope:.5f} Å²/ps) means the dopant was "
                f"essentially locked in place — it barely moved at all during the simulation."
            )
        else:
            mobility = (
                f"The MSD slope ({slope:.5f} Å²/ps) is below this run's stability threshold of "
                f"{threshold:.5f} Å²/ps — within the thermal-fluctuation noise — confirming the "
                f"dopant stayed near its original position and did not migrate."
            )
    elif slope < 4 * threshold:
        mobility = (
            f"The MSD slope ({slope:.5f} Å²/ps) exceeds this run's stability threshold of "
            f"{threshold:.5f} Å²/ps, suggesting the dopant drifted slightly or hopped "
            f"between nearby atomic sites."
        )
    else:
        mobility = (
            f"The MSD slope ({slope:.5f} Å²/ps) is well above the migration threshold. "
            f"The dopant diffused significantly away from its intended site — it did not "
            f"stay in place during heating."
        )

    return (
        f"{mobility} "
        f"The farthest the dopant moved from its starting position was **{max_disp:.2f} Å** "
        f"(about {max_disp / 0.529:.1f} times the Bohr radius), "
        f"with a final mean-squared displacement of **{final:.3f} Å²**."
    )


def _coordination_plain(cn_min: int, cn_max: int, cn_mean: float, cn_relax: int, mean_bond: float) -> str:
    if cn_min == cn_max == cn_relax:
        desc = (
            f"The dopant had exactly **{cn_relax} neighboring oxygen atoms** throughout the "
            f"entire simulation — the same number as right after relaxation. "
            f"The local bonding environment was perfectly preserved."
        )
    else:
        desc = (
            f"The number of neighboring oxygen atoms ranged from **{cn_min} to {cn_max}** "
            f"(average: {cn_mean:.1f}) during heating, compared to {cn_relax} after relaxation. "
            f"This count is very sensitive to the exact bond-length cutoff used to define a "
            f"neighbor, so it is reported for context only and does not affect the verdict."
        )
    return f"{desc} The average dopant–oxygen bond length during the simulation was **{mean_bond:.3f} Å**."


def _volume_plain(dv: float) -> str:
    if abs(dv) < 1.0:
        return (
            f"The crystal's volume changed by only **{dv:+.2f}%** — essentially no change. "
            f"The host lattice is mechanically stable with this dopant."
        )
    if abs(dv) < VOLUME_TOLERANCE_PCT:
        return (
            f"The crystal's volume changed by **{dv:+.2f}%**. "
            f"This is a moderate change but within the acceptable ±{VOLUME_TOLERANCE_PCT:.0f}% range. "
            f"The material remains structurally stable."
        )
    return (
        f"The crystal's volume changed by **{dv:+.2f}%** — exceeding the ±{VOLUME_TOLERANCE_PCT:.0f}% "
        f"tolerance. This large volume change suggests the material may become mechanically "
        f"unstable at operating temperature with this dopant."
    )


def _verdict_plain(r: dict) -> str:
    verdict = r["verdict"]
    dopant = r["dopant"]
    target = r["target_site_element"]
    temp_c = (r.get("md_temperature_K") or 523.15) - 273.15

    if verdict == "STABLE":
        return (
            f"**{dopant} is a strong candidate for the {target} site.** "
            f"All stability tests passed: the formation energy is thermodynamically "
            f"favorable, the dopant does not migrate at {temp_c:.0f}°C, and the host crystal "
            f"does not expand or contract excessively. This result supports further "
            f"experimental investigation."
        )
    if verdict == "METASTABLE":
        return (
            f"**{dopant} stays in place once it is on the {target} site, but it may be "
            f"hard to incorporate under standard conditions.** "
            f"The simulation shows the dopant is thermally stable at {temp_c:.0f}°C (good), "
            f"but the formation energy exceeds the equilibrium threshold — the material does "
            f"not spontaneously want to take in this dopant. "
            f"Special synthesis techniques like ion exchange or rapid quenching may still work."
        )
    if verdict.startswith("MIGRATION"):
        return (
            f"**{dopant} does not stay on the {target} site — it moves during the simulation.** "
            f"Although the formation energy looks favorable, the dopant atom migrates at "
            f"{temp_c:.0f}°C. The {target} site is not a stable resting place for this dopant. "
            f"Inspecting the MD trajectory could reveal where it ends up."
        )
    if verdict == "STRUCTURAL COLLAPSE":
        return (
            f"**The crystal structure was destabilized at {temp_c:.0f}°C with this dopant.** "
            f"The overall crystal volume changed beyond the acceptable range during heating. "
            f"This dopant–site combination is unlikely to survive at operating temperature."
        )
    if "FAVORABLE" in verdict:
        ef = r.get("formation_energy_eV", 0)
        return (
            f"The formation energy is favorable ({ef:+.3f} eV), but no molecular dynamics "
            f"simulation was run for this configuration. Only thermodynamic feasibility has "
            f"been assessed — thermal stability at operating temperature is still unknown."
        )
    if "UNFAVORABLE" in verdict:
        ef = r.get("formation_energy_eV", 0)
        return (
            f"The formation energy is unfavorable ({ef:+.3f} eV). "
            f"{dopant} is unlikely to incorporate at the {target} site under normal conditions. "
            f"No further simulation was performed."
        )
    return f"Verdict: {verdict}."


def _site_preference_plain(reports: list[dict]) -> str:
    """Generate a cross-layer comparison paragraph when multiple target elements exist."""
    target_bests: dict[str, dict] = {}
    for r in reports:
        t = r["target_site_element"]
        if t not in target_bests or r["formation_energy_eV"] < target_bests[t]["formation_energy_eV"]:
            target_bests[t] = r
    if len(target_bests) < 2:
        return ""

    ordered = sorted(target_bests.values(), key=lambda r: r["formation_energy_eV"])
    winner = ordered[0]
    runner = ordered[1]
    delta = runner["formation_energy_eV"] - winner["formation_energy_eV"]
    dopant = winner["dopant"]

    parts = [
        f"**{dopant} strongly prefers to occupy the {winner['target_site_element']} layer**, "
        f"with a formation energy {delta:.3f} eV lower than the "
        f"{runner['target_site_element']} layer. "
        f"Put simply: the material 'wants' the dopant on the {winner['target_site_element']} "
        f"site much more than the {runner['target_site_element']} site."
    ]

    wm = winner.get("md_msd_slope_A2_per_ps")
    rm = runner.get("md_msd_slope_A2_per_ps")
    if wm is not None and rm is not None:
        parts.append(
            f"The MD results reinforce this: dopant movement on the "
            f"{winner['target_site_element']} site was {wm:.5f} Å²/ps (stable) "
            f"vs {rm:.5f} Å²/ps on the {runner['target_site_element']} site."
        )

    if winner.get("charge_mismatch", 0) == 0:
        parts.append(
            f"The {winner['target_site_element']}-site result is the most reliable because "
            f"there is no charge mismatch — the dopant carries the same oxidation state as "
            f"the atom it replaced, so the energy calculation is fully accurate."
        )
    if (runner.get("charge_mismatch") or 0) > 0:
        parts.append(
            f"The {runner['target_site_element']}-site energy is approximate (charge surplus "
            f"of +{runner['charge_mismatch']} cannot be fully modelled in CHGNet)."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Main Markdown generator
# ---------------------------------------------------------------------------

def generate_md(
    reports: list[dict],
    out_path: Path,
    host_formula: str,
    dopant: str,
    temperature_C: float = 250.0,
) -> Path:
    """
    Write a plain-English Markdown stability report.

    Parameters
    ----------
    reports       : list of StabilityReport.to_dict() records
    out_path      : output .md file path
    host_formula  : e.g. "NaCoO2"
    dopant        : e.g. "Al"
    temperature_C : MD simulation temperature in Celsius
    """
    temperature_K = temperature_C + 273.15
    now = datetime.now().strftime("%B %d, %Y at %I:%M %p")

    best_overall = min(reports, key=lambda r: r["formation_energy_eV"])
    target_names = sorted({r["target_site_element"] for r in reports})
    target_str = " and ".join(target_names) if len(target_names) > 1 else target_names[0]

    L: list[str] = []

    # ── Title ────────────────────────────────────────────────────────────────
    L += [
        f"# Doping Stability Report: {dopant} in {host_formula}",
        "",
        f"*Generated: {now}*  ",
        f"*Simulation temperature: {temperature_C:.0f}°C ({temperature_K:.1f} K)*  ",
        f"*Total configurations tested: {len(reports)}*",
        "",
        "---",
        "",
    ]

    # ── Section 1: What This Study Tests ─────────────────────────────────────
    L += [
        "## 1. What Is This Study Testing?",
        "",
        f"This study investigates whether **{dopant}** (the *dopant*) can be stably "
        f"inserted into the crystal structure of **{host_formula}** (the *host material*) "
        f"by replacing one of the **{target_str}** atoms already present in the crystal. "
        f"This process is called *doping*.",
        "",
        "**Why does this matter?**",
        "",
        f"Battery cathode materials like {host_formula} can sometimes be improved by "
        f"substituting a fraction of their atoms with a different element. However, not "
        f"every dopant is stable — some are thermodynamically unfavorable, and some cause "
        f"the crystal structure to deteriorate during battery operation at elevated temperatures. "
        f"This simulation workflow tests both aspects:",
        "",
        f"1. **Thermodynamic feasibility** — Is it energetically favorable to place {dopant} "
        f"into the crystal? (Formation energy test)",
        f"2. **Thermal stability** — Does the crystal remain intact when heated to "
        f"{temperature_C:.0f}°C? (Molecular dynamics simulation)",
        "",
        "---",
        "",
    ]

    # ── Section 2: Quick Summary ──────────────────────────────────────────────
    L += ["## 2. Quick Summary of Results", ""]

    site_pref = _site_preference_plain(reports)
    if site_pref:
        L += [site_pref, ""]

    # Summary table
    L += [
        "| Site # | Target Layer | Formation Energy | Thermodynamic? | Thermal Stability | Verdict |",
        "|--------|-------------|-----------------|---------------|-------------------|---------|",
    ]
    for r in sorted(reports, key=lambda x: x["formation_energy_eV"]):
        ef = r["formation_energy_eV"]
        ef_ok = r.get("ef_pass", ef < EF_THRESHOLD_OK)
        msd = r.get("md_msd_slope_A2_per_ps")
        verdict = r["verdict"]
        thermo = "✅ Favorable" if ef_ok else "❌ Unfavorable"
        if msd is not None:
            msd_ok = r.get("msd_pass")
            if msd_ok is None:
                msd_ok = msd < r.get("msd_threshold_A2_per_ps", MSD_PLATEAU_SLOPE)
            therm = "✅ Stable" if msd_ok else "❌ Migrating"
        else:
            therm = "— Not tested"
        badge = (
            "✅ STABLE" if "STABLE" in verdict and "META" not in verdict
            else f"⚠️ {verdict}" if "METASTABLE" in verdict or "MIGRATION" in verdict
            else f"❌ {verdict}"
        )
        L.append(
            f"| {r['site_index']} | {r['target_site_element']} "
            f"| {ef:+.3f} eV | {thermo} | {therm} | {badge} |"
        )

    L += [
        "",
        f"**Best overall:** Site {best_overall['site_index']} "
        f"({best_overall['target_site_element']} layer) — "
        f"E_f = {best_overall['formation_energy_eV']:+.3f} eV, "
        f"verdict: **{best_overall['verdict']}**",
        "",
        "---",
        "",
    ]

    # ── Section 3: Detailed Per-Site Results ─────────────────────────────────
    L += [
        "## 3. Detailed Results",
        "",
        "> *Each subsection below describes one tested atomic configuration in detail.*",
        "",
    ]

    for rank, r in enumerate(sorted(reports, key=lambda x: x["formation_energy_eV"]), 1):
        target = r["target_site_element"]
        site_idx = r["site_index"]
        ef = r["formation_energy_eV"]
        verdict = r["verdict"]
        mismatch = r.get("charge_mismatch", 0) or 0
        comp_desc = r.get("compensation_description", "")

        L += [
            f"### 3.{rank}  Site {site_idx}: {dopant} replacing {target}",
            "",
            f"**Overall verdict: {_verdict_badge(verdict)}**",
            "",
        ]

        # Charge situation
        if mismatch == 0:
            charge_info = (
                f"**Charge balance:** {dopant} and {target} have the same oxidation state "
                f"(*isovalent substitution*) — no charge compensation is needed. "
                f"All energies for this site are fully reliable."
            )
        elif mismatch < 0:
            charge_info = (
                f"**Charge balance:** {dopant} carries less positive charge than {target} "
                f"(charge mismatch: {mismatch:+d}). "
                f"To keep the crystal electrically neutral, compensating atoms were removed "
                f"from the supercell. This is physically realistic and the energy is reliable.  \n"
                f"*Applied: {comp_desc}.*"
            )
        else:
            charge_info = (
                f"**Charge balance (approximate):** {dopant} carries more positive charge "
                f"than {target} (charge mismatch: +{mismatch}). "
                f"CHGNet cannot fully model this electrical surplus, so the formation energy "
                f"here is an estimate.  \n"
                f"*Description: {comp_desc}.*"
            )
        L += [charge_info, ""]

        # A. Formation energy
        L += [
            "#### A. Was It Energetically Favorable? (Formation Energy)",
            "",
            "> **What is formation energy?** It tells you whether the crystal 'wants' to "
            "incorporate the dopant. A negative value means energy is released (favorable, "
            "spontaneous); a positive value means energy must be supplied (less favorable). "
            "Values below +1.0 eV are considered potentially achievable.",
            "",
            _ef_plain(ef, mismatch, dopant, target),
            "",
            f"| Parameter | Value | Threshold | Result |",
            f"|-----------|-------|-----------|--------|",
            f"| Formation energy (E_f) | **{ef:+.4f} eV** | < {EF_THRESHOLD_OK:.1f} eV | "
            f"{_pass_fail(r.get('ef_pass', ef < EF_THRESHOLD_OK))} |",
            "",
        ]

        # B. Relaxed structure
        sg = r.get("relaxed_space_group", "N/A")
        cn_relax = r.get("relaxed_coordination", 6)
        mean_nn = r.get("relaxed_mean_nn_distance_A")
        nn_dists = r.get("relaxed_nn_distances_A", [])

        L += [
            "#### B. Crystal Structure After Relaxation",
            "",
            "> **What is relaxation?** After placing the dopant, the simulation lets all "
            "surrounding atoms shift to find the lowest-energy arrangement. This section "
            "shows the stable structure after that adjustment.",
            "",
            f"- **Space group:** `{sg}`  ",
            f"  *(Describes the crystal's 3-D symmetry pattern. Deviations from the pristine "
            f"symmetry indicate structural distortion around the dopant.)*",
            f"- **Coordination number:** {cn_relax}  ",
            f"  *(Number of oxygen atoms directly bonded to the dopant. "
            f"In undoped {host_formula}, {target} atoms typically have 6 such neighbors.)*",
        ]
        if mean_nn is not None:
            L.append(f"- **Average dopant–O bond length:** {mean_nn:.4f} Å")
        if nn_dists:
            dist_str = ", ".join(f"{d:.3f}" for d in nn_dists)
            L.append(f"- **All dopant–O bond lengths:** {dist_str} Å")
        L.append("")

        # C. Molecular dynamics
        msd_slope = r.get("md_msd_slope_A2_per_ps")
        if msd_slope is not None:
            temp_k = r.get("md_temperature_K", temperature_K)
            temp_c_r = temp_k - 273.15
            duration = r.get("md_duration_ps", 0)
            msd_final = r.get("md_msd_final_A2", 0)
            max_disp = r.get("md_max_displacement_A", 0)
            cn_min = r.get("md_coordination_min", 0)
            cn_max = r.get("md_coordination_max", 0)
            cn_mean = r.get("md_coordination_mean", 0.0)
            md_nn = r.get("md_mean_nn_distance_A", 0.0)
            vol_chg = r.get("md_volume_change_pct", 0.0)
            md_sg = r.get("md_space_group", "N/A")
            msd_thr = r.get("msd_threshold_A2_per_ps", MSD_PLATEAU_SLOPE)
            msd_se = r.get("md_msd_slope_stderr_A2_per_ps")
            slope_cell = f"**{msd_slope:.5f} Å²/ps**"
            if msd_se is not None:
                slope_cell += f" ± {msd_se:.5f}"

            L += [
                f"#### C. Thermal Stability at {temp_c_r:.0f}°C (Molecular Dynamics)",
                "",
                f"> **What is molecular dynamics (MD)?** We simulate atomic vibrations "
                f"for {duration:.0f} picoseconds at {temp_c_r:.0f}°C to test whether the dopant "
                f"stays in place and whether the crystal survives operating conditions. "
                f"One picosecond = one trillionth of a second (10⁻¹² s).",
                "",
                "**Dopant mobility (Mean Squared Displacement — MSD):**",
                "",
                _msd_plain(msd_slope, msd_final, max_disp, msd_thr),
                "",
                f"| Metric | Value | Threshold | Result |",
                f"|--------|-------|-----------|--------|",
                f"| MSD slope | {slope_cell} | < {msd_thr:.5f} Å²/ps | "
                f"{_pass_fail(r.get('msd_pass', msd_slope < msd_thr))} |",
                f"| Max displacement | **{max_disp:.3f} Å** | reference only | — |",
                f"| Final MSD | **{msd_final:.4f} Å²** | reference only | — |",
                "",
                "**Local bonding environment during MD:**",
                "",
                _coordination_plain(cn_min, cn_max, cn_mean, cn_relax if isinstance(cn_relax, int) else 6, md_nn),
                "",
                f"| Metric | Value | Threshold | Result |",
                f"|--------|-------|-----------|--------|",
                f"| Coordination range | **{cn_min}–{cn_max}** (mean {cn_mean:.1f}) | "
                f"relaxed = {cn_relax} | informational |",
                f"| Avg bond length (MD) | **{md_nn:.3f} Å** | reference only | — |",
                "",
                "**Crystal volume stability:**",
                "",
                _volume_plain(vol_chg),
                "",
                f"| Metric | Value | Threshold | Result |",
                f"|--------|-------|-----------|--------|",
                f"| Volume change | **{vol_chg:+.2f}%** | ±{VOLUME_TOLERANCE_PCT:.0f}% | "
                f"{_pass_fail(r.get('lattice_pass', abs(vol_chg) < VOLUME_TOLERANCE_PCT))} |",
                f"| Space group (MD) | `{md_sg}` | reference only | — |",
                "",
            ]
        else:
            L += [
                "#### C. Thermal Stability Simulation",
                "",
                "> *Molecular dynamics was not run for this configuration. Only the "
                "formation energy (thermodynamic feasibility) has been assessed.*",
                "",
            ]

        # D. Verdict
        L += [
            "#### D. What Does This Mean? (Verdict)",
            "",
            _verdict_plain(r),
            "",
        ]

        # Notes
        notes = [n for n in r.get("notes", []) if not n.startswith("Analysis outputs")]
        if notes:
            L += ["**Simulation notes:**", ""]
            for n in notes:
                L.append(f"- {n}")
            L.append("")

        L += ["---", ""]

    # ── Section 4: Glossary ───────────────────────────────────────────────────
    L += [
        "## 4. Glossary of Key Terms",
        "",
        "| Term | Plain-English Definition |",
        "|------|------------------------|",
        "| **Dopant** | An atom of a different element intentionally inserted into a crystal to modify its properties. |",
        "| **Host material** | The original crystal being modified. |",
        f"| **{host_formula}** | The layered oxide cathode material studied here, used in rechargeable batteries. |",
        "| **Formation energy (E_f)** | Energy released (negative) or required (positive) to insert the dopant into the host. Unit: eV (electronvolts). |",
        "| **eV (electronvolt)** | A tiny unit of energy. Bond energies in materials are typically a few eV. 1 eV ≈ 96 kJ/mol. |",
        "| **Å (Angstrom)** | Unit of length equal to 10⁻¹⁰ m (one ten-billionth of a meter). Atomic bond lengths are 1–3 Å. |",
        "| **Relaxation** | Letting the simulation find the lowest-energy atomic arrangement after placing the dopant. |",
        "| **Space group** | A label describing the 3-D symmetry of a crystal. Changes indicate structural distortion. |",
        "| **Coordination number** | Number of nearest-neighbor atoms (usually oxygen) bonded to the dopant. |",
        "| **Molecular dynamics (MD)** | Simulation of atomic motion at a given temperature over a short time period. |",
        "| **MSD (Mean Squared Displacement)** | Measures how far the dopant moved on average during MD. Flat curve = stable; rising curve = migrating. |",
        "| **MSD slope** | How fast the MSD grows over time. Near-zero = dopant stays put; large = dopant is diffusing. |",
        "| **Isovalent substitution** | Replacing an atom with one of the same electric charge — simplest, most reliable case. |",
        "| **Charge compensation** | Adding/removing other atoms to keep the crystal electrically neutral when the dopant has a different charge. |",
        "| **CHGNet** | The machine-learning interatomic potential driving the simulations in this workflow. |",
        "",
        "---",
        "",
    ]

    # ── Section 5: Limitations ────────────────────────────────────────────────
    L += [
        "## 5. Important Limitations and Caveats",
        "",
        "These simulations are powerful tools, but they have known limitations. "
        "Always consider these when drawing conclusions:",
        "",
        "1. **CHGNet is charge-neutral.** The model treats all atoms as electrically neutral, "
        "so charge-transfer effects for aliovalent dopants (different oxidation state) are not "
        "fully captured. Formation energies for such dopants are approximate.",
        "",
        "2. **No electrostatic image correction.** In periodic simulations, charged defects "
        "interact with their own periodic copies. The Freysoldt/Kumagai correction that fixes "
        "this error is not applied — relevant mainly for highly charged dopants in small cells.",
        "",
        "3. **Metal-rich reference state.** Chemical potential references assume metal-rich "
        "conditions. Under realistic (oxygen-rich) synthesis conditions, formation energies "
        "can shift by several tenths of an eV.",
        "",
        "4. **Short simulation time.** MD covers ~25 picoseconds — orders of magnitude less "
        "than real battery operation (hours to thousands of hours). Very slow diffusion or "
        "gradual phase transitions are invisible at this timescale.",
        "",
        "5. **Machine-learning accuracy.** CHGNet has a typical energy error of 50–150 meV/atom "
        "compared to DFT. Formation energies with |E_f| < ~0.2 eV could change sign with "
        "higher-accuracy methods — treat near-zero results with extra caution.",
        "",
        "---",
        "",
        f"*This report was generated automatically by the CHGNet doping stability workflow.*  ",
        f"*Host: {host_formula} | Dopant: {dopant} | "
        f"Temperature: {temperature_C:.0f}°C | Sites tested: {len(reports)}*",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(L), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Called from run_workflow.py
# ---------------------------------------------------------------------------

def generate_md_for_run(
    reports_list,
    reports_dir: str,
    host_formula: str,
    dopant: str,
    temperature_C: float = 250.0,
) -> Path:
    """Called from run_workflow.run() after all tests complete."""
    from report import run_report_stem
    stem = run_report_stem(host_formula, dopant)
    out = Path(reports_dir) / f"{stem}_report.md"
    dicts = [r.to_dict() for r in reports_list]
    return generate_md(dicts, out, host_formula=host_formula, dopant=dopant, temperature_C=temperature_C)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _load_reports(paths: list[Path]) -> list[dict]:
    reports = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                if "summary" not in f.name and "final" not in f.name:
                    reports.append(json.loads(f.read_text(encoding="utf-8")))
        else:
            data = json.loads(p.read_text(encoding="utf-8"))
            # _final.json files contain a "reports" list of per-site dicts
            if "reports" in data and isinstance(data["reports"], list):
                reports.extend(data["reports"])
            else:
                reports.append(data)
    return reports


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_md_report.py <report.json|dir> [...]")
        sys.exit(1)

    paths = [Path(a) for a in sys.argv[1:]]
    rpts = _load_reports(paths)
    if not rpts:
        print("No report JSON files found.")
        sys.exit(1)

    host = rpts[0].get("host_formula", "Unknown")
    dop = rpts[0].get("dopant", "Unknown")
    temp_c = (rpts[0].get("md_temperature_K") or 523.15) - 273.15
    out = paths[0] if paths[0].is_dir() else paths[0].parent
    out = out / f"{host}_{dop}_report.md"
    result = generate_md(rpts, out, host_formula=host, dopant=dop, temperature_C=temp_c)
    print(f"Markdown report written -> {result}")
