# Doping Stability Report: Mn in NaCoO2

*Generated: May 30, 2026 at 10:33 AM*  
*Simulation temperature: 300°C (573.1 K)*  
*Total configurations tested: 2*

---

## 1. What Is This Study Testing?

This study investigates whether **Mn** (the *dopant*) can be stably inserted into the crystal structure of **NaCoO2** (the *host material*) by replacing one of the **Co and Na** atoms already present in the crystal. This process is called *doping*.

**Why does this matter?**

Battery cathode materials like NaCoO2 can sometimes be improved by substituting a fraction of their atoms with a different element. However, not every dopant is stable — some are thermodynamically unfavorable, and some cause the crystal structure to deteriorate during battery operation at elevated temperatures. This simulation workflow tests both aspects:

1. **Thermodynamic feasibility** — Is it energetically favorable to place Mn into the crystal? (Formation energy test)
2. **Thermal stability** — Does the crystal remain intact when heated to 300°C? (Molecular dynamics simulation)

---

## 2. Quick Summary of Results

**Mn strongly prefers to occupy the Co layer**, with a formation energy 6.621 eV lower than the Na layer. Put simply: the material 'wants' the dopant on the Co site much more than the Na site. The MD results reinforce this: dopant movement on the Co site was -0.00307 Å²/ps (stable) vs 0.00922 Å²/ps on the Na site. The Co-site result is the most reliable because there is no charge mismatch — the dopant carries the same oxidation state as the atom it replaced, so the energy calculation is fully accurate. The Na-site energy is approximate (charge surplus of +2 cannot be fully modelled in CHGNet).

| Site # | Target Layer | Formation Energy | Thermodynamic? | Thermal Stability | Verdict |
|--------|-------------|-----------------|---------------|-------------------|---------|
| 24 | Co | -2.098 eV | ✅ Favorable | ✅ Stable | ✅ STABLE |
| 0 | Na | +4.523 eV | ❌ Unfavorable | ❌ Migrating | ✅ STABLE |

**Best overall:** Site 24 (Co layer) — E_f = -2.098 eV, verdict: **STABLE**

---

## 3. Detailed Results

> *Each subsection below describes one tested atomic configuration in detail.*

### 3.1  Site 24: Mn replacing Co

**Overall verdict: ✅ **STABLE****

**Charge balance:** Mn and Co have the same oxidation state (*isovalent substitution*) — no charge compensation is needed. All energies for this site are fully reliable.

#### A. Was It Energetically Favorable? (Formation Energy)

> **What is formation energy?** It tells you whether the crystal 'wants' to incorporate the dopant. A negative value means energy is released (favorable, spontaneous); a positive value means energy must be supplied (less favorable). Values below +1.0 eV are considered potentially achievable.

The formation energy is **-2.098 eV** — strongly negative. Placing Mn on the Co site releases energy, so the process happens spontaneously under normal conditions. The material is very likely to accept this dopant.

| Parameter | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| Formation energy (E_f) | **-2.0981 eV** | < 1.0 eV | ✅ PASS |

#### B. Crystal Structure After Relaxation

> **What is relaxation?** After placing the dopant, the simulation lets all surrounding atoms shift to find the lowest-energy arrangement. This section shows the stable structure after that adjustment.

