import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROFILES = REPO / "src" / "iproc" / "data" / "site_profiles"
LAUNCHER = REPO / "launch" / "iproc-run"


def test_launcher_parses():
    r = subprocess.run(
        ["bash", "-n", str(LAUNCHER)], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stderr


def test_dry_run_emits_sbatch_apptainer(tmp_path):
    subs = tmp_path / "subs.txt"
    subs.write_text("s01\n")
    r = subprocess.run(
        [
            str(LAUNCHER),
            str(PROFILES / "generic-slurm.yaml"),
            str(subs),
            "setup",
            "--bids-root",
            str(tmp_path),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "sbatch" in out and "apptainer exec" in out
    assert "--partition normal" in out or "--partition=normal" in out
    assert "--time 24:00:00" in out or "24:00:00" in out  # setup override applied
    assert "--cpus-per-task 16" in out or "16" in out


def test_dry_run_non_setup_stage_uses_default_resources(tmp_path):
    subs = tmp_path / "subs.txt"
    subs.write_text("s01\n")
    r = subprocess.run(
        [
            str(LAUNCHER),
            str(PROFILES / "generic-slurm.yaml"),
            str(subs),
            "combine_and_apply_warp",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "--mem 64G" in out
    assert "--cpus-per-task 8" in out
    assert "--partition normal" in out or "--partition=normal" in out


def test_setup_without_bids_root_fails(tmp_path):
    subs = tmp_path / "subs.txt"
    subs.write_text("s01\n")
    r = subprocess.run(
        [
            str(LAUNCHER),
            str(PROFILES / "generic-slurm.yaml"),
            str(subs),
            "setup",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "bids-root" in (r.stdout + r.stderr).lower()


def test_sherlock_setup_uses_long_russpold_partition(tmp_path):
    subs = tmp_path / "subs.txt"
    subs.write_text("s01\n")
    r = subprocess.run(
        [
            str(LAUNCHER),
            str(PROFILES / "sherlock.yaml"),
            str(subs),
            "setup",
            "--bids-root",
            str(tmp_path),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "--partition russpold" in out or "--partition=russpold" in out
    assert "--time 24:00:00" in out
    assert "--cpus-per-task 16" in out


def test_sherlock_non_long_stage_uses_default_normal_partition(tmp_path):
    subs = tmp_path / "subs.txt"
    subs.write_text("s01\n")
    r = subprocess.run(
        [
            str(LAUNCHER),
            str(PROFILES / "sherlock.yaml"),
            str(subs),
            "combine_and_apply_warp",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "--partition normal" in out or "--partition=normal" in out
    assert "russpold" not in out
