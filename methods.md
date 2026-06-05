# Methodology

A complete description of every computational step in the doping-stability
workflow, including the charge-compensation scheme for aliovalent dopants.
Intended as supplementary material for reporting results or as a reference
when modifying the workflow for a new host/dopant system.

---

## 1. Overview

The workflow predicts, for a given host crystal, candidate dopant element,
substitution site(s), and target temperature, whether the dopant is

1. **thermodynamically favourable** to incorporate (formation energy), and
2. **kinetically stable** on the proposed site at temperature (MD), and
3. **structurally compatible** with the host lattice (lattice volume).

The implementation is built on **CHGNet** [1] — a universal pretrained
machine-learning interatomic potential trained on r²SCAN density functional
theory data from the Materials Project — combined with **pymatgen** [2]
for structure handling and **ASE** [3] for molecular dynamics. CHGNet allows
the same DFT-quality energy surface to be evaluated ≈10³–10⁴ × faster than
direct DFT, enabling site enumeration and finite-temperature MD that would
be intractable otherwise.

The workflow proceeds in six numbered phases, with checkpoint files written
at every step so a paused run can be resumed:

| Phase | Output |
|---|---|
| 1. Reference chemical potentials | `references.json` |
| 2. Pristine supercell relaxation | `relaxed_structures/<host>_pristine_N.cif` |
| 3. Site enumeration + doped relaxations + E_f | `relaxed_structures/<host>_<dopant>@<element>_site*.cif` |
| 4. NVT molecular dynamics | `md_runs/<test>/md.traj` |
| 5. Trajectory analysis | `analysis/<test>/{msd,rdf,coordination}.csv` |
| 6. Stability report + verdict | `reports/<test>.json`, `reports/summary.csv` |

---

## 2. Phase 1 — Reference chemical potentials

Defect formation energies require a reference chemical potential μ for every
element added to or removed from the supercell. Within this workflow each μ
is computed self-consistently by CHGNet, ensuring the reference and the
defect energy come from the same energy surface.

### 2.1 Reference structures

Elemental ground-state structures hard-coded in `setup_references.py`:

| Element | Structure | Lattice constant(s) | Atoms/cell |
|---|---|---|---|
| Al | FCC | a = 4.046 Å | 4 |
| Co | HCP | a = 2.507 Å, c = 4.069 Å | 2 |
| Ca | FCC | a = 5.588 Å | 4 |
| Na | BCC | a = 4.225 Å | 2 |
| Mn | BCC | a = 2.911 Å | 2 |

For each requested element, the cell is relaxed with CHGNet's `StructOptimizer`
(FIRE algorithm, `fmax = 0.01 eV/Å`), and the per-atom energy is recorded:

$$\mu_X = \frac{E_{\text{total}}(\text{relaxed elemental }X)}{n_X}$$

The resulting values are cached to `references.json` and reused on subsequent
runs. To switch to different reference conditions (e.g. oxide-rich rather
than metal-rich), replace the reference structures or pass pre-computed
μ values to `formation_energy()` directly.

### 2.2 Caveats

- **α-Mn approximation.** Manganese's true ground state is α-Mn (space
  group I-43m, 58 atoms/cell). The 2-atom BCC structure used here is a
  computationally tractable proxy; it gives μ(Mn) consistent within
  CHGNet's energy frame but differs from α-Mn by perhaps 0.1–0.2 eV/atom.
  This systematic offset cancels exactly when comparing E_f values for
  the *same* dopant at *different* sites.

- **Metal-rich limit.** Using elemental references corresponds to the
  metal-rich corner of the chemical potential diagram. Oxide-rich
  conditions (Al₂O₃ for Al, CoO/Co₃O₄ for Co, etc.) give different μ
  and therefore different absolute E_f. Relative orderings of sites are
  preserved across these conditions.

---

## 3. Phase 2 — Pristine supercell

The host CIF is read into a `pymatgen.Structure` and expanded to an
N × N × N supercell (default N = 2). For NaCoO₂ this yields 32 atoms
(8 Na + 8 Co + 16 O) starting from a 4-atom primitive cell.

The supercell is then relaxed with CHGNet (`StructOptimizer.relax`,
`fmax = 0.01 eV/Å`, max 500 steps). The relaxed structure becomes the
common reference for every doped-supercell calculation in Phase 3.

