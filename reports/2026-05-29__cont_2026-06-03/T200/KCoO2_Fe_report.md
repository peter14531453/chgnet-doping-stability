# Doping Stability Report: Fe in KCoO2

*Generated: May 30, 2026 at 01:12 PM*  
*Simulation temperature: 200°C (473.1 K)*  
*Total configurations tested: 2*

---

## 1. What Is This Study Testing?

This study investigates whether **Fe** (the *dopant*) can be stably inserted into the crystal structure of **KCoO2** (the *host material*) by replacing one of the **Co and K** atoms already present in the crystal. This process is called *doping*.

**Why does this matter?**

Battery cathode materials like KCoO2 can sometimes be improved by substituting a fraction of their atoms with a different element. However, not every dopant is stable — some are thermodynamically unfavorable, and some cause the crystal structure to deteriorate during battery operation at elevated temperatures. This simulation workflow tests both aspects:

1. **Thermodynamic feasibility** — Is it energetically favorable to place Fe into the crystal? (Formation energy test)
2. **Thermal stability** — Does the crystal remain intact when heated to 200°C? (Molecular dynamics simulation)

---

## 2. Quick Summary of Results

**Fe strongly prefers to occupy the Co layer**, with a formation energy 6.242 eV lower than the K layer. Put simply: the material 'wants' the dopant on the Co site much more than the K site. The MD results reinforce this: dopant movement on the Co site was -0.00158 Å²/ps (stable) vs 0.08760 Å²/ps on the K site. The Co-site result is the most reliable because there is no charge mismatch — the dopant carries the same oxidation state as the atom it replaced, so the energy calculation is fully accurate. The K-site energy is approximate (charge surplus of +2 cannot be fully modelled in CHGNet).

| Site # | Target Layer | Formation Energy | Thermodynamic? | Thermal Stability | Verdict |
|--------|-------------|-----------------|---------------|-------------------|---------|
| 16 | Co | -1.042 eV | ✅ Favorable | ✅ Stable | ✅ STABLE |
| 0 | K | +5.200 eV | ❌ Unfavorable | ❌ Migrating | ⚠️ MIGRATION / UNFAVORABLE |

**Best overall:** Site 16 (Co layer) — E_f = -1.042 eV, verdict: **STABLE**

---

## 3. Detailed Results

> *Each subsection below describes one tested atomic configuration in detail.*

### 3.1  Site 16: Fe replacing Co

**Overall verdict: ✅ **STABLE****

**Charge balance:** Fe and Co have the same oxidation state (*isovalent substitution*) — no charge compensation is needed. All energies for this site are fully reliable.

#### A. Was It Energetically Favorable? (Formation Energy)

> **What is formation energy?** It tells you whether the crystal 'wants' to incorporate the dopant. A negative value means energy is released (favorable, spontaneous); a positive value means energy must be supplied (less favorable). Values below +1.0 eV are considered potentially achievable.

The formation energy is **-1.042 eV** — strongly negative. Placing Fe on the Co site releases energy, so the process happens spontaneously under normal conditions. The material is very likely to accept this dopant.

| Parameter | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| Formation energy (E_f) | **-1.0422 eV** | < 1.0 eV | ✅ PASS |

#### B. Crystal Structure After Relaxation

> **What is relaxation?** After placing the dopant, the simulation lets all surrounding atoms shift to find the lowest-energy arrangement. This section shows the stable structure after that adjustment.

