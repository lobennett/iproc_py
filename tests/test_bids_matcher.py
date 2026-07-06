"""match_scan_no_to_bids (pybids rewrite) — works on an inheritance-style BIDS
dataset (NO per-run sidecars) with cross-session anat (T1 in a struct session,
BOLD/fmap in a func session), as with MSC on read-only OAK."""
from pathlib import Path
import textwrap
import pytest

from iproc.config import Config
from iproc import csvHandler
from iproc import bids as ibids

pytest.importorskip("bids")  # pybids in the [bids] extra


def _touch(p: Path, content: str = ""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _build_bids(root: Path):
    _touch(root / "dataset_description.json",
           '{"Name":"t","BIDSVersion":"1.9.0"}')
    # inherited, root-level bold sidecar (no per-run sidecars anywhere)
    _touch(root / "task-restingstate_bold.json",
           '{"TaskName":"restingstate","RepetitionTime":2.2}')
    s = root / "sub-01"
    # anat lives in a STRUCT session
    _touch(s / "ses-struct01" / "anat" / "sub-01_ses-struct01_run-01_T1w.nii.gz")
    # BOLD + fmap live in a FUNC session (2 runs), NO per-run json
    f = s / "ses-func01" / "func"
    _touch(f / "sub-01_ses-func01_task-restingstate_run-01_bold.nii.gz")
    _touch(f / "sub-01_ses-func01_task-restingstate_run-02_bold.nii.gz")
    m = s / "ses-func01" / "fmap"
    _touch(m / "sub-01_ses-func01_magnitude1.nii.gz")
    _touch(m / "sub-01_ses-func01_magnitude2.nii.gz")
    _touch(m / "sub-01_ses-func01_phasediff.nii.gz")


def _scans(tmp: Path):
    cfg = tmp / "s.cfg"
    cfg.write_text(textwrap.dedent("""\
        [iproc]
        SUB=01
        BASEDIR=/tmp/x
        [template]
        MIDVOL_SESS=func01
        MIDVOL_BOLDNO=004
        MIDVOL_VOLNO=50
        FD_THRESH=0.4
        FD_LABEL=0p4
        [fmap]
        PREPTOOL=fsl_prepare_fieldmap
        [out_atlas]
        RESOLUTION=222
        """))
    tasktype = tmp / "tasktype.csv"
    tasktype.write_text("TYPE,TR,SKIP,SMOOTHING,NUMVOL,NUMECHOS\nRESTINGSTATE,2.2,4,6,50,1\n")
    scanlist = tmp / "scanlist.csv"
    scanlist.write_text(
        "SUBJID,SESSION_ID,Analyze,BLD,TYPE,ANAT,FMAP_MAG,FMAP_PHASE,FMAP_AP,FMAP_PA,T2,T2_SESSION_ID\n"
        "01,struct01,1,0,ANAT,51,0,0,0,0,0,0\n"
        "01,func01,1,4,RESTINGSTATE,51,2,3,0,0,0,0\n"
        "01,func01,1,5,RESTINGSTATE,51,2,3,0,0,0,0\n"
        "01,func01,1,0,FMAP,0,2,3,0,0,0,0\n")
    c = Config(); c.parse(str(cfg))
    s = csvHandler.scansHandler(c)
    s.ingest_task_csv(str(tasktype))
    s.ingest_bold_csv(str(scanlist))
    return s


def test_matcher_inheritance_cross_session(tmp_path):
    root = tmp_path / "ds"
    _build_bids(root)
    scans = _scans(tmp_path)

    ibids.match_scan_no_to_bids(str(root / "sub-01"), scans)

    func = scans.scan_by_session["func01"]
    struct = scans.scan_by_session["struct01"]

    # BOLD rows (BLD 4,5) map to BIDS runs 01,02 by order — no SeriesNumber
    # needed; zero-padding preserved from the filename (steps.py globs run-{ID})
    assert func.bold_scans[4]["BIDS_ID"] == "01"
    assert func.bold_scans[5]["BIDS_ID"] == "02"
    assert func.bold_scans[4]["FMAP_DIR"] == "FMAP"

    # cross-session anat: T1 in struct01 gets its own run
    assert struct.anat_scans['51']["BIDS_ID"] == "01"

    # fmap: FIRST = magnitude(s), SECOND = phasediff
    fm = list(func.fmap_scans.values())[0]
    first = fm["FIRST_BIDS_FNAME"]
    first_list = first if isinstance(first, list) else [first]
    assert any("magnitude" in x for x in first_list)
    assert fm["SECOND_BIDS_FNAME"].endswith("phasediff.nii.gz")
    assert fm["DIR"] == "FMAP"
