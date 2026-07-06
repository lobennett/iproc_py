import hashlib
import sys
from pathlib import Path
import pytest

REPO = Path(__file__).resolve().parents[1]
VENDORED = REPO / "src" / "iproc"
UP = REPO / "third_party" / "iProc-upstream"
FORK = REPO / "third_party" / "iProc-fork"

def _sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def _is_compiled_artifact(f):
    """True for anything that isn't real source: __pycache__ contents and
    compiled bytecode. If something ever compiles a .pyc into the upstream
    submodule tree (e.g. a stray `python -m py_compile` or an import that
    writes __pycache__), rglob("*") would otherwise pick it up and report a
    spurious DIFFERS/MISSING failure since no .pyc exists on the vendored
    side. Real source-file drift must still be caught."""
    return "__pycache__" in f.parts or f.suffix in (".pyc", ".pyo")

# Files intentionally taken from the fork — must match FORK, differ from UP.
# Most are neutral env/portability fixes (see docs/fork-audit.md bucket A).
# fm_unwarp_and_mc_to_midvol.sh / iProc_p4_sbatch_combined[_ME].py are NOT
# numerics-neutral: they are a documented, default-on, intentional correctness
# deviation (fslnvols/MAT-count NUMVOL override) that is a no-op on
# fixed-length runs but changes behavior on variable-length runs — see
# docs/fork-audit.md bucket A2. Either way they must still match the fork's
# applied fix and differ from upstream's un-fixed version.
NEUTRAL_FROM_FORK = [
    "runscript/recon_all.sh", "runscript/combine_warps_parallel.sbatch",
    "runscript/combine_warps_parallel_ME.sbatch", "runscript/fs6_project_to_surf.sh",
    "runscript/calculate_nuisance_params.sh", "runscript/fm_unwarp_and_mc_to_midvol.sh",
    "iProc_p4_sbatch_combined.py", "iProc_p4_sbatch_combined_ME.py",
]
# Files with our own edits (compared explicitly, not to a baseline).
# runscript/fmap_from_bids.py adds a GE/Philips Hz→rad/s branch (capability
# upstream lacks); its Siemens/Varian path is byte-behavior-identical to
# upstream. bids/__init__.py (match_scan_no_to_bids) makes per-session modality
# globs conditional so a session missing a modality (e.g. cross-session anat:
# T1 in ses-struct*, BOLD/fmap in ses-func*) no longer raises IOError;
# behavior-preserving for same-session datasets. See NOTICE.md /
# docs/fork-audit.md.
OURS = {"cli/iproc.py", "steps.py", "runscript/fmap_from_bids.py",
        "bids/__init__.py"}

def _iter_upstream_core():
    for f in (UP / "iproc").rglob("*"):
        if f.is_file() and not _is_compiled_artifact(f):
            yield f.relative_to(UP / "iproc").as_posix(), f
    for asset in ["runscript", "configs", "wrappers", "mni_masks", "modwrap.sh",
                  "modules_rocky8.sh", "iProc_p4_sbatch_combined.py",
                  "iProc_p4_sbatch_combined_ME.py", "run_tedana.py", "tedana_loop.py",
                  "dss.sh", "executorcli.py"]:
        up = UP / asset
        if up.is_file():
            if not _is_compiled_artifact(up):
                yield asset, up
        elif up.is_dir():
            for f in up.rglob("*"):
                if f.is_file() and not _is_compiled_artifact(f):
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


# ---------------------------------------------------------------------------
# _iter_upstream_core must ignore compiled artifacts so a stray __pycache__ or
# .pyc/.pyo committed/compiled into the upstream submodule tree cannot trigger
# a spurious MISSING/DIFFERS failure (there is never a matching compiled
# artifact on the vendored side to compare against). Real source-file drift
# must still be detected.
# ---------------------------------------------------------------------------

def _build_fake_upstream(root):
    """Build a minimal fake upstream tree under `root` mirroring the shape
    `_iter_upstream_core` walks: an `iproc/` package dir plus one top-level
    asset dir (`runscript/`)."""
    iproc_dir = root / "iproc"
    iproc_dir.mkdir(parents=True)
    (iproc_dir / "real_source.py").write_text("x = 1\n")

    pycache = iproc_dir / "__pycache__"
    pycache.mkdir()
    (pycache / "real_source.cpython-311.pyc").write_bytes(b"\x00\x01fake-bytecode")

    (iproc_dir / "stray.pyo").write_bytes(b"fake-pyo")

    runscript_dir = root / "runscript"
    runscript_dir.mkdir()
    (runscript_dir / "helper.sh").write_text("#!/bin/bash\necho hi\n")
    nested_pycache = runscript_dir / "__pycache__"
    nested_pycache.mkdir()
    (nested_pycache / "helper.cpython-311.pyc").write_bytes(b"\x00\x01fake-bytecode")


def test_iter_upstream_core_skips_pycache_and_pyc(tmp_path, monkeypatch):
    _build_fake_upstream(tmp_path)
    monkeypatch.setattr(sys.modules[__name__], "UP", tmp_path)

    rels = {rel for rel, _ in _iter_upstream_core()}

    assert "real_source.py" in rels
    assert "runscript/helper.sh" in rels
    assert not any("__pycache__" in rel for rel in rels)
    assert not any(rel.endswith((".pyc", ".pyo")) for rel in rels)


def test_iter_upstream_core_still_catches_real_source_drift(tmp_path, monkeypatch):
    """Compiled-artifact filtering must not blind the test to genuine drift in
    a real source file sitting right next to a __pycache__ dir."""
    up_root = tmp_path / "up"
    vendored_root = tmp_path / "vendored"
    _build_fake_upstream(up_root)
    vendored_root.mkdir()
    # Vendored copy intentionally differs from upstream's real_source.py.
    (vendored_root / "real_source.py").write_text("x = 2\n")

    monkeypatch.setattr(sys.modules[__name__], "UP", up_root)

    bad = []
    for rel, up in _iter_upstream_core():
        if rel == "runscript/helper.sh":
            continue  # not vendored in this fake tree
        v = vendored_root / rel
        if not v.exists():
            bad.append(f"MISSING {rel}")
        elif _sha(v) != _sha(up):
            bad.append(f"DIFFERS from upstream {rel}")

    assert bad == ["DIFFERS from upstream real_source.py"], bad
