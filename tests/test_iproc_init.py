import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "launch" / "iproc-init"


def test_init_writes_valid_profile(tmp_path):
    out = tmp_path / "site.yaml"
    r = subprocess.run(
        [
            sys.executable,
            str(INIT),
            "--out",
            str(out),
            "--non-interactive",
            "--name",
            "mysite",
            "--container",
            "/c/iproc.sif",
            "--output-root",
            "/data/out",
            "--partition",
            "gpu",
            "--bind",
            "/data:/data",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    p = yaml.safe_load(out.read_text())
    assert p["name"] == "mysite"
    assert p["container"] == "/c/iproc.sif"
    assert p["partitions"]["default"] == "gpu"
    assert "/data:/data" in p["binds"]
    assert "setup" in p["resources"]  # sensible defaults included


def test_init_non_interactive_defaults_and_schema(tmp_path):
    """Defaults fill in sensibly, and the emitted profile matches the schema
    launch/iproc-run consumes (same top-level keys as the shipped profiles)."""
    out = tmp_path / "site.yaml"
    r = subprocess.run(
        [
            sys.executable,
            str(INIT),
            "--out",
            str(out),
            "--non-interactive",
            "--name",
            "labcluster",
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    p = yaml.safe_load(out.read_text())

    # Same top-level keys as src/iproc/data/site_profiles/*.yaml.
    expected_keys = {
        "name",
        "scheduler",
        "container",
        "binds",
        "storage",
        "partitions",
        "resources",
        "fsl",
        "modules",
    }
    assert expected_keys.issubset(p.keys())

    assert p["scheduler"] == "slurm"
    assert isinstance(p["binds"], list)
    assert "code_root" in p["storage"]
    assert "output_root" in p["storage"]
    assert p["partitions"]["default"]
    assert p["fsl"]["mode"] in ("mapped", "exact")
    assert isinstance(p["modules"], list)

    # Per-stage resource defaults matching generic-slurm.yaml.
    resources = p["resources"]
    assert resources["default"] == {"time": "08:00:00", "mem": "32G", "cpus": 4}
    assert resources["setup"]["time"] == "24:00:00"
    assert resources["setup"]["mem"] == "32G"
    assert resources["setup"]["cpus"] == 16
    assert resources["combine_and_apply_warp"]["time"] == "08:00:00"
    assert resources["combine_and_apply_warp"]["mem"] == "64G"
    assert resources["combine_and_apply_warp"]["cpus"] == 8


def test_init_missing_out_flag_fails(tmp_path):
    r = subprocess.run(
        [sys.executable, str(INIT), "--non-interactive", "--name", "x"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0


def test_init_help():
    r = subprocess.run(
        [sys.executable, str(INIT), "--help"], capture_output=True, text=True
    )
    assert r.returncode == 0
    assert "--non-interactive" in r.stdout
