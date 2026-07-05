"""
Helpers for the golden dry-run DAG snapshot test (tests/test_golden_commands.py).

These build a minimal-but-sufficient fixture (BASEDIR with CSVs + a BIDS tree)
that lets `iproc -s setup --dry-run --bids ...` actually reach command
emission (ingest_fieldmap/ingest_anat/ingest_task/recon_all), then normalize
the captured output down to the stable `runscript/...` command lines so the
snapshot doesn't depend on tmp paths, the installed package location, or
wall-clock timestamps.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "golden"


def _codedir():
    """Resolve the installed iproc package directory (== CODEDIR)."""
    import iproc

    return str(Path(iproc.__file__).resolve().parent)


def build_run_dir(tmp_path):
    """
    Materialize a BASEDIR (CSVs + MNI/fsaverage6 stubs) and a minimal BIDS
    tree matching tests/fixtures/golden/scanlist.csv, then render
    TEST01.cfg with {{CODEDIR}}/{{BASEDIR}} filled in.

    Returns a dict with "cfg" (rendered config path) and "bids" (the
    per-subject BIDS directory to pass to `--bids`).
    """
    base = tmp_path / "base"
    base.mkdir()

    # CSVs consumed by iproc.csvHandler
    shutil.copy2(FIXTURES / "tasktype.csv", base / "tasktype.csv")
    shutil.copy2(FIXTURES / "scanlist.csv", base / "scanlist.csv")
    shutil.copy2(FIXTURES / "cluster_requests.csv", base / "cluster_requests.csv")

    # MNI / fsaverage6 stubs referenced by [out_atlas] in the rendered cfg.
    # Not opened during the `setup` stage, but created for completeness/
    # future stages that do read them.
    mni = base / "mni"
    mni.mkdir()
    for fname in (
        "MNI152_T1_2mm.nii.gz",
        "MNI152_T1_2mm_brain.nii.gz",
        "MNI152_T1_2mm_brain_mask.nii.gz",
    ):
        (mni / fname).write_bytes(b"")
    (base / "fsaverage6").mkdir()

    # Minimal BIDS tree. iproc.bids.match_scan_no_to_bids/steps.py glob and
    # regex against `{bids}/ses-{SESSION_ID}/{anat,func,fmap}/...` directly
    # (no `sub-*` level in the internal path building) -- `--bids` is passed
    # the per-subject directory itself.
    bids_root = tmp_path / "bids" / "sub-TEST01"
    ses_dir = bids_root / "ses-ses01"
    anat_dir = ses_dir / "anat"
    func_dir = ses_dir / "func"
    fmap_dir = ses_dir / "fmap"
    for d in (anat_dir, func_dir, fmap_dir):
        d.mkdir(parents=True)

    # ANAT (scanlist ANAT=1 -> SeriesNumber 1). The T1w.json must match
    # `sub-{SUB}_ses-{SES}_run-###_T1w.json` exactly (no extra entities) for
    # match_scan_no_to_bids's regex; the .nii.gz just needs to satisfy
    # anat_from_bids()'s `*_run-###_T1w.nii.gz` glob.
    (anat_dir / "sub-TEST01_ses-ses01_run-001_T1w.json").write_text(
        json.dumps({"SeriesNumber": 1})
    )
    (anat_dir / "sub-TEST01_ses-ses01_acq-mprage_run-001_T1w.nii.gz").write_bytes(b"")

    # FUNC (REST, BLD=5 -> SeriesNumber 5)
    (func_dir / "sub-TEST01_ses-ses01_task-rest_run-001_bold.json").write_text(
        json.dumps({"SeriesNumber": 5})
    )
    (func_dir / "sub-TEST01_ses-ses01_task-rest_run-001_bold.nii.gz").write_bytes(b"")

    # FMAP: Siemens magnitude1 + phasediff (fsl_prepare_fieldmap regime).
    # FMAP_MAG=2 -> SeriesNumber 2, FMAP_PHASE=3 -> SeriesNumber 3.
    (fmap_dir / "sub-TEST01_ses-ses01_magnitude1.json").write_text(
        json.dumps({"SeriesNumber": 2, "Manufacturer": "Siemens"})
    )
    (fmap_dir / "sub-TEST01_ses-ses01_magnitude1.nii.gz").write_bytes(b"")
    (fmap_dir / "sub-TEST01_ses-ses01_phasediff.json").write_text(
        json.dumps(
            {
                "SeriesNumber": 3,
                "Manufacturer": "Siemens",
                "EchoTime1": 0.00492,
                "EchoTime2": 0.00738,
            }
        )
    )
    (fmap_dir / "sub-TEST01_ses-ses01_phasediff.nii.gz").write_bytes(b"")

    # Render the config: fill {{CODEDIR}}/{{BASEDIR}} placeholders.
    template = (FIXTURES / "TEST01.cfg").read_text()
    rendered = template.replace("{{CODEDIR}}", _codedir()).replace(
        "{{BASEDIR}}", str(base)
    )
    cfg_path = tmp_path / "TEST01.cfg"
    cfg_path.write_text(rendered)

    return {"cfg": cfg_path, "bids": bids_root, "base": base}


def run_dry(cfg, bids, stage):
    """
    Invoke the installed `iproc` console entry point in --dry-run mode and
    return combined stdout+stderr text.
    """
    iproc_bin = Path(sys.executable).with_name("iproc")
    if not iproc_bin.exists():
        found = shutil.which("iproc")
        iproc_bin = Path(found) if found else iproc_bin
    cmd = [
        str(iproc_bin),
        "-c",
        str(cfg),
        "-s",
        stage,
        "--executor",
        "local",
        "--dry-run",
        "--bids",
        str(bids),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    combined = result.stdout + result.stderr
    if result.returncode != 0:
        raise AssertionError(
            f"iproc dry-run exited {result.returncode}, expected 0:\n{combined}"
        )
    return combined


_EPOCH_RE = re.compile(r"\d{10,}")
# strips the "[2026-07-05 10:17:11,573][INFO] - iproc.py - " logging prefix
# (see configure_logging()'s log_format), leaving just the message.
_LOG_PREFIX_RE = re.compile(r"^\[[^\]]+\]\[[A-Z]+\] - [\w.]+ - ")


def normalize(text, tmp_path):
    """
    Drop everything except the `runscript/...` command lines (the only
    part of dry-run output that represents the emitted DAG), and scrub the
    volatile bits from those lines: the log timestamp prefix, the tmp run
    directory, the installed package directory (CODEDIR), and
    epoch-timestamp path components (e.g. SCRATCHDIR/<epoch>/...).
    """
    tmp_str = str(tmp_path)
    codedir = _codedir()
    kept = []
    for line in text.splitlines():
        if "runscript" not in line:
            continue
        norm = _LOG_PREFIX_RE.sub("", line)
        norm = norm.replace(tmp_str, "<TMP>")
        norm = norm.replace(codedir, "<CODEDIR>")
        norm = _EPOCH_RE.sub("<EPOCH>", norm)
        kept.append(norm)
    return "\n".join(kept) + ("\n" if kept else "")