The relaxed CIF is cached to `relaxed_structures/<host>_pristine_N.cif`
with a JSON sidecar containing `energy_eV` and `space_group`. Subsequent
runs skip Phase 2 if both files exist.

---

## 4. Phase 3 — Doped supercells and formation energies

This phase is the analytical core: it (a) enumerates all symmetry-distinct
sites of each target element, (b) builds a charge-compensated doped
supercell at each site, (c) relaxes it, and (d) computes the defect
formation energy.

### 4.1 Site enumeration

For each `target_element` (e.g. Co for the cobalt layer, Na for the
alkali layer), `enumerate_sites()` uses
`pymatgen.symmetry.analyzer.SpacegroupAnalyzer` (`symprec = 10⁻³`) to
identify the equivalence classes of `target_element` atoms in the
pristine supercell. A single representative is selected per class; the
multiplicity (size of the orbit) is recorded for reporting.

For a 2×2×2 NaCoO₂ supercell with P-3m1 host symmetry, both the 8 Co and
the 8 Na atoms collapse into a single Wyckoff orbit each, so only one
substitution per target element is needed.

### 4.2 Charge compensation

For an aliovalent dopant, simple substitution leaves the supercell with a
net charge that is unphysical in a periodic calculation. The workflow
addresses this by introducing structural charge compensation.

**Charge mismatch** between dopant X (oxidation state +q_X) and host atom Y
(oxidation state +q_Y):

$$\Delta q = q_X - q_Y$$

Default oxidation states are taken from a lookup table covering common
cathode-relevant elements (alkali, alkaline earth, group 13, 3d/4d/5d
transition metals, common anions). The user can override either via
`dopant_oxidation_state` or `target_oxidation_states={"Co": 3, ...}` in
`WorkflowConfig`.

Three cases are handled in `charge_utils.build_compensated_supercell`:

#### Case A — Isovalent (Δq = 0)
Examples: Al³⁺ → Co³⁺, Mn³⁺ → Co³⁺. Plain substitution; E_f is fully
reliable.

#### Case B — Negative mismatch (Δq < 0)
Examples: Ca²⁺ → Co³⁺ (Δq = −1), Ni²⁺ → V⁵⁺ (Δq = −3). The dopant
brings less positive charge than the host atom it replaces, so the
supercell would be negatively charged. To restore neutrality, |Δq|
alkali atoms (Na by default, set by `compensation_ref`) are removed
from the supercell.

**Which Na to remove?** All Na atoms are ranked by their distance from
the dopant site, using the minimum-image convention to handle periodic
boundaries:

$$d_i = \|\,\mathcal{L} \cdot \mathrm{wrap}(\mathbf{r}_i^{\mathrm{frac}} - \mathbf{r}_{\mathrm{dopant}}^{\mathrm{frac}})\,\|$$

The |Δq| Na atoms with the largest d_i are removed. This maximises the
defect-defect separation and approximates the dilute-limit formation
energy as closely as a finite supercell allows.

#### Case C — Positive mismatch (Δq > 0)
Examples: Mn³⁺ → Na⁺ (Δq = +2), Ca²⁺ → Na⁺ (Δq = +1). The dopant
brings *more* positive charge than the host atom it replaces.
Compensation in a real material would proceed via cation oxidation
(e.g. Co³⁺ → Co⁴⁺) or interstitial electron capture. Neither
mechanism is available to a charge-neutral interatomic potential —
CHGNet has no notion of oxidation state or local charge.

The workflow runs the plain substitution and **flags E_f as approximate
in the report**. Structural and dynamical observables (MSD, coordination,
lattice) remain physically meaningful, but the absolute E_f should not
be trusted beyond an order-of-magnitude estimate.

### 4.3 Doped-cell relaxation

Each constructed defect supercell is relaxed with the same CHGNet
optimiser as in Phase 2. The relaxed CIF and a JSON sidecar with energy,
space group, coordination number, nearest-neighbour distances, and a
compensation flag are cached.

### 4.4 Defect formation energy

$$E_f = E(\text{doped}) - E(\text{pristine}) + \sum_{i \in \text{removed}} \mu_i - \mu_{\text{dopant}}$$

