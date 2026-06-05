"""
Phase 7 - Natural-language PDF report generator.

Converts the JSON stability reports produced after each test run into a
human-readable PDF document. The PDF mirrors the narrative explanations
shown in the terminal: every number is accompanied by a sentence saying
what it means, not just what it is.

Requires fpdf2:
    pip install fpdf2

Called automatically at the end of run_workflow.run(), and also usable
as a standalone script:

    python generate_pdf_report.py reports/Mn@Co_site24.json reports/Mn@Na_site0.json
    python generate_pdf_report.py reports/          # reads all .json in folder
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from fpdf import FPDF

# ---------------------------------------------------------------------------
# Unicode → ASCII sanitizer
# Helvetica is a core PDF font that only covers Latin-1. Any Unicode character
# outside that range (em-dash, curly quotes, etc.) raises a character-range
# error. Replace common offenders with plain ASCII equivalents before any text
# is passed to fpdf.
# ---------------------------------------------------------------------------

def _safe(text: str) -> str:
    return (
        str(text)
        .replace("—", "--")   # em dash —
        .replace("–", "-")    # en dash –
        .replace("’", "'")    # right single quotation mark '
        .replace("‘", "'")    # left single quotation mark '
        .replace("“", '"')    # left double quotation mark "
        .replace("”", '"')    # right double quotation mark "
        .replace("²", "^2")   # superscript 2  ²
        .replace("°", " deg") # degree sign °
        .replace("μ", "u")    # mu µ
        .replace("→", "->")   # arrow →
        .replace("é", "e")    # é
        .replace("è", "e")    # è
        .replace("à", "a")    # à
        .encode("latin-1", errors="replace").decode("latin-1")
    )


# ---------------------------------------------------------------------------
# Thresholds — must match report.py
# ---------------------------------------------------------------------------
EF_THRESHOLD_OK = 1.0
MSD_PLATEAU_SLOPE = 0.005
VOLUME_TOLERANCE_PCT = 5.0

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
GREEN = (0, 140, 0)
RED = (190, 0, 0)
ORANGE = (200, 110, 0)
BLACK = (0, 0, 0)
DARK_GRAY = (60, 60, 60)
LIGHT_GRAY = (240, 240, 240)
MID_GRAY = (180, 180, 180)
BLUE = (30, 90, 180)


# ---------------------------------------------------------------------------
# Narrative helpers
# ---------------------------------------------------------------------------

def _ef_narrative(ef: float, mismatch: int, dopant: str, target: str) -> str:
    approx = " (approximate — charge surplus not modelled in CHGNet)" if mismatch > 0 else ""
    if ef < -3.0:
        quality = "exceptionally large and negative"
        meaning = "incorporation is strongly thermodynamically driven"
    elif ef < -1.0:
        quality = "strongly negative"
        meaning = "incorporation is thermodynamically very favorable"
    elif ef < 0:
        quality = "slightly negative"
        meaning = "incorporation is thermodynamically favorable"
    elif ef < 0.5:
        quality = "small and positive"
        meaning = "incorporation is marginally feasible under equilibrium conditions"
    elif ef < 1.0:
        quality = "moderately positive"
        meaning = "incorporation is possible but endothermic; may require non-equilibrium synthesis"
    else:
        quality = "large and positive"
        meaning = "incorporation is thermodynamically unfavorable under equilibrium conditions"
    return (
        f"E_f = {ef:+.3f} eV{approx}. This value is {quality}, indicating that {dopant} "
        f"{meaning} at the {target} site."
    )


def _msd_narrative(slope: float, final: float, max_disp: float,
                   threshold: float = MSD_PLATEAU_SLOPE) -> str:
    if slope < 0:
        mobility = "The negative slope is a flat plateau — essentially no migration detected."
    elif slope < 0.2 * threshold:
        mobility = "The slope is near zero, confirming the dopant is tightly confined to its site."
    elif slope < threshold:
        mobility = ("The slope sits within the thermal-fluctuation margin of error for this run "
                    "(below the noise-calibrated cutoff) — the dopant is site-stable.")
    elif slope < 4 * threshold:
        mobility = "The slope exceeds the migration cutoff, suggesting mild drift or site-hopping."
    else:
        mobility = "The large slope indicates significant diffusion — the dopant is migrating."

    return (
        f"Late-time MSD slope = {slope:.5f} A²/ps. {mobility} "
        f"Final MSD = {final:.3f} A²; maximum displacement from starting position = {max_disp:.2f} A."
    )


def _coordination_narrative(
    cn_min: int, cn_max: int, cn_mean: float, cn_relaxed: int, mean_bond: float
) -> str:
    if cn_min == cn_max == cn_relaxed:
        stability = (
            f"Coordination was exactly {cn_relaxed} throughout the entire trajectory — "
            "the dopant held its local environment rigidly."
        )
    else:
        stability = (
            f"Coordination fluctuated between {cn_min} and {cn_max} (mean {cn_mean:.1f}) "
            f"versus the relaxed value of {cn_relaxed}. The first-shell count is sensitive "
            "to the bond-length cutoff, so it is reported for context only and does not "
            "affect the verdict."
        )
    return f"{stability} Mean nearest-neighbour distance during MD = {mean_bond:.3f} A."


def _volume_narrative(dv: float) -> str:
    if abs(dv) < 1.0:
        return f"Volume change = {dv:+.2f}%. The host lattice is mechanically intact."
    if abs(dv) < VOLUME_TOLERANCE_PCT:
        return (
            f"Volume change = {dv:+.2f}%. Moderate expansion/contraction, within the "
            f"+/-{VOLUME_TOLERANCE_PCT}% tolerance."
        )
    return (
        f"Volume change = {dv:+.2f}%, exceeding the +/-{VOLUME_TOLERANCE_PCT}% tolerance. "
        "This signals mechanical instability of the doped phase at this temperature."
    )


def _verdict_narrative(report: dict) -> str:
    verdict = report["verdict"]
    dopant = report["dopant"]
    target = report["target_site_element"]
    temp_c = (report.get("md_temperature_K") or 523.15) - 273.15
    mismatch = report.get("charge_mismatch", 0) or 0

    if verdict == "STABLE":
        return (
            f"{dopant} is thermodynamically favorable and kinetically stable on the "
            f"{target} site at {temp_c:.0f} C. All stability criteria pass: formation "
            f"energy is favorable, the dopant does not migrate during MD, and the host "
            f"lattice volume is unchanged."
        )
    if verdict == "METASTABLE":
        return (
            f"{dopant} sits stably on the {target} site during MD at {temp_c:.0f} C, "
            f"but the formation energy exceeds the 1.0 eV equilibrium threshold. This "
            f"configuration is metastable — it may be achievable via non-equilibrium "
            f"synthesis routes such as ion exchange or rapid quenching."
        )
    if verdict.startswith("MIGRATION"):
        return (
            f"The formation energy is favorable but {dopant} migrates away from the "
            f"{target} site during MD. The relaxed structure is not the true resting site. "
            f"Inspect the MSD and trajectory to identify where the dopant ends up."
        )
    if verdict == "STRUCTURAL COLLAPSE":
        return (
            f"The doped structure shows signs of mechanical instability at {temp_c:.0f} C: "
            f"the host lattice volume changed beyond the +/-{VOLUME_TOLERANCE_PCT:.0f}% tolerance. "
            f"This dopant-site combination may not be stable at this temperature."
        )
    if "FAVORABLE" in verdict:
        return (
            f"Formation energy passes ({report.get('formation_energy_eV', 0):+.3f} eV). "
            f"MD was not run for this configuration — run with run_md=True to complete the stability assessment."
        )
    if "UNFAVORABLE" in verdict:
        return (
            f"Formation energy is unfavorable ({report.get('formation_energy_eV', 0):+.3f} eV). "
            f"{dopant} is unlikely to incorporate at the {target} site under equilibrium conditions."
        )
    return f"Verdict: {verdict}. Refer to the individual criteria above."


def _site_preference_conclusion(reports: list[dict]) -> str:
    if len(reports) < 2:
        return ""
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
    winner_md = winner.get("md_msd_slope_A2_per_ps")
    runner_md = runner.get("md_msd_slope_A2_per_ps")

    lines = [
        f"{dopant} preferentially occupies the {winner['target_site_element']} layer. "
        f"The formation energy difference between the two layers is {delta:+.3f} eV, "
        f"strongly favouring the {winner['target_site_element']} site."
    ]
    if winner_md is not None:
        lines.append(
            f"MD confirms this preference: on the {winner['target_site_element']} site "
            f"the dopant MSD plateau slope is {winner_md:.5f} A²/ps (stable), "
        )
        if runner_md is not None:
            lines.append(
                f"compared to {runner_md:.5f} A²/ps on the {runner['target_site_element']} site."
            )
    if winner.get("charge_mismatch", 0) == 0:
        lines.append(
            f"The {winner['target_site_element']}-site result is isovalent (no charge mismatch), "
            f"so the formation energy is fully reliable."
        )
    if (runner.get("charge_mismatch") or 0) > 0:
        lines.append(
            f"The {runner['target_site_element']}-site E_f is approximate due to a charge surplus "
            f"of +{runner['charge_mismatch']} that cannot be modelled in CHGNet."
        )
    return " ".join(lines)


# ---------------------------------------------------------------------------
# PDF layout class
# ---------------------------------------------------------------------------

class ReportPDF(FPDF):
    def __init__(self, title: str):
        super().__init__()
        self._doc_title = _safe(title)
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(left=20, top=20, right=20)

    def cell(self, w=0, h=0, txt="", *args, **kwargs):
        super().cell(w, h, _safe(txt), *args, **kwargs)

    def multi_cell(self, w, h, txt="", *args, **kwargs):
        super().multi_cell(w, h, _safe(txt), *args, **kwargs)

    def header(self):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*DARK_GRAY)
        self.cell(0, 6, self._doc_title, align="L")
        self.ln(1)
        self.set_draw_color(*MID_GRAY)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(4)
        self.set_text_color(*BLACK)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*DARK_GRAY)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")
        self.set_text_color(*BLACK)

    def section_title(self, text: str, color=BLUE):
        self.ln(3)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(*color)
        self.cell(0, 8, text, ln=True)
        self.set_draw_color(*color)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)
        self.set_text_color(*BLACK)
        self.set_draw_color(*BLACK)

    def sub_title(self, text: str):
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*DARK_GRAY)
        self.cell(0, 6, text, ln=True)
        self.ln(1)
        self.set_text_color(*BLACK)

    def body(self, text: str, indent: int = 0):
        self.set_font("Helvetica", "", 10)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def verdict_box(self, verdict: str):
        if "STABLE" in verdict and "METASTABLE" not in verdict:
            color = GREEN
        elif "METASTABLE" in verdict:
            color = ORANGE
        elif "COLLAPSE" in verdict or "UNSTABLE" in verdict or "UNFAVORABLE" in verdict:
            color = RED
        elif "MIGRATION" in verdict:
            color = ORANGE
        else:
            color = DARK_GRAY

        self.ln(2)
        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 12)
        self.cell(0, 9, f"  VERDICT:  {verdict}", fill=True, ln=True)
        self.set_text_color(*BLACK)
        self.ln(3)

    def metric_row(self, label: str, value: str, passed: bool | None, note: str = ""):
        """One row in a metrics table."""
        # background
        self.set_fill_color(*LIGHT_GRAY)
        col_w = [68, 35, 18, 0]   # label, value, tag, rest
        full_w = self.w - self.l_margin - self.r_margin

        # label
        self.set_font("Helvetica", "", 10)
        self.set_text_color(*BLACK)
        self.cell(col_w[0], 6.5, f"  {label}", border="LTB", fill=True)

        # value
        self.set_font("Helvetica", "B", 10)
        self.cell(col_w[1], 6.5, value, border="TB", fill=True)

        # pass/fail tag
        if passed is True:
            self.set_fill_color(*GREEN)
            self.set_text_color(255, 255, 255)
            tag = "PASS"
        elif passed is False:
            self.set_fill_color(*RED)
            self.set_text_color(255, 255, 255)
            tag = "FAIL"
        else:
            self.set_fill_color(*MID_GRAY)
            self.set_text_color(255, 255, 255)
            tag = "----"
        self.set_font("Helvetica", "B", 8)
        self.cell(col_w[2], 6.5, f" {tag}", border="TB", fill=True)

        # note
        self.set_fill_color(*LIGHT_GRAY)
        self.set_text_color(*DARK_GRAY)
        self.set_font("Helvetica", "I", 9)
        note_w = full_w - sum(col_w[:3])
        self.cell(note_w, 6.5, f"  {note}", border="RTB", fill=True, ln=True)

        self.set_text_color(*BLACK)
        self.set_fill_color(255, 255, 255)

    def comparison_table(self, headers: list[str], rows: list[list[str]]):
        col_w = 170 // len(headers)
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(*BLUE)
        self.set_text_color(255, 255, 255)
        for h in headers:
            self.cell(col_w, 7, f" {h}", border=1, fill=True)
        self.ln()
        self.set_text_color(*BLACK)
        for i, row in enumerate(rows):
            self.set_fill_color(*LIGHT_GRAY if i % 2 == 0 else (255, 255, 255))
            self.set_font("Helvetica", "", 9)
            for cell in row:
                self.cell(col_w, 6.5, f" {cell}", border=1,
                          fill=(i % 2 == 0))
            self.ln()
        self.set_fill_color(255, 255, 255)
        self.ln(3)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def _pass_label(passed: bool | None) -> str:
    if passed is True:
        return "PASS"
    if passed is False:
        return "FAIL"
    return "n/a"


def generate_pdf(
    reports: list[dict],
    output_path: str | Path,
    host_formula: str = "",
    dopant: str = "",
    temperature_C: float = 250.0,
) -> Path:
    """Build and save the PDF. Returns the output path."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    host = host_formula or (reports[0].get("host_formula", "Unknown") if reports else "Unknown")
    dop = dopant or (reports[0].get("dopant", "Unknown") if reports else "Unknown")
    title = f"Doping Stability Report — {dop} in {host} at {temperature_C:.0f} C"

    pdf = ReportPDF(title)
    pdf.add_page()

    # -----------------------------------------------------------------------
    # Title block
    # -----------------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*BLUE)
    pdf.cell(0, 12, title, ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*DARK_GRAY)
    pdf.cell(0, 6, f"Generated: {now}    Host: {host}    Dopant: {dop}", ln=True)
    pdf.set_text_color(*BLACK)
    pdf.ln(4)

    # -----------------------------------------------------------------------
    # Executive summary
    # -----------------------------------------------------------------------
    pdf.section_title("Executive Summary")
    conclusion = _site_preference_conclusion(reports)
    if conclusion:
        pdf.body(conclusion)
    else:
        # single-site summary
        r = reports[0]
        pdf.body(f"This report presents the stability assessment for {dop} "
                 f"substituting at the {r['target_site_element']} site in {host} "
                 f"at {temperature_C:.0f} C.  Overall verdict: {r['verdict']}.")

    # Summary table across all sites
    if len(reports) > 1:
        pdf.ln(2)
        headers = ["Site", "E_f (eV)", "Charge", "Compensation", "MSD pass", "Verdict"]
        rows = []
        for r in sorted(reports, key=lambda x: x["formation_energy_eV"]):
            mismatch = r.get("charge_mismatch") or 0
            rows.append([
                r["target_site_element"],
                f"{r['formation_energy_eV']:+.3f}",
                f"{mismatch:+d}",
                "Yes" if r.get("compensation_applied") else "No",
                _pass_label(r.get("msd_pass")),
                r["verdict"],
            ])
        pdf.comparison_table(headers, rows)

    # -----------------------------------------------------------------------
    # Per-site detailed sections
    # -----------------------------------------------------------------------
    for r in reports:
        target = r["target_site_element"]
        mismatch = r.get("charge_mismatch") or 0
        ef = r["formation_energy_eV"]
        has_md = r.get("md_msd_slope_A2_per_ps") is not None

        pdf.section_title(
            f"{dop} at the {target} layer  —  {r['verdict']}",
            color=GREEN if r["verdict"] == "STABLE" else
                  ORANGE if r["verdict"] in ("METASTABLE",) else
                  RED,
        )

        # charge situation
        comp_desc = r.get("compensation_description", "")
        pdf.sub_title("Charge situation")
        if mismatch == 0:
            charge_text = (
                f"{dop} replaces {target} with no change in oxidation state "
                f"(isovalent substitution, charge mismatch = 0). "
                f"No charge compensation is needed. The formation energy is fully reliable."
            )
        elif mismatch < 0:
            charge_text = (
                f"{dop} replaces {target} with a charge mismatch of {mismatch:+d}. "
                f"To restore charge neutrality, {abs(mismatch)} Na atom(s) were removed "
                f"from the supercell (furthest from the dopant site). "
                f"The formation energy accounts for the Na-vacancy term."
            )
        else:
            charge_text = (
                f"{dop} replaces {target} with a charge surplus of +{mismatch}. "
                f"CHGNet cannot model this compensation (would require Co oxidation or "
                f"electron addition). The formation energy below is approximate."
            )
        pdf.body(charge_text)

        # formation energy
        pdf.sub_title("Formation Energy (thermodynamic stability)")
        pdf.metric_row(
            "Formation energy  E_f",
            f"{ef:+.4f} eV",
            r.get("ef_pass"),
            "< 1.0 eV to pass",
        )
        pdf.body(_ef_narrative(ef, mismatch, dop, target), indent=4)

        # MD metrics
        if has_md:
            temp_k = r.get("md_temperature_K", 523.15)
            dur_ps = r.get("md_duration_ps", 25.0)
            pdf.sub_title(f"Molecular Dynamics Stability  ({temp_k - 273.15:.0f} C,  {dur_ps:.0f} ps)")

            msd_slope = r["md_msd_slope_A2_per_ps"]
            msd_final = r.get("md_msd_final_A2", 0)
            max_disp = r.get("md_max_displacement_A", 0)
            cn_min = r.get("md_coordination_min")
            cn_max = r.get("md_coordination_max")
            cn_mean = r.get("md_coordination_mean")
            cn_relaxed = r.get("relaxed_coordination")
            bond_md = r.get("md_mean_nn_distance_A", 0)
            bond_relax = r.get("relaxed_mean_nn_distance_A", 0)
            dv = r.get("md_volume_change_pct", 0)
            msd_thr = r.get("msd_threshold_A2_per_ps", MSD_PLATEAU_SLOPE)
            msd_se = r.get("md_msd_slope_stderr_A2_per_ps")
            slope_val = f"{msd_slope:.5f} A²/ps"
            if msd_se is not None:
                slope_val += f" ± {msd_se:.5f}"

            pdf.metric_row(
                "MSD slope (late-time)",
                slope_val,
                r.get("msd_pass"),
                f"< {msd_thr:.5f} to pass (noise-calibrated plateau)",
            )
            pdf.metric_row(
                "Final MSD",
                f"{msd_final:.3f} A²",
                None,
                "",
            )
            pdf.metric_row(
                "Max displacement",
                f"{max_disp:.3f} A",
                None,
                "",
            )
            pdf.metric_row(
                f"Coordination (min/mean/max)",
                f"{cn_min} / {cn_mean:.1f} / {cn_max}",
                None,
                f"relaxed = {cn_relaxed}, informational only",
            )
            pdf.metric_row(
                "Mean bond length (MD vs relaxed)",
                f"{bond_md:.3f} A  (relaxed: {bond_relax:.3f} A)",
                None,
                "",
            )
            pdf.metric_row(
                "Lattice volume change",
                f"{dv:+.2f} %",
                r.get("lattice_pass"),
                "< +/-5% to pass",
            )

            pdf.body(_msd_narrative(msd_slope, msd_final, max_disp, msd_thr), indent=4)
            if cn_min is not None:
                pdf.body(_coordination_narrative(cn_min, cn_max, cn_mean, cn_relaxed, bond_md), indent=4)
            pdf.body(_volume_narrative(dv), indent=4)
        else:
            pdf.sub_title("Molecular Dynamics")
            pdf.body("MD was not run for this configuration. "
                     "Only relaxation and formation energy are available.")

        # verdict box + narrative
        pdf.verdict_box(r["verdict"])
        pdf.body(_verdict_narrative(r))

        # warnings
        for note in r.get("notes", []):
            if note.upper().startswith("WARNING"):
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(*ORANGE)
                pdf.multi_cell(0, 5, f"  ⚠  {note}")
                pdf.set_text_color(*BLACK)
                pdf.ln(1)

    # -----------------------------------------------------------------------
    # Cross-site comparison (multi-site runs only)
    # -----------------------------------------------------------------------
    if len(reports) > 1:
        pdf.section_title("Site Preference Comparison")
        target_bests: dict[str, dict] = {}
        for r in reports:
            t = r["target_site_element"]
            if t not in target_bests or r["formation_energy_eV"] < target_bests[t]["formation_energy_eV"]:
                target_bests[t] = r

        ordered = sorted(target_bests.values(), key=lambda r: r["formation_energy_eV"])
        if len(ordered) >= 2:
            delta = ordered[1]["formation_energy_eV"] - ordered[0]["formation_energy_eV"]
            winner = ordered[0]
            runner = ordered[1]
            pdf.body(
                f"The {winner['target_site_element']} site is preferred by "
                f"{delta:.3f} eV over the {runner['target_site_element']} site. "
                f"Formation energy: {winner['formation_energy_eV']:+.3f} eV ({winner['target_site_element']}) "
                f"vs {runner['formation_energy_eV']:+.3f} eV ({runner['target_site_element']})."
            )
            pdf.body(_site_preference_conclusion(reports))

    # -----------------------------------------------------------------------
    # Caveats
    # -----------------------------------------------------------------------
    pdf.section_title("Caveats and Limitations")
    caveats = [
        ("CHGNet is charge-neutral.",
         "The potential does not model oxidation states, polaron formation, or "
         "electron/hole localisation. Formation energies for aliovalent dopants "
         "(charge mismatch != 0) are approximate even when structural compensation "
         "defects are included."),
        ("No Freysoldt/Kumagai correction.",
         "Electrostatic finite-size corrections for charged defects require the host "
         "dielectric tensor and the DFT electrostatic potential, neither of which is "
         "available from a neural-network potential. For publication-quality E_f of "
         "charged defects, follow up with DFT using doped or pymatgen-analysis-defects."),
        ("Metal-rich reference state.",
         "Chemical potentials are computed from elemental ground-state structures. "
         "Synthesis under oxide-rich or other conditions shifts all E_f values by "
         "additive constants; the relative ordering of sites is unaffected."),
        ("MD timescales are short (25 ps default).",
         "This is sufficient to assess local site stability and rapid migration, "
         "but cannot resolve slow diffusion mechanisms. A non-plateauing MSD "
         "confirms instability; a plateau does not guarantee stability on longer timescales."),
        ("Energy rankings are more trustworthy than absolute values.",
         "CHGNet is a universal MLIP trained on r2SCAN DFT. Formation-energy errors "
         "for transition-metal oxides are typically 50-150 meV/atom. Use relative "
         "orderings (which site is preferred?) as the primary result."),
    ]
    for heading, text in caveats:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"▶  {heading}", ln=True)
        pdf.body(text, indent=6)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------
    pdf.output(str(output_path))
    return output_path


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def _load_reports(paths: list[Path]) -> list[dict]:
    reports = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                if "summary" not in f.name and "final" not in f.name:
                    reports.append(json.loads(f.read_text()))
        else:
            reports.append(json.loads(p.read_text()))
    return reports


def generate_pdf_for_run(reports_list, reports_dir: str, host_formula: str, dopant: str, temperature_C: float = 250.0):
    """Called from run_workflow.run() after all tests complete."""
    from report import run_report_stem
    stem = run_report_stem(host_formula, dopant)
    out = Path(reports_dir) / f"{stem}_report.pdf"
    dicts = [r.to_dict() for r in reports_list]
    path = generate_pdf(dicts, out, host_formula=host_formula, dopant=dopant, temperature_C=temperature_C)
    return path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_pdf_report.py <report.json> [report2.json ...] [reports_dir/]")
        sys.exit(1)

    paths = [Path(a) for a in sys.argv[1:]]
    rpts = _load_reports(paths)
    if not rpts:
        print("No report JSON files found.")
        sys.exit(1)

    host = rpts[0].get("host_formula", "Unknown")
    dop = rpts[0].get("dopant", "Unknown")
    out = paths[0].parent / f"{host}_{dop}_report.pdf"
    result = generate_pdf(rpts, out, host_formula=host, dopant=dop)
    print(f"PDF written -> {result}")