- **Space group:** `P-3m1 (164)`  
  *(Describes the crystal's 3-D symmetry pattern. Deviations from the pristine symmetry indicate structural distortion around the dopant.)*
- **Coordination number:** 6  
  *(Number of oxygen atoms directly bonded to the dopant. In undoped NaCoO2, Co atoms typically have 6 such neighbors.)*
- **Average dopant–O bond length:** 1.9221 Å
- **All dopant–O bond lengths:** 1.921, 1.921, 1.921, 1.923, 1.923, 1.923 Å

#### C. Thermal Stability at 300°C (Molecular Dynamics)

> **What is molecular dynamics (MD)?** We simulate atomic vibrations for 25 picoseconds at 300°C to test whether the dopant stays in place and whether the crystal survives operating conditions. One picosecond = one trillionth of a second (10⁻¹² s).

**Dopant mobility (Mean Squared Displacement — MSD):**

An MSD slope this close to zero (-0.00307 Å²/ps) means the dopant was essentially locked in place — it barely moved at all during the simulation. The farthest the dopant moved from its starting position was **1.04 Å** (about 2.0 times the Bohr radius), with a final mean-squared displacement of **0.071 Å²**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| MSD slope | **-0.00307 Å²/ps** | < 0.005 Å²/ps | ✅ PASS |
| Max displacement | **1.044 Å** | reference only | — |
| Final MSD | **0.0706 Å²** | reference only | — |

**Local bonding environment during MD:**

The dopant had exactly **6 neighboring oxygen atoms** throughout the entire simulation — the same number as right after relaxation. The local bonding environment was perfectly preserved. The average dopant–oxygen bond length during the simulation was **1.938 Å**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Coordination range | **6–6** (mean 6.0) | within ±1 of 6 | ✅ PASS |
| Avg bond length (MD) | **1.938 Å** | reference only | — |

**Crystal volume stability:**

The crystal's volume changed by only **+0.00%** — essentially no change. The host lattice is mechanically stable with this dopant.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Volume change | **+0.00%** | ±5% | ✅ PASS |
| Space group (MD) | `P1 (1)` | reference only | — |

#### D. What Does This Mean? (Verdict)

**Mn is a strong candidate for the Co site.** All four stability tests passed: the formation energy is thermodynamically favorable, the dopant does not migrate at 300°C, its local atomic environment is preserved during heating, and the host crystal does not expand or contract excessively. This result supports further experimental investigation.

**Simulation notes:**

- Symmetric multiplicity: 24

---

### 3.2  Site 0: Mn replacing Na

**Overall verdict: ✅ **UNSTABLE (migration + structural distortion)****

**Charge balance (approximate):** Mn carries more positive charge than Na (charge mismatch: +2). CHGNet cannot fully model this electrical surplus, so the formation energy here is an estimate.  
*Description: aliovalent (mismatch +2): charge surplus cannot be modelled in CHGNet — running uncompensated single substitution (E_f approximate).*

#### A. Was It Energetically Favorable? (Formation Energy)

> **What is formation energy?** It tells you whether the crystal 'wants' to incorporate the dopant. A negative value means energy is released (favorable, spontaneous); a positive value means energy must be supplied (less favorable). Values below +1.0 eV are considered potentially achievable.

The formation energy is **+4.523 eV** — large and positive. A significant amount of energy is required to place Mn at the Na site. Under most synthesis conditions this dopant configuration would not form.

> **Note on accuracy:** This formation energy is approximate. The dopant carries a different electric charge than the atom it replaced, and the simulation model (CHGNet) cannot fully account for that electrical imbalance. Treat this value as an estimate rather than an exact number.

| Parameter | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| Formation energy (E_f) | **+4.5229 eV** | < 1.0 eV | ❌ FAIL |

#### B. Crystal Structure After Relaxation

> **What is relaxation?** After placing the dopant, the simulation lets all surrounding atoms shift to find the lowest-energy arrangement. This section shows the stable structure after that adjustment.

- **Space group:** `C2/m (12)`  
  *(Describes the crystal's 3-D symmetry pattern. Deviations from the pristine symmetry indicate structural distortion around the dopant.)*
- **Coordination number:** 6  
  *(Number of oxygen atoms directly bonded to the dopant. In undoped NaCoO2, Na atoms typically have 6 such neighbors.)*
- **Average dopant–O bond length:** 2.2049 Å
- **All dopant–O bond lengths:** 2.205, 2.205, 2.205, 2.205, 2.205, 2.205 Å

#### C. Thermal Stability at 300°C (Molecular Dynamics)

> **What is molecular dynamics (MD)?** We simulate atomic vibrations for 25 picoseconds at 300°C to test whether the dopant stays in place and whether the crystal survives operating conditions. One picosecond = one trillionth of a second (10⁻¹² s).

**Dopant mobility (Mean Squared Displacement — MSD):**

The MSD slope (0.00922 Å²/ps) exceeds the stability threshold of 0.005 Å²/ps, suggesting the dopant drifted slightly or hopped between nearby atomic sites. The farthest the dopant moved from its starting position was **2.06 Å** (about 3.9 times the Bohr radius), with a final mean-squared displacement of **2.482 Å²**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| MSD slope | **0.00922 Å²/ps** | < 0.005 Å²/ps | ❌ FAIL |
| Max displacement | **2.061 Å** | reference only | — |
| Final MSD | **2.4823 Å²** | reference only | — |

**Local bonding environment during MD:**

The coordination number ranged from **4 to 7** (average: 5.8), deviating significantly from the relaxed value of 6. This indicates the local structure around the dopant changed during heating, which may signal structural distortion. The average dopant–oxygen bond length during the simulation was **2.191 Å**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Coordination range | **4–7** (mean 5.8) | within ±1 of 6 | ❌ FAIL |
| Avg bond length (MD) | **2.191 Å** | reference only | — |

**Crystal volume stability:**

The crystal's volume changed by only **+0.00%** — essentially no change. The host lattice is mechanically stable with this dopant.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Volume change | **+0.00%** | ±5% | ✅ PASS |
| Space group (MD) | `P1 (1)` | reference only | — |

#### D. What Does This Mean? (Verdict)

Verdict: UNSTABLE (migration + structural distortion).

**Simulation notes:**

- Symmetric multiplicity: 24

---

## 4. Glossary of Key Terms

| Term | Plain-English Definition |
|------|------------------------|
| **Dopant** | An atom of a different element intentionally inserted into a crystal to modify its properties. |
| **Host material** | The original crystal being modified. |
| **NaCoO2** | The layered oxide cathode material studied here, used in rechargeable batteries. |
| **Formation energy (E_f)** | Energy released (negative) or required (positive) to insert the dopant into the host. Unit: eV (electronvolts). |
| **eV (electronvolt)** | A tiny unit of energy. Bond energies in materials are typically a few eV. 1 eV ≈ 96 kJ/mol. |
| **Å (Angstrom)** | Unit of length equal to 10⁻¹⁰ m (one ten-billionth of a meter). Atomic bond lengths are 1–3 Å. |
| **Relaxation** | Letting the simulation find the lowest-energy atomic arrangement after placing the dopant. |
| **Space group** | A label describing the 3-D symmetry of a crystal. Changes indicate structural distortion. |
| **Coordination number** | Number of nearest-neighbor atoms (usually oxygen) bonded to the dopant. |
| **Molecular dynamics (MD)** | Simulation of atomic motion at a given temperature over a short time period. |
| **MSD (Mean Squared Displacement)** | Measures how far the dopant moved on average during MD. Flat curve = stable; rising curve = migrating. |
| **MSD slope** | How fast the MSD grows over time. Near-zero = dopant stays put; large = dopant is diffusing. |
| **Isovalent substitution** | Replacing an atom with one of the same electric charge — simplest, most reliable case. |
| **Charge compensation** | Adding/removing other atoms to keep the crystal electrically neutral when the dopant has a different charge. |
| **CHGNet** | The machine-learning interatomic potential driving the simulations in this workflow. |

---

## 5. Important Limitations and Caveats

These simulations are powerful tools, but they have known limitations. Always consider these when drawing conclusions:

1. **CHGNet is charge-neutral.** The model treats all atoms as electrically neutral, so charge-transfer effects for aliovalent dopants (different oxidation state) are not fully captured. Formation energies for such dopants are approximate.

2. **No electrostatic image correction.** In periodic simulations, charged defects interact with their own periodic copies. The Freysoldt/Kumagai correction that fixes this error is not applied — relevant mainly for highly charged dopants in small cells.

3. **Metal-rich reference state.** Chemical potential references assume metal-rich conditions. Under realistic (oxygen-rich) synthesis conditions, formation energies can shift by several tenths of an eV.

4. **Short simulation time.** MD covers ~25 picoseconds — orders of magnitude less than real battery operation (hours to thousands of hours). Very slow diffusion or gradual phase transitions are invisible at this timescale.

5. **Machine-learning accuracy.** CHGNet has a typical energy error of 50–150 meV/atom compared to DFT. Formation energies with |E_f| < ~0.2 eV could change sign with higher-accuracy methods — treat near-zero results with extra caution.

---

*This report was generated automatically by the CHGNet doping stability workflow.*  
*Host: NaCoO2 | Dopant: Mn | Temperature: 300°C | Sites tested: 2*