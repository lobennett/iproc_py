import hashlib
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
VENDORED = REPO / "src" / "iproc"
UP = REPO / "third_party" / "iProc-upstream"
FORK = REPO / "third_party" / "iProc-fork"

def _sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

# Files intentionally taken from the fork (neutral env fixes) — must match FORK, differ from UP.
NEUTRAL_FROM_FORK = [
    "runscript/recon_all.sh", "runscript/combine_warps_parallel.sbatch",
    "runscript/combine_warps_parallel_ME.sbatch", "runscript/fs6_project_to_surf.sh",
    "runscript/calculate_nuisance_params.sh", "runscript/fm_unwarp_and_mc_to_midvol.sh",
    "iProc_p4_sbatch_combined.py", "iProc_p4_sbatch_combined_ME.py",
]
# Files with our own edits (compared explicitly, not to a baseline).
# runscript/fmap_from_bids.py adds a GE/Philips Hz→rad/s branch (capability
# upstream lacks); its Siemens/Varian path is byte-behavior-identical to
# upstream. See NOTICE.md / docs/fork-audit.md.
OURS = {"cli/iproc.py", "steps.py", "runscript/fmap_from_bids.py"}

def _iter_upstream_core():
    for f in (UP / "iproc").rglob("*"):
        if f.is_file():
            yield f.relative_to(UP / "iproc").as_posix(), f
    for asset in ["runscript", "configs", "wrappers", "mni_masks", "modwrap.sh",
                  "modules_rocky8.sh", "iProc_p4_sbatch_combined.py",
                  "iProc_p4_sbatch_combined_ME.py", "run_tedana.py", "tedana_loop.py",
                  "dss.sh", "executorcli.py"]:
        up = UP / asset
        if up.is_file():
            yield asset, up
        elif up.is_dir():
            for f in up.rglob("*"):
                if f.is_file():
                    yield f.relative_to(UP).as_posix(), f

@pytest.mark.skipif(not (UP / "iproc").exists(), reason="submodule not checked out")
def test_untouched_core_matches_upstream():
    bad = []
    for rel, up in _iter_upstream_core():
        if rel in OURS or rel in NEUTRAL_FROM_FORK:
            continue
        v = VENDORED / rel
        if not v.exists(): bad.append(f"MISSING {rel}")
        elif _sha(v) != _sha(up): bad.append(f"DIFFERS from upstream {rel}")
    assert not bad, "core drift:\n" + "\n".join(bad)

@pytest.mark.skipif(not (FORK / "iproc").exists(), reason="submodule not checked out")
def test_neutral_files_match_fork_and_differ_from_upstream():
    bad = []
    for rel in NEUTRAL_FROM_FORK:
        v, up, fk = VENDORED / rel, UP / rel, FORK / rel
        if _sha(v) != _sha(fk): bad.append(f"{rel} != fork")
        if _sha(v) == _sha(up): bad.append(f"{rel} unexpectedly == upstream (no fix applied)")
    assert not bad, "neutral-fix drift:\n" + "\n".join(bad)

def test_steps_keeps_upstream_wbonly_names():
    txt = (VENDORED / "steps.py").read_text()
    assert "_wb_resid" not in txt, "fork rename leaked in; upstream uses _wbonly"
    assert txt.count("_wbonly") >= 3
