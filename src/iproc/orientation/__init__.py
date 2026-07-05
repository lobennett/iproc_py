"""T1->MNI orientation/registration policy.

Default = upstream iProc behavior (fslswapdim + upstream FLIRT search). The fork's
already-RAS assumption (no swap, +-30 search) is available ONLY as an explicit
opt-in; when we detect an already-RAS T1 we warn but still default to upstream.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import nibabel as nib

logger = logging.getLogger(__name__)

UPSTREAM_SEARCH = (-180, 180)
FORK_SEARCH = (-30, 30)


@dataclass
class Policy:
    swapdim: bool
    flirt_search: tuple
    source: str   # "upstream" | "fork"


def registration_policy(t1_path: str, config: dict | None = None) -> Policy:
    config = config or {}
    mode = config.get("orientation_mode", "upstream")
    try:
        axcodes = "".join(nib.aff2axcodes(nib.load(str(t1_path)).affine))
    except Exception as e:  # noqa: BLE001
        logger.warning("[orientation] could not read %s: %s; assuming non-RAS", t1_path, e)
        axcodes = ""
    if axcodes == "RAS":
        logger.warning("[orientation] %s is already RAS+. Upstream applies fslswapdim; "
                       "if T1->MNI misregisters, retry with orientation_mode=fork_no_swap. "
                       "VERIFY registration QC.", t1_path)
    if mode == "fork_no_swap":
        return Policy(swapdim=False, flirt_search=FORK_SEARCH, source="fork")
    return Policy(swapdim=True, flirt_search=UPSTREAM_SEARCH, source="upstream")
