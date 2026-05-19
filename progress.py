"""
Bottom-pinned progress bar for the workflow.

Each test gets one tqdm bar that stays at the bottom of the terminal until
the test finishes. Bar weights are split across the slow phases:

    doped_relax  5%    one CHGNet relaxation of the doped supercell (if not cached)
    md_setup     1%    constructing the MolecularDynamics object
    md_run      90%    NVT MD steps  (this is the dominant cost)
    analysis    3%     MSD, RDF, coordination, lattice
    report      1%     stability report write

Use `info(msg)` instead of `print()` from inside the workflow so the bar
redraws cleanly underneath your output. CHGNet/torch's own prints will
cause a one-line flicker but the bar is always re-pinned to the bottom.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

from tqdm.auto import tqdm


PHASE_WEIGHTS = {
    "doped_relax": 5,
    "md_setup": 1,
    "md_run": 90,
    "analysis": 3,
    "report": 1,
}
TOTAL_WEIGHT = sum(PHASE_WEIGHTS.values())


def info(msg=""):
    """Print a message above the progress bar without disturbing it."""
    tqdm.write(str(msg), file=sys.stdout)


class TestProgress:
    def __init__(self, bar, total_md_steps):
        self._bar = bar
        self._total_md_steps = max(total_md_steps, 1)
        self._md_units_done = 0

    def phase(self, key):
        """Advance the bar by the weight of a discrete phase."""
        weight = PHASE_WEIGHTS.get(key, 0)
        if weight > 0:
            self._bar.update(weight)

    def md(self, current_md_step):
        """Advance the bar to reflect MD progress (0..total_md_steps)."""
        if current_md_step <= 0:
            return
        target = int(current_md_step / self._total_md_steps * PHASE_WEIGHTS["md_run"])
        target = min(target, PHASE_WEIGHTS["md_run"])
        delta = target - self._md_units_done
        if delta > 0:
            self._bar.update(delta)
            self._md_units_done = target

    def md_complete(self):
        """Fill any remaining MD fraction (e.g. when MD is restored from cache)."""
        remaining = PHASE_WEIGHTS["md_run"] - self._md_units_done
        if remaining > 0:
            self._bar.update(remaining)
            self._md_units_done = PHASE_WEIGHTS["md_run"]

    def info(self, msg):
        info(msg)


@contextmanager
def loop_progress_bar(total, desc):
    """Simple bottom-pinned bar that ticks once per iteration."""
    bar = tqdm(
        total=total,
        desc=desc,
        bar_format=(
            "{desc} |{bar}| {n_fmt}/{total_fmt}  {percentage:5.1f}%  "
            "[elapsed {elapsed}, remaining {remaining}]"
        ),
        position=0,
        leave=True,
        dynamic_ncols=True,
        ascii=" =",
        file=sys.stdout,
        mininterval=0.2,
    )
    try:
        yield bar
    finally:
        bar.refresh()
        bar.close()


@contextmanager
def test_progress_bar(test_name, total_md_steps):
    """Context manager that yields a TestProgress with the bar pinned at bottom."""
    bar = tqdm(
        total=TOTAL_WEIGHT,
        desc=test_name,
        bar_format=(
            "{desc} |{bar}| {percentage:5.1f}%  "
            "[elapsed {elapsed}, remaining {remaining}]"
        ),
        position=0,
        leave=True,
        dynamic_ncols=True,
        ascii=" =",
        file=sys.stdout,
        mininterval=0.2,
    )
    try:
        yield TestProgress(bar, total_md_steps)
    finally:
        bar.refresh()
        bar.close()
