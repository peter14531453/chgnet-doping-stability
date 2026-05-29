# CHGNet Doping Stability Workflow

A six-phase workflow built on [CHGNet](https://github.com/CederGroupHub/chgnet)
for determining whether a dopant element is **thermodynamically stable**,
**kinetically dopable**, and **where it sits** in a target crystal at a
specified temperature.

The workflow targets layered **ACoO2** cathodes (**NaCoO2**, **KCoO2**, or
**LiCoO2**) with command-line control over host lattice, dopant, and
substitution layer. Additional settings (supercell size, MD temperature, step
counts) live in `WorkflowConfig` inside [run_workflow.py](run_workflow.py).

For exploring many dopants at once, an **interactive batch mode**
([interactive.py](interactive.py)) lets you queue a mix of hosts and dopants in
one session (see *Interactive batch mode* below).

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

## Checkpointing and resume

Every phase writes its result to disk. Reruns of `python run_workflow.py`
skip any phase whose output already exists, so a paused or crashed run
picks up where it stopped.

| Phase | Checkpoint files |
|---|---|
| 1. References | `references.json` |
| 2. Pristine relax | `relaxed_structures/<host>_pristine_N.cif` + `.json` sidecar |
| 3. Doped relax | `relaxed_structures/<host>_<dopant>@<elem>_siteI.cif` + `.json` |
| 4. MD | `md_runs/<test>/md.traj` + `md.complete.json` marker |
| 5. Analysis | `analysis/<test>/analysis.json` (plus msd.csv, rdf.csv, coordination.csv) |
| 6. Report | `reports/<host>_<dopant>@<site>_siteI.json`, `<host>_<dopant>_summary.csv`, `<host>_<dopant>_final.json` |

**MD additionally supports mid-run resume.** If a previous run was killed
partway through the trajectory, the next run reads the existing `md.traj`,
starts a new MD segment from the last frame (velocities preserved), and
concatenates the segments when complete. The `md.complete.json` marker is
only written when the full step count is reached.

To force a full recompute, pass `--force-recompute` or delete the relevant
checkpoint files.

## Progress bar

Each test gets a tqdm bar pinned to the bottom of the terminal showing
relaxation + MD + analysis progress in real time, with elapsed and remaining
time. Use `info(msg)` from `progress.py` instead of `print()` inside the
workflow so the bar redraws cleanly underneath your output.

## Project layout

```
report.py              Stability evaluation + structured printout
setup_references.py    Phase 1 -- chemical potentials
enumerate_and_relax.py Phase 2-3 -- site enumeration, relaxation, E_f
run_md.py              Phase 4 -- NVT MD with checkpoint + mid-run resume
analyze_trajectory.py  Phase 5 -- MSD, coordination, RDF, lattice
progress.py            Bottom-pinned tqdm progress bar
run_workflow.py        Orchestrator (configure + run all phases)
primitive_cells/       Input CIF files (NaCoO2.cif, KCoO2.cif)
relaxed_structures/    Pristine + doped relaxed CIFs + sidecar JSON (output)
md_runs/               Per-test MD trajectories + completion markers (output)
analysis/              Per-test MSD/coordination/RDF CSVs + analysis.json (output)
reports/               Per-site JSON, run summary CSV, and final JSON (output)
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
python run_workflow.py --dopant Al --host NaCoO2 --sites Co
```

`--dopant` is required. Other flags are optional.

### Command-line options

| Flag | Description |
|------|-------------|
| `--host` | Host lattice: `NaCoO2` (default), `KCoO2`, or `LiCoO2` |
| `--dopant` | Dopant element from the dopant database (see below) |
| `--sites` | One or more substitution layers (see below). Default: `Co` and the host alkali |
| `--oxidation-state` | Override the dopant's default oxidation state (e.g. `--oxidation-state 4`) |
| `--no-md` | Skip MD and trajectory analysis (relaxation + E_f only) |
| `--force-recompute` | Ignore cached relaxations, MD, and analysis |

### Dopants and substitution layers

Supported dopants live in [dopant_database.py](dopant_database.py) — ~25 curated
metals (alkaline-earth, post-transition, and 3d/4d/5d transition metals) with
their typical layered-oxide oxidation state. Each dopant is automatically tested
on whichever site(s) you pick; the charge mismatch versus that site is handled
for you (alkali vacancies compensate a charge *deficit*; a charge *surplus*, e.g.
Ti⁴⁺/Nb⁵⁺ on Co³⁺, runs uncompensated with an "E_f approximate" flag).

For `--sites`, each token is one of:

- `Co` — transition-metal layer
- `alkali` — `Na` (NaCoO2), `K` (KCoO2), or `Li` (LiCoO2), depending on `--host`
- `Na`, `K`, or `Li` — explicit alkali symbol (must match the host)

Running both layers (the default) ranks the dopant's site preference by
formation energy.

### Examples

```powershell
# Al on Co in NaCoO2
python run_workflow.py --host NaCoO2 --dopant Al --sites Co

# Mn on both Co and Na layers (site-preference comparison)
python run_workflow.py --host NaCoO2 --dopant Mn

# Ca on the K layer in KCoO2
python run_workflow.py --host KCoO2 --dopant Ca --sites alkali

# Ni on Co in KCoO2, both layers, no MD
python run_workflow.py --host KCoO2 --dopant Ni --sites Co K --no-md

# Full help
python run_workflow.py --help
```

Charge compensation uses **Na** for NaCoO2, **K** for KCoO2, and **Li** for
LiCoO2 automatically. The dopant oxidation state comes from the database
(override with `--oxidation-state`).

To change MD temperature, timestep, or step counts, edit `config_from_args` or
`WorkflowConfig` in [run_workflow.py](run_workflow.py).

## Interactive batch mode

For screening many dopants across hosts in one go:

```powershell
conda activate chgnet
python interactive.py
```

You'll be guided through:

1. **Pick hosts** — NaCoO2 (NCO), KCoO2 (KCO), and/or LiCoO2 (LCO).
2. **Pick dopants per host** — a grouped checklist (all pre-selected). Press
   **Enter** to take all, or:
   - `Space` toggle one
   - `Ctrl+A` select all · `Alt+D` deselect all · `Ctrl+R` invert
3. **Pick sites per host** — Co and the host alkali, both pre-selected.
4. **MD?** — off by default (fast relaxation + formation-energy screening).

Because choices are made per host, you can queue mixed trials in a single
session — e.g. *Al/Mn on LCO*, *Ti on KCO*, and *Sb/Sr/Al/Mn on NCO*. Before
anything runs you get a pre-flight summary (with charge-surplus warnings), and
when it finishes a **combined ranking** of every run by formation energy plus a
`reports/<date>/batch_summary.csv`.

CHGNet is loaded once and shared across all queued runs; per-phase caching means
re-running a session skips work already done.

## SLURM cluster (per-job submission with resume)

For a cluster with a hard wall-time limit (e.g. 4 h) where each workflow run is
a separate job, [submit_slurm_jobs.py](submit_slurm_jobs.py) manages submission
and resume:

```bash
source activate chgnet
python submit_slurm_jobs.py --status     # classify jobs, submit nothing
python submit_slurm_jobs.py --dry-run    # write .sbatch files + print, no sbatch
python submit_slurm_jobs.py              # write + submit the pending jobs
```

It scans the caches and labels each job FINISHED or, if not, which phase it would
resume from (pristine relax / doped relax / MD with the timestep reached /
analysis+report), prints that, writes one `.sbatch` per pending job (customised
`--output`, `--job-name`, and the `run_workflow.py` command), and submits with
`sbatch`. Jobs already in the SLURM queue (matched by name) are skipped.

**MD resume on restart.** A run killed mid-MD by the wall-time limit resumes from
its last checkpoint automatically: frames are written every `loginterval` steps,
and `run_md` folds the partial segment back into the trajectory on the next run
(see `_fold_segment`). Re-submitting the same `run_workflow.py` command continues
the MD from where it stopped rather than restarting it.

Edit the dopant/host lists at the top of `submit_slurm_jobs.py` to change the job
set. All jobs use `run_workflow.py`'s default MD temperature (250 C).

## Caveats

- **CHGNet is charge-neutral.** Isovalent substitutions (Al3+/Co3+) are
  modelled directly; aliovalent cases (e.g. Al3+/Na+) require explicit
  charge-compensating defects in the supercell.
- **Energy rankings are more trustworthy than absolute values.** CHGNet is a
  universal MLIP fitted to DFT; treat E_f differences between sites as the
  primary signal.
- **Single concentration per run.** Re-run with a larger supercell to probe
  dilution effects.
- **MD timescales are short.** The default 25 ps production captures local
  dynamics but not slow diffusion -- treat a non-plateauing MSD as evidence
  that the site is unstable, not as a quantitative diffusion measurement.
