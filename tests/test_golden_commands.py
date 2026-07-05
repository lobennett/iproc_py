import os
from pathlib import Path

import pytest

from tests._golden_env import build_run_dir, run_dry, normalize

REPO = Path(__file__).resolve().parents[1]
GOLDEN = REPO / "tests" / "golden" / "setup_baseline.txt"
REGEN = os.environ.get("IPROC_REGEN_GOLDEN") == "1"


def test_setup_dry_run_matches_golden(tmp_path):
    ctx = build_run_dir(tmp_path)
    norm = normalize(run_dry(ctx["cfg"], ctx["bids"], "setup"), tmp_path)
    assert "runscript" in norm, "no runscript commands emitted"
    if REGEN or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(norm)
        pytest.skip("golden regenerated")
    assert norm == GOLDEN.read_text(), (
        "dry-run command set changed; regen with IPROC_REGEN_GOLDEN=1 and review"
    )