- **Space group:** `Pm (6)`  
  *(Describes the crystal's 3-D symmetry pattern. Deviations from the pristine symmetry indicate structural distortion around the dopant.)*
- **Coordination number:** 5  
  *(Number of oxygen atoms directly bonded to the dopant. In undoped KCoO2, Co atoms typically have 6 such neighbors.)*
- **Average dopant–O bond length:** 1.9864 Å
- **All dopant–O bond lengths:** 1.770, 2.040, 2.040, 2.041, 2.041 Å

#### C. Thermal Stability at 200°C (Molecular Dynamics)

> **What is molecular dynamics (MD)?** We simulate atomic vibrations for 25 picoseconds at 200°C to test whether the dopant stays in place and whether the crystal survives operating conditions. One picosecond = one trillionth of a second (10⁻¹² s).

**Dopant mobility (Mean Squared Displacement — MSD):**

An MSD slope this close to zero (-0.00158 Å²/ps) means the dopant was essentially locked in place — it barely moved at all during the simulation. The farthest the dopant moved from its starting position was **0.79 Å** (about 1.5 times the Bohr radius), with a final mean-squared displacement of **0.108 Å²**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| MSD slope | **-0.00158 Å²/ps** | < 0.005 Å²/ps | ✅ PASS |
| Max displacement | **0.789 Å** | reference only | — |
| Final MSD | **0.1081 Å²** | reference only | — |

**Local bonding environment during MD:**

The number of neighboring oxygen atoms fluctuated between **4 and 5** (average: 5.0) during heating, compared to 5 after relaxation. This small variation is normal thermal fluctuation — the dopant's local environment is essentially intact. The average dopant–oxygen bond length during the simulation was **1.987 Å**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Coordination range | **4–5** (mean 5.0) | within ±1 of 5 | ✅ PASS |
| Avg bond length (MD) | **1.987 Å** | reference only | — |

**Crystal volume stability:**

The crystal's volume changed by only **+0.00%** — essentially no change. The host lattice is mechanically stable with this dopant.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Volume change | **+0.00%** | ±5% | ✅ PASS |
| Space group (MD) | `P1 (1)` | reference only | — |

#### D. What Does This Mean? (Verdict)

**Fe is a strong candidate for the Co site.** All four stability tests passed: the formation energy is thermodynamically favorable, the dopant does not migrate at 200°C, its local atomic environment is preserved during heating, and the host crystal does not expand or contract excessively. This result supports further experimental investigation.

**Simulation notes:**

- Symmetric multiplicity: 16

---

### 3.2  Site 0: Fe replacing K

**Overall verdict: ⚠️ **MIGRATION / UNFAVORABLE****

**Charge balance (approximate):** Fe carries more positive charge than K (charge mismatch: +2). CHGNet cannot fully model this electrical surplus, so the formation energy here is an estimate.  
*Description: aliovalent (mismatch +2): charge surplus cannot be modelled in CHGNet — running uncompensated single substitution (E_f approximate).*

#### A. Was It Energetically Favorable? (Formation Energy)

> **What is formation energy?** It tells you whether the crystal 'wants' to incorporate the dopant. A negative value means energy is released (favorable, spontaneous); a positive value means energy must be supplied (less favorable). Values below +1.0 eV are considered potentially achievable.

The formation energy is **+5.200 eV** — large and positive. A significant amount of energy is required to place Fe at the K site. Under most synthesis conditions this dopant configuration would not form.

> **Note on accuracy:** This formation energy is approximate. The dopant carries a different electric charge than the atom it replaced, and the simulation model (CHGNet) cannot fully account for that electrical imbalance. Treat this value as an estimate rather than an exact number.

| Parameter | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| Formation energy (E_f) | **+5.2002 eV** | < 1.0 eV | ❌ FAIL |

#### B. Crystal Structure After Relaxation

> **What is relaxation?** After placing the dopant, the simulation lets all surrounding atoms shift to find the lowest-energy arrangement. This section shows the stable structure after that adjustment.

- **Space group:** `P1 (1)`  
  *(Describes the crystal's 3-D symmetry pattern. Deviations from the pristine symmetry indicate structural distortion around the dopant.)*
- **Coordination number:** 5  
  *(Number of oxygen atoms directly bonded to the dopant. In undoped KCoO2, K atoms typically have 6 such neighbors.)*
- **Average dopant–O bond length:** 2.0209 Å
- **All dopant–O bond lengths:** 1.946, 2.038, 2.039, 2.040, 2.041 Å

#### C. Thermal Stability at 200°C (Molecular Dynamics)

> **What is molecular dynamics (MD)?** We simulate atomic vibrations for 25 picoseconds at 200°C to test whether the dopant stays in place and whether the crystal survives operating conditions. One picosecond = one trillionth of a second (10⁻¹² s).

**Dopant mobility (Mean Squared Displacement — MSD):**

The MSD slope (0.08760 Å²/ps) is well above the migration threshold. The dopant diffused significantly away from its intended site — it did not stay in place during heating. The farthest the dopant moved from its starting position was **1.61 Å** (about 3.0 times the Bohr radius), with a final mean-squared displacement of **1.185 Å²**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| MSD slope | **0.08760 Å²/ps** | < 0.005 Å²/ps | ❌ FAIL |
| Max displacement | **1.612 Å** | reference only | — |
| Final MSD | **1.1854 Å²** | reference only | — |

**Local bonding environment during MD:**

The number of neighboring oxygen atoms fluctuated between **4 and 6** (average: 4.7) during heating, compared to 5 after relaxation. This small variation is normal thermal fluctuation — the dopant's local environment is essentially intact. The average dopant–oxygen bond length during the simulation was **1.964 Å**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Coordination range | **4–6** (mean 4.7) | within ±1 of 5 | ✅ PASS |
| Avg bond length (MD) | **1.964 Å** | reference only | — |

**Crystal volume stability:**

The crystal's volume changed by only **+0.00%** — essentially no change. The host lattice is mechanically stable with this dopant.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Volume change | **+0.00%** | ±5% | ✅ PASS |
| Space group (MD) | `P1 (1)` | reference only | — |

#### D. What Does This Mean? (Verdict)

**Fe does not stay on the K site — it moves during the simulation.** Although the formation energy looks favorable, the dopant atom migrates at 200°C. The K site is not a stable resting place for this dopant. Inspecting the MD trajectory could reveal where it ends up.

**Simulation notes:**

- Symmetric multiplicity: 16

---

## 4. Glossary of Key Terms

| Term | Plain-English Definition |
|------|------------------------|
| **Dopant** | An atom of a different element intentionally inserted into a crystal to modify its properties. |
| **Host material** | The original crystal being modified. |
| **KCoO2** | The layered oxide cathode material studied here, used in rechargeable batteries. |
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
*Host: KCoO2 | Dopant: Fe | Temperature: 200°C | Sites tested: 2*