The sum runs over every atom removed from the pristine supercell. For
isovalent substitution this is just the host atom: $E_f = E_d - E_p + \mu_Y - \mu_X$.
For a negative-mismatch substitution with k Na vacancies added,

$$E_f = E_d - E_p + \mu_Y + k\,\mu_{\mathrm{Na}} - \mu_X$$

A negative E_f means doping is thermodynamically exothermic relative to
the chosen reference state; a positive E_f means doping is endothermic
but may still be accessible via non-equilibrium synthesis (ion exchange,
quench).

### 4.5 What is NOT included

This workflow does **not** apply the Freysoldt/Kumagai [4,5] electrostatic
finite-size correction for charged defects. These corrections require
the host dielectric tensor and the DFT electrostatic potential, neither
of which is produced by CHGNet. For publication-quality charged-defect
E_f the user should follow up with DFT (e.g. VASP + `doped` [6] or
`pymatgen-analysis-defects`) on the relaxed supercells produced here.

---

## 5. Phase 4 — NVT molecular dynamics

For each substitution site (or the top-N lowest-E_f sites per layer when
multiple are tested), an NVT trajectory is generated at the target
temperature.

| Setting | Default |
|---|---|
| Ensemble | NVT (Berendsen thermostat) |
| Timestep | 2.0 fs |
| Equilibration | 2 500 steps = 5 ps |
| Production | 25 000 steps = 50 ps |
| Logging interval | every 10 steps |
| Temperature | 250 °C = 523.15 K (configurable) |

CHGNet's `MolecularDynamics` wrapper around ASE is used. The integrator
operates on the relaxed doped supercell with all structural compensation
defects already in place.

**Equilibration vs production.** Only frames from after the equilibration
window are passed to the trajectory analysis in Phase 5. The
equilibration window allows the system to reach the target temperature
and lose any artefacts from the 0 K relaxed starting point.

**Checkpointing.** Trajectories are written incrementally to `md.traj`.
If the run is interrupted mid-trajectory, the next invocation reads the
existing frames, takes the last frame's positions and velocities as a
new starting point, runs the remaining steps, and concatenates the
segments. A `md.complete.json` marker is only written when the full
production count is reached.

---

## 6. Phase 5 — Trajectory analysis

The production trajectory is loaded with `ase.io.read` and the dopant
atom's index is identified by symbol.

### 6.1 Mean-squared displacement (MSD)

Per-frame Cartesian displacements between consecutive frames are
converted to fractional coordinates, wrapped to (−½, +½] via the
minimum-image convention, transformed back to Cartesian, and accumulated.
This yields the true unwrapped trajectory of the dopant atom even when
it crosses periodic-boundary images:

$$\Delta \mathbf{r}_t = \mathcal{L} \cdot \mathrm{wrap}\bigl(\mathcal{L}^{-1}(\mathbf{r}_t - \mathbf{r}_{t-1})\bigr)$$

$$\mathbf{r}_t^{\mathrm{unwrapped}} = \sum_{s \leq t} \Delta \mathbf{r}_s$$

$$\mathrm{MSD}(t) = \|\mathbf{r}_t^{\mathrm{unwrapped}} - \mathbf{r}_0\|^2$$

A least-squares linear fit is then performed on the **last 50%** of the
MSD time series to extract the long-time slope:

$$\mathrm{MSD}(t) \approx 6 D t + C \quad\text{(3D Einstein relation)}$$

Using only the late-time portion avoids contamination from the initial
ballistic and sub-diffusive regimes.

**Thermal-noise calibration of the migration cutoff.** A dopant confined
to its site is *not* motionless — it oscillates thermally, so its late-time
MSD wanders around a plateau and the linear fit returns a small nonzero
slope (frequently *negative*, which is impossible for genuine diffusion and
therefore a direct readout of the noise). A single fixed slope cutoff cannot
separate signal from this noise, because the noise level itself varies by
more than an order of magnitude between runs (different temperature, host,
dopant mass, and plateau amplitude). The fit therefore also returns the
**standard error of the slope**, $\sigma_b$, which is precisely the margin of
error contributed by thermal fluctuations. Because the single-origin MSD is a
near-continuous random walk, successive points are strongly autocorrelated
(lag-1 $\rho \approx 0.8\text{–}0.95$); ordinary least squares, assuming
independent residuals, understates $\sigma_b$ several-fold. We model the fit
residuals as an AR(1) process and inflate the OLS error accordingly,

$$\sigma_b = \sigma_b^{\mathrm{OLS}}\sqrt{\tfrac{1+\rho}{1-\rho}},
\qquad N_{\mathrm{eff}} = N\,\tfrac{1-\rho}{1+\rho},$$

so $\sigma_b$ reflects the *effective* number of independent samples in the
fit window. The dopant is classified as **migrating** only when its slope
rises above the larger of a fixed floor and the thermal margin of error,

$$\text{cutoff} = \max\bigl(0.005\ \text{Å}^2/\text{ps},\ 2\,\sigma_b\bigr),$$

i.e. the slope must exceed thermal noise by $\approx 2\sigma$ (one-sided
$\approx$ 97.5 % confidence). A slope within $\pm 2\sigma_b$ of zero is
statistically indistinguishable from a vibrating-but-stationary atom and is
reported as a plateau. The floor (`MSD_PLATEAU_SLOPE_A2_PER_PS`) is the
smallest slope ever treated as migration even in an exceptionally quiet run
($\sigma_b$ near zero); the multiplier is `MSD_NOISE_SIGMA`. Because the
cutoff is the *maximum* of the two terms, the test is never looser than the
old fixed threshold — it only tightens for noisy runs, eliminating the
spurious "migration" verdicts that thermal fluctuations would otherwise
produce.

### 6.2 Coordination number (informational only)

For every production frame, distances from the dopant atom to all other
atoms (minimum-image convention) are computed, and the count within
`coordination_cutoff_A` (default 2.5 Å) is recorded. The min, max, and
mean over the trajectory are reported.

The first-shell count is **reported for diagnostics only and is not used
in the verdict** (see §7). The count is extremely sensitive to the choice
of `coordination_cutoff_A`: for large dopants (Ca, Sr, or alkali-site
substitutions) the relaxed dopant–O bond length already sits near the
2.5 Å cutoff, so ordinary thermal vibration pushes individual neighbours
in and out of the shell and makes the min/max swing by 2–3 even when the
lattice is mechanically intact. Gating on this count produced spurious
"collapse" verdicts for otherwise-stable large-ion dopants, so the
criterion was removed; lattice volume (§6.4) is the structural gate.

### 6.3 Mean nearest-neighbour distance

The same first-shell neighbours are averaged across all frames. Compared
to the relaxed (0 K) mean NN distance, this quantifies thermal
expansion of the local environment.

### 6.4 Volume change

$$\Delta V \;/\; V_0 = \frac{V(t_{\mathrm{final}}) - V(t_0)}{V(t_0)} \times 100\%$$

A persistent shift > ±5 % is interpreted as a mechanical instability
of the doped phase at temperature.

### 6.5 Time-averaged space group

Atomic positions are averaged over ~20 evenly spaced frames, and the
averaged structure is passed to `SpacegroupAnalyzer` with a loose
tolerance (`symprec = 0.05`). The resulting space group is **reported
informationally only**, not used in the verdict. Single-frame analysis
of a finite-temperature trajectory will always return P1; even averaged
frames are noisy enough that recovery of the host space group is
hit-or-miss in modest supercells.

### 6.6 Radial distribution function

A radial histogram of dopant-neighbour distances over all production
frames is written to `rdf.csv` for offline plotting. This is purely
diagnostic.

---

## 7. Phase 6 — Stability classification

Every test produces a `StabilityReport` object aggregating the Phase 3
and Phase 5 outputs. Three criteria are evaluated against fixed
thresholds:

| Criterion | Pass condition | Threshold | Rationale |
|---|---|---|---|
| Formation energy | E_f < 1 eV | `EF_THRESHOLD_OK = 1.0` | 1 eV is the conventional upper bound for dilute defect feasibility under equilibrium synthesis |
| Dopant mobility | MSD slope < max(0.005 Å²/ps, 2σ_b) | `MSD_PLATEAU_SLOPE_A2_PER_PS`, `MSD_NOISE_SIGMA` | cutoff held at the edge of the per-run thermal-fluctuation margin of error σ_b (§6.1); floor ≈ one bond-length hop over the production run |
| Lattice integrity | \|ΔV/V\| < 5 % | `VOLUME_CHANGE_TOLERANCE_PCT` | conventional cutoff for mechanical stability of solid solutions |

