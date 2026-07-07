"""Execution test for runscript/recon_all.sh's multi-input averaging loop.

Stubs `python`, `mri_convert`, and `recon-all` on PATH so the script runs
without FreeSurfer/FSL (and without Linux-only os.sched_getaffinity). Verifies
that N trailing T1 inputs become orig/001.mgz .. 00N.mgz, and that a single
input still yields exactly orig/001.mgz."""
import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "src" / "iproc" / "runscript" / "recon_all.sh"


def _stub(path: Path, body: str):
    path.write_text("#!/bin/bash\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run_recon(tmp_path, t1s):
    bind = tmp_path / "bin"
    bind.mkdir()
    # cpus probe -> constant; mri_convert -> copy src to dst; recon-all -> no-op
    # ln -> no-op (script uses GNU-only `ln -sfT`; macOS/BSD ln lacks -T and
    # this step is irrelevant to what's under test, the orig/*.mgz layout)
    _stub(bind / "python", 'echo 4')
    _stub(bind / "mri_convert", 'cp "$1" "$2"')
    _stub(bind / "recon-all", 'exit 0')
    _stub(bind / "ln", 'exit 0')
    scratch = tmp_path / "scratch"
    subjects = tmp_path / "subjects"
    scratch.mkdir()
    subjects.mkdir()
    fsavg = tmp_path / "fsaverage6"
    fsavg.mkdir()
    env = dict(os.environ, PATH=f"{bind}:{os.environ['PATH']}")
    args = ["SUBJ", "sess_001", str(t1s[0]), "__none__", str(subjects),
            str(fsavg), str(scratch), str(REPO / "src" / "iproc")]
    args += [str(p) for p in t1s[1:]]
    r = subprocess.run(["bash", str(SCRIPT), *args],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    return sorted(p.name for p in (subjects / "sess_001" / "mri" / "orig").glob("*.mgz"))


def _make_t1s(tmp_path, n):
    out = []
    for i in range(1, n + 1):
        p = tmp_path / f"t1_{i}.nii.gz"
        p.write_bytes(b"x")
        out.append(p)
    return out


def test_single_input_yields_one_orig(tmp_path):
    assert _run_recon(tmp_path, _make_t1s(tmp_path, 1)) == ["001.mgz"]


def test_three_inputs_yield_three_orig(tmp_path):
    assert _run_recon(tmp_path, _make_t1s(tmp_path, 3)) == \
        ["001.mgz", "002.mgz", "003.mgz"]
