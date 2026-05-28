# Doping Stability Report: Ca in KCoO2

*Generated: May 28, 2026 at 12:27 PM*  
*Simulation temperature: 250°C (523.1 K)*  
*Total configurations tested: 1*

---

## 1. What Is This Study Testing?

This study investigates whether **Ca** (the *dopant*) can be stably inserted into the crystal structure of **KCoO2** (the *host material*) by replacing one of the **K** atoms already present in the crystal. This process is called *doping*.

**Why does this matter?**

Battery cathode materials like KCoO2 can sometimes be improved by substituting a fraction of their atoms with a different element. However, not every dopant is stable — some are thermodynamically unfavorable, and some cause the crystal structure to deteriorate during battery operation at elevated temperatures. This simulation workflow tests both aspects:

1. **Thermodynamic feasibility** — Is it energetically favorable to place Ca into the crystal? (Formation energy test)
2. **Thermal stability** — Does the crystal remain intact when heated to 250°C? (Molecular dynamics simulation)

---

## 2. Quick Summary of Results

| Site # | Target Layer | Formation Energy | Thermodynamic? | Thermal Stability | Verdict |
|--------|-------------|-----------------|---------------|-------------------|---------|
| 0 | K | -3.294 eV | ✅ Favorable | ✅ Stable | ❌ STRUCTURAL COLLAPSE |

**Best overall:** Site 0 (K layer) — E_f = -3.294 eV, verdict: **STRUCTURAL COLLAPSE**

---

## 3. Detailed Results

> *Each subsection below describes one tested atomic configuration in detail.*

### 3.1  Site 0: Ca replacing K

**Overall verdict: ❌ **STRUCTURAL COLLAPSE****

**Charge balance (approximate):** Ca carries more positive charge than K (charge mismatch: +1). CHGNet cannot fully model this electrical surplus, so the formation energy here is an estimate.  
*Description: aliovalent (mismatch +1): charge surplus cannot be modelled in CHGNet — running uncompensated single substitution (E_f approximate).*

#### A. Was It Energetically Favorable? (Formation Energy)

> **What is formation energy?** It tells you whether the crystal 'wants' to incorporate the dopant. A negative value means energy is released (favorable, spontaneous); a positive value means energy must be supplied (less favorable). Values below +1.0 eV are considered potentially achievable.

The formation energy is **-3.294 eV** — an exceptionally large negative value. In simple terms: the crystal strongly 'wants' to incorporate Ca at the K site. A large negative value means the process releases a lot of energy, making it thermodynamically driven. This is as favorable as it gets.

> **Note on accuracy:** This formation energy is approximate. The dopant carries a different electric charge than the atom it replaced, and the simulation model (CHGNet) cannot fully account for that electrical imbalance. Treat this value as an estimate rather than an exact number.

| Parameter | Value | Threshold | Result |
|-----------|-------|-----------|--------|
| Formation energy (E_f) | **-3.2935 eV** | < 1.0 eV | ✅ PASS |

#### B. Crystal Structure After Relaxation

> **What is relaxation?** After placing the dopant, the simulation lets all surrounding atoms shift to find the lowest-energy arrangement. This section shows the stable structure after that adjustment.

- **Space group:** `Cm (8)`  
  *(Describes the crystal's 3-D symmetry pattern. Deviations from the pristine symmetry indicate structural distortion around the dopant.)*
- **Coordination number:** 5  
  *(Number of oxygen atoms directly bonded to the dopant. In undoped KCoO2, K atoms typically have 6 such neighbors.)*
- **Average dopant–O bond length:** 2.3696 Å
- **All dopant–O bond lengths:** 2.369, 2.369, 2.370, 2.370, 2.370 Å

#### C. Thermal Stability at 250°C (Molecular Dynamics)

> **What is molecular dynamics (MD)?** We simulate atomic vibrations for 25 picoseconds at 250°C to test whether the dopant stays in place and whether the crystal survives operating conditions. One picosecond = one trillionth of a second (10⁻¹² s).

**Dopant mobility (Mean Squared Displacement — MSD):**

An MSD slope this close to zero (-0.00321 Å²/ps) means the dopant was essentially locked in place — it barely moved at all during the simulation. The farthest the dopant moved from its starting position was **1.03 Å** (about 2.0 times the Bohr radius), with a final mean-squared displacement of **0.026 Å²**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| MSD slope | **-0.00321 Å²/ps** | < 0.005 Å²/ps | ✅ PASS |
| Max displacement | **1.032 Å** | reference only | — |
| Final MSD | **0.0256 Å²** | reference only | — |

**Local bonding environment during MD:**

The coordination number ranged from **1 to 6** (average: 3.8), deviating significantly from the relaxed value of 5. This indicates the local structure around the dopant changed during heating, which may signal structural distortion. The average dopant–oxygen bond length during the simulation was **2.325 Å**.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Coordination range | **1–6** (mean 3.8) | within ±1 of 5 | ❌ FAIL |
| Avg bond length (MD) | **2.325 Å** | reference only | — |

**Crystal volume stability:**

The crystal's volume changed by only **+0.00%** — essentially no change. The host lattice is mechanically stable with this dopant.

| Metric | Value | Threshold | Result |
|--------|-------|-----------|--------|
| Volume change | **+0.00%** | ±5% | ✅ PASS |
| Space group (MD) | `P1 (1)` | reference only | — |

#### D. What Does This Mean? (Verdict)

**The coordination count flagged a potential problem, but this may be a measurement artifact.** The dopant barely moved (confirming site stability), but the coordination count fluctuated — possibly because the bond-detection cutoff is close to the actual bond length. Consider re-running analysis with a slightly larger `coordination_cutoff_A` value.

**Simulation notes:**

- Symmetric multiplicity: 16
- WARNING: Charge surplus (+1) cannot be modelled in CHGNet. Running single substitution without compensation. E_f is approximate.

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
*Host: KCoO2 | Dopant: Ca | Temperature: 250°C | Sites tested: 1*