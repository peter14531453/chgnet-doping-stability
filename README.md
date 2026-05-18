# CHGNet Doping Stability Workflow

A six-phase workflow built on [CHGNet](https://github.com/CederGroupHub/chgnet)
for determining whether a dopant element is **thermodynamically stable**,
**kinetically dopable**, and **where it sits** in a target crystal at a
specified temperature.

The default configuration substitutes **Al for Co in NaCoO2** at **250 C**,
which is the original experimental question this code was built around. Every
parameter is exposed in [run_workflow.py](run_workflow.py).

## What it does

For a host crystal + candidate dopant, the workflow:

1. **Reference chemical potentials** -- relaxes elemental ground states of the
   dopant and substituted element with CHGNet, giving per-atom mu values for
   defect formation energies.
2. **Site enumeration** -- finds all symmetrically distinct host sites of the
   target element in the supercell using `SpacegroupAnalyzer`.
3. **Relaxation + formation energy** -- relaxes the pristine and every doped
   configuration, computes `E_f = E(doped) - E(pristine) + mu(removed) - mu(dopant)`.
4. **Finite-temperature MD** -- runs an NVT trajectory on the top-N lowest-Ef
   sites at the target temperature, with separate equilibration and production
   segments.
5. **Trajectory analysis** -- dopant MSD and late-time slope, coordination
   history, mean nearest-neighbor distance, lattice volume drift, and
   space group of the time-averaged structure.
6. **Stability report** -- aggregates phase 3 + 5 into a structured verdict
   per site, plus a summary CSV across all sites.

## Stability verdicts

Every test prints a report with PASS / FAIL on each criterion:

- **E_f below threshold** (default 1.0 eV; below 0 is very favorable)
- **MSD plateaus** (late-time slope below 0.005 A^2/ps)
- **Coordination stays sensible** (within +/- 1 of relaxed coordination)
- **No structural collapse** (volume drift below +/-5%, space group preserved)

These combine into one of:

| Verdict | Meaning |
|---|---|
| **STABLE** | Favorable E_f and MD shows the dopant stays on this site at T. |
| **METASTABLE** | E_f above threshold but MD is well-behaved. Possible with non-equilibrium synthesis. |
| **MIGRATION** | Site relaxes well but the dopant moves during MD -- the true preferred site is elsewhere. |
| **STRUCTURAL COLLAPSE** | Lattice or symmetry distorts beyond tolerance. |
| **FAVORABLE / UNFAVORABLE (relaxation only)** | Verdict before MD runs. |

## Project layout

```
report.py              Stability evaluation + structured printout
setup_references.py    Phase 1 -- chemical potentials
enumerate_and_relax.py Phase 2-3 -- site enumeration, relaxation, E_f
run_md.py              Phase 4 -- NVT molecular dynamics
analyze_trajectory.py  Phase 5 -- MSD, coordination, RDF, lattice
run_workflow.py        Orchestrator (configure + run all phases)
primitive_cells/       Input CIF files for host crystals
relaxed_structures/    Pristine + doped relaxed CIFs (output)
md_runs/               Per-test MD trajectories + logs (output)
analysis/              Per-test MSD/coordination/RDF CSVs (output)
reports/               Per-test JSON reports + summary.csv (output)
```

## Installation

```powershell
conda create -n chgnet python=3.11 -y
conda activate chgnet
pip install -r requirements.txt
```

CHGNet builds a Cython extension on install. On Windows you need **Microsoft
Visual C++ Build Tools** (Desktop development with C++ workload):
<https://visualstudio.microsoft.com/visual-cpp-build-tools/>

## Running

```powershell
conda activate chgnet
python run_workflow.py
```

To change dopant, host, or temperature, edit the `WorkflowConfig` block at the
bottom of `run_workflow.py`.

## Caveats

- **CHGNet is charge-neutral.** Isovalent substitutions (Al3+/Co3+) are
  modelled directly; aliovalent cases (e.g. Al3+/Na+) require explicit
  charge-compensating defects in the supercell.
- **Energy rankings are more trustworthy than absolute values.** CHGNet is a
  universal MLIP fitted to DFT; treat E_f differences between sites as the
  primary signal.
- **Single concentration per run.** Re-run with a larger supercell to probe
  dilution effects.
- **MD timescales are short.** The default 50 ps production captures local
  dynamics but not slow diffusion -- treat a non-plateauing MSD as evidence
  that the site is unstable, not as a quantitative diffusion measurement.
