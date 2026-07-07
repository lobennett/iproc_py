"""steps.recon_all in T1_AVERAGE mode emits exactly one recon job whose command
lists every reoriented T1, keyed by the representative fs_sub. Uses the golden
dry-run harness with a 2-T1 fixture."""
import json

import pytest

from tests._golden_env import build_run_dir, run_dry

pytest.importorskip("bids")


def _make_average_fixture(tmp_path):
    ctx = build_run_dir(tmp_path)
    base, cfg, bids = ctx["base"], ctx["cfg"], ctx["bids"]

    # add a 2nd T1w (run-002, series 2)
    anat = bids / "ses-ses01" / "anat"
    (anat / "sub-TEST01_ses-ses01_run-002_T1w.json").write_text(
        json.dumps({"SeriesNumber": 2})
    )
    (anat / "sub-TEST01_ses-ses01_acq-mprage_run-002_T1w.nii.gz").write_bytes(b"")

    # scanlist: two ANAT rows (series 1 and 2), both Analyze=1
    (base / "scanlist.csv").write_text(
        "SUBJID,SESSION_ID,Analyze,BLD,TYPE,ANAT,FMAP_MAG,FMAP_PHASE,"
        "FMAP_AP,FMAP_PA,T2,T2_SESSION_ID\n"
        "TEST01,ses01,1,1,ANAT,1,0,0,0,0,0,0\n"
        "TEST01,ses01,1,1,ANAT,2,0,0,0,0,0,0\n"
        "TEST01,ses01,1,5,REST,0,2,3,0,0,0,0\n"
        "TEST01,ses01,1,0,FMAP,0,2,3,0,0,0,0\n"
    )

    # cfg: representative scan 002 + enable averaging
    cfg.write_text(cfg.read_text().replace(
        "T1_SCAN_NO=001", "T1_SCAN_NO=002\nT1_AVERAGE=true"))
    return cfg, bids


def test_average_mode_emits_one_job_listing_all_t1s(tmp_path):
    cfg, bids = _make_average_fixture(tmp_path)
    out = run_dry(cfg, bids, "setup")
    recon = [ln for ln in out.splitlines() if "recon_all.sh" in ln]
    assert len(recon) == 1, out
    line = recon[0]
    assert "'ses01_002'" in line                       # representative fs_sub
    assert "ANAT_001" in line and "mpr001_reorient" in line
    assert "ANAT_002" in line and "mpr002_reorient" in line
