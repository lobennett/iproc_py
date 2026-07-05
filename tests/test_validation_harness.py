import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_harness_parses():
    r = subprocess.run(
        ["bash", "-n", str(REPO / "scripts" / "validate_against_baseline.sh")],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


def test_diff_nifti_fallback_present():
    assert (REPO / "scripts" / "diff_tools" / "diff-nifti.py").exists()
