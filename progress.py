"""
Bottom-pinned progress bar for the workflow.

Each test gets one tqdm bar that stays at the bottom of the terminal until
the test finishes. Bar weights are split across the slow phases:

    doped_relax  5%
    md_setup     1%
    md_run      90%
    analysis     3%
    report       1%

Use `info(msg)` instead of `print()` from inside the workflow so the bar
redraws cleanly underneath your output. CHGNet/torch's own prints will
cause a brief flicker but tqdm immediately re-pins the bar to the bottom.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

from tqdm import tqdm


PHASE_WEIGHTS = {
    "doped_relax": 5,
    "md_setup": 1,
    "md_run": 90,
    "analysis": 3,
    "report": 1,
}
TOTAL_WEIGHT = sum(PHASE_WEIGHTS.values())


def info(msg=""):
    tqdm.write(str(msg), file=sys.stderr)


def _make_bar(**kwargs):
    defaults = dict(
        position=0,
        leave=True,
        ncols=100,
        mininterval=0.1,
        miniters=1,
        file=sys.stderr,
        ascii=False,
    )
    defaults.update(kwargs)
    return tqdm(**defaults)


@contextmanager
def loop_progress_bar(total, desc):
    bar = _make_bar(
        total=total,
        desc=desc,
        bar_format=(
            "{desc}: |{bar}| {n_fmt}/{total_fmt}  {percentage:5.1f}%  "
            "[elapsed {elapsed}, remaining {remaining}]"
        ),
    )
    bar.refresh()
    try:
        yield bar
    finally:
        bar.refresh()
        bar.close()


class TestProgress:
    def __init__(self, bar, total_md_steps):
        self._bar = bar
        self._total_md_steps = max(total_md_steps, 1)
        self._md_units_done = 0

    def phase(self, key):
        weight = PHASE_WEIGHTS.get(key, 0)
        if weight > 0:
            self._bar.update(weight)
            self._bar.refresh()

    def md(self, current_md_step):
        if current_md_step <= 0:
            return
        target = int(current_md_step / self._total_md_steps * PHASE_WEIGHTS["md_run"])
        target = min(target, PHASE_WEIGHTS["md_run"])
        delta = target - self._md_units_done
        if delta > 0:
            self._bar.update(delta)
            self._md_units_done = target
            self._bar.refresh()

    def md_complete(self):
        remaining = PHASE_WEIGHTS["md_run"] - self._md_units_done
        if remaining > 0:
            self._bar.update(remaining)
            self._md_units_done = PHASE_WEIGHTS["md_run"]
            self._bar.refresh()

    def info(self, msg):
        info(msg)


@contextmanager
def test_progress_bar(test_name, total_md_steps):
    bar = _make_bar(
        total=TOTAL_WEIGHT,
        desc=test_name,
        bar_format=(
            "{desc}: |{bar}| {percentage:5.1f}%  "
            "[elapsed {elapsed}, remaining {remaining}]"
        ),
    )
    bar.refresh()
    try:
        yield TestProgress(bar, total_md_steps)
    finally:
        bar.refresh()
        bar.close()
