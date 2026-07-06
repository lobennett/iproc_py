"""iProc BIDS-App package.

Houses the importable core of the BIDS discover/generate pipeline that used to
live as loose scripts under ``bids_setup/``. Moving the logic here makes it
importable and wheel-packaged (a prerequisite for the BIDS-App console entry
point); the ``bids_setup/*.py`` files remain as thin shims that call into these
modules so the documented ``uv run bids_setup/bids_discover.py ...`` usage keeps
working unchanged.
"""
from __future__ import annotations

import re
from typing import Any


def _num_key(value: Any):
    """Sort key that orders numeric-looking labels numerically, others lexically.

    Ensures run-10 sorts after run-2 and ses-10 after ses-2 instead of lexically
    (where "10" < "2"). Numeric labels sort before non-numeric ones; both groups
    are stable. Shared by discover and generate so session/run ordering is
    consistent across both modules' output and error/gate messages.
    """
    if value is None:
        return (0, 0.0, "")
    s = str(value)
    m = re.fullmatch(r"0*(\d+)", s)
    if m:
        return (0, float(m.group(1)), "")
    return (1, 0.0, s)


__all__ = ["_num_key"]
