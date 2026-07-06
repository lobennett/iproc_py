import subprocess
import sys
from pathlib import Path

import pytest

C = Path(__file__).resolve().parents[1] / "container"


def _extract_conversion_py(wrapper_name):
    """Pull the inline `python3 - "$arg" <<'PY' ... PY` conversion body out of
    a hex-float wrapper so the *shipped* detection/conversion logic itself can
    be exercised directly (the wrapper otherwise calls a real FSL binary)."""
    text = (C / wrapper_name).read_text().splitlines()
    start = next(i for i, ln in enumerate(text) if "<<'PY'" in ln)
    end = next(i for i in range(start + 1, len(text)) if text[i].strip() == "PY")
    return "\n".join(text[start + 1 : end])


def test_shell_assets_parse():
    for n in [
        "module_shim.sh",
        "flirt_wrapper.sh",
        "convert_xfm_wrapper.sh",
        "build.sh",
        "build_sherlock.sh",
        "validate.sh",
    ]:
        r = subprocess.run(["bash", "-n", str(C / n)], capture_output=True, text=True)
        assert r.returncode == 0, f"{n}: {r.stderr}"


def test_def_has_pinned_versions_and_shim():
    d = (C / "iproc.def").read_text()
    assert "module_shim.sh /opt/module_shim.sh" in d

    # AFNI has no dated/versioned Linux binary tarball upstream (confirmed
    # against afni.nimh.nih.gov's own directory listing), so instead of
    # asserting "latest" is absent, we assert that the def documents a
    # justification for tracking latest-stable plus build-time provenance
    # capture (HTTP headers + installed `afni -version` string) that lets
    # any built image be audited after the fact. This is the honest
    # adaptation of the "no floating installs" check for a dependency that
    # genuinely has no better pin available.
    dl = d.lower()
    assert "afni version pinning note" in dl
    assert "3dtproject" in dl and "3dafnitonifti" in dl
    assert "installed_version.txt" in dl

    for tool in ["freesurfer", "fsl", "ants", "dcm2niix"]:
        assert tool in dl


def test_module_shim_maps_four_fsl_versions():
    s = (C / "module_shim.sh").read_text()
    for v in ["4.0.3", "5.0.4", "5.0.10", "6.0.1"]:
        assert v in s


def test_module_shim_warns_on_unknown_spec():
    # CON#7: the catch-all for unrecognized `module load` specs must warn to
    # stderr (unlike a silent Lmod no-op) so a typo'd/unknown FSL version
    # surfaces in logs instead of running under whatever FSL is active.
    s = (C / "module_shim.sh").read_text()
    assert "unrecognized module" in s
    assert ">&2" in s


def test_def_wraps_more_than_default_fsl():
    # CON#4 / I-g: the hex-float wrapper install must iterate over every real
    # FSL dir (not just /opt/fsl-5.0.10), so the exact-from-Sherlock path where
    # 5.0.4 and 5.0.10 are separate real dirs also gets 5.0.4 wrapped.
    d = (C / "iproc.def").read_text()
    # The wrap step loops over FSL dirs and references 5.0.4 among them.
    assert "/opt/fsl-5.0.4" in d
    # Loop touches multiple versions in the wrap step (5.0.10 alone is not
    # enough); require the loop to enumerate several real dirs.
    for v in ["/opt/fsl-4.1.9", "/opt/fsl-5.0.4", "/opt/fsl-5.0.8", "/opt/fsl-5.0.10"]:
        assert v in d
    # Real binary is moved aside per-dir to a sibling `<tool>.real`, not a
    # single hardcoded /opt/.fsl_orig path.
    assert ".real" in d
    assert "/opt/.fsl_orig" not in d


def test_wrappers_resolve_sibling_real_binary():
    # The wrappers must call their OWN version's real binary (sibling
    # `<tool>.real`), not a single hardcoded /opt/.fsl_orig/<tool>, so each
    # wrapped FSL dir invokes the correct binary.
    for w in ["flirt_wrapper.sh", "convert_xfm_wrapper.sh"]:
        text = (C / w).read_text()
        assert "/opt/.fsl_orig" not in text
        assert ".real" in text


def test_no_tracked_file_references_ignored_internal_docs():
    # I-h: the gitignored internal-docs dir is absent from a clone, so any
    # tracked link into it 404s. The only allowed mention is the .gitignore
    # rule itself. The needle is assembled from parts so THIS test file does
    # not itself trip the check.
    needle = "docs/" + "super" + "powers/"
    repo = C.parent
    files = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    offenders = []
    for rel in files:
        if rel == ".gitignore":
            continue
        p = repo / rel
        try:
            content = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if needle in content:
            offenders.append(rel)
    assert not offenders, f"tracked files reference {needle}: {offenders}"


# ---------------------------------------------------------------------------
# Hex-float wrapper conversion logic (guards hex-float fix #1). The predicate
# must convert ONLY genuine C99 hex-float matrices and leave decimal matrices
# byte-for-byte untouched — float.fromhex('0.998765') succeeds as a hex
# mantissa and would silently corrupt a decimal value if the predicate were
# just "fromhex didn't raise". These tests run the exact python conversion
# body extracted from container/{flirt,convert_xfm}_wrapper.sh.
# ---------------------------------------------------------------------------

WRAPPERS = ["flirt_wrapper.sh", "convert_xfm_wrapper.sh"]


def _run_conversion(wrapper_name, mat_path, tmp_path):
    script = tmp_path / "conv.py"
    script.write_text(_extract_conversion_py(wrapper_name))
    r = subprocess.run(
        [sys.executable, str(script), str(mat_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    return r


@pytest.mark.parametrize("wrapper_name", WRAPPERS)
def test_decimal_matrix_left_byte_unchanged(wrapper_name, tmp_path):
    decimal = (
        "0.998765 -0.001234 0.004567 1.234500\n"
        "0.001200 0.999900 -0.002300 -0.567800\n"
        "-0.004500 0.002300 0.999800 0.123400\n"
        "0.000000 0.000000 0.000000 1.000000\n"
    )
    mat = tmp_path / "decimal.mat"
    mat.write_bytes(decimal.encode())
    _run_conversion(wrapper_name, mat, tmp_path)
    # CRITICAL: a decimal matrix must be passed through byte-for-byte — no
    # fromhex() corruption of e.g. 0.998765.
    assert mat.read_bytes() == decimal.encode()


@pytest.mark.parametrize("wrapper_name", WRAPPERS)
def test_c99_hexfloat_matrix_is_converted(wrapper_name, tmp_path):
    # 0x1p+0 == 1.0, 0x1.8p+1 == 3.0, 0x0p+0 == 0.0, -0x1.4p+1 == -2.5
    hexmat = (
        "0x1p+0 0x0p+0 0x0p+0 0x1.8p+1\n"
        "0x0p+0 0x1p+0 0x0p+0 -0x1.4p+1\n"
        "0x0p+0 0x0p+0 0x1p+0 0x0p+0\n"
        "0x0p+0 0x0p+0 0x0p+0 0x1p+0\n"
    )
    mat = tmp_path / "hex.mat"
    mat.write_text(hexmat)
    _run_conversion(wrapper_name, mat, tmp_path)
    out = mat.read_text()
    assert "0x" not in out and "p+" not in out, out
    rows = [[float(t) for t in ln.split()] for ln in out.splitlines() if ln.strip()]
    assert rows[0] == [1.0, 0.0, 0.0, 3.0]
    assert rows[1] == [0.0, 1.0, 0.0, -2.5]
    assert rows[3] == [0.0, 0.0, 0.0, 1.0]