Coordination number is measured and reported but is **not** a pass/fail
criterion (see §6.2): the first-shell count is too sensitive to the bond
cutoff to gate on, and doing so produced spurious "collapse" verdicts for
large-ion dopants whose bonds sit near the cutoff at rest.

The criteria combine into one of six verdicts:

| Verdict | Meaning |
|---|---|
| `STABLE` | All three criteria pass — dopant sits favourably on its site at T |
| `METASTABLE` | E_f marginal but MD shows stable site occupancy; achievable via quench / ion exchange |
| `MIGRATION` | E_f favourable but dopant moves during MD; the relaxed site is not the true resting site |
| `STRUCTURAL COLLAPSE` | Lattice volume change signals mechanical instability |
| `FAVORABLE (relaxation only)` | E_f passes, MD not yet run |
| `UNFAVORABLE (relaxation only)` | E_f fails, MD not yet run |

For multi-target runs (`target_elements = ["Co", "Na"]`), every site
report is collected and a cross-site comparison table is printed,
identifying the layer with the lowest E_f as the preferred substitution
site for the dopant.

---

## 8. Limitations and known approximations

1. **CHGNet is charge-neutral.** The potential predicts forces from a
   universal neural network with no charge state or oxidation state
   degree of freedom. Positive-mismatch cases (where compensation
   requires electron addition) cannot be modelled rigorously, and even
   compensated cases lack the polaron/electronic relaxation energy that
   DFT captures.

2. **No electrostatic finite-size correction.** Charged-defect E_f from
   single-supercell DFT requires Freysoldt or Kumagai correction terms
   that depend on the host dielectric tensor and the DFT electrostatic
   potential. Neither is available from an MLIP.

3. **Single supercell size and dopant concentration.** A 2×2×2 NaCoO₂
   supercell with one substitution corresponds to a dopant concentration
   of 1/8 ≈ 12.5 %. To probe dilution effects, repeat the workflow at
   3×3×3 or 4×4×4.

4. **MD timescale ≪ slow diffusion.** 50 ps of production is sufficient
   to identify whether a dopant sits stably or migrates rapidly. It is
   *not* sufficient to extract a quantitative diffusion coefficient for
   any but the fastest-diffusing ions.

5. **r²SCAN-trained MLIP accuracy.** CHGNet is trained on r²SCAN DFT
   from the Materials Project. Formation-energy errors for transition-
   metal oxides are typically 50–150 meV/atom relative to higher-level
   methods. Relative orderings between similar configurations are far
   more reliable than absolute values.

6. **Reference state assumes metal-rich conditions.** Synthesis under
   different chemical potentials (oxide-rich, reducing atmosphere, etc.)
   shifts all E_f by additive constants that depend on the alternative
   reference phases.

---

## 9. References

[1] B. Deng, P. Zhong, K. Jun, J. Riebesell, K. Han, C. J. Bartel,
G. Ceder, *CHGNet as a pretrained universal neural network potential for
charge-informed atomistic modelling*, Nature Machine Intelligence **5**,
1031–1041 (2023).

[2] S. P. Ong, W. D. Richards, A. Jain, G. Hautier, M. Kocher,
S. Cholia, D. Gunter, V. L. Chevrier, K. A. Persson, G. Ceder,
*Python Materials Genomics (pymatgen): A robust, open-source python
library for materials analysis*, Comp. Mater. Sci. **68**, 314 (2013).

[3] A. H. Larsen, J. J. Mortensen, J. Blomqvist, *et al.*,
*The atomic simulation environment — a Python library for working with
atoms*, J. Phys. Condens. Matter **29**, 273002 (2017).

[4] C. Freysoldt, J. Neugebauer, C. G. Van de Walle,
*Fully ab initio finite-size corrections for charged-defect supercell
calculations*, Phys. Rev. Lett. **102**, 016402 (2009).

[5] Y. Kumagai, F. Oba,
*Electrostatics-based finite-size corrections for first-principles
point defect calculations*, Phys. Rev. B **89**, 195205 (2014).

[6] S. R. Kavanagh, A. G. Squires, A. Nicolson, *et al.*,
*doped: Python toolkit for robust and repeatable charged defect
supercell calculations*, J. Open Source Softw. **9**, 6433 (2024).
