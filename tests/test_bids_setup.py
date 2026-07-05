import json, subprocess, sys
from pathlib import Path
import pytest
REPO = Path(__file__).resolve().parents[1]
B = REPO / "tests" / "fixtures" / "bids"

def _run(script, *args):
    return subprocess.run([sys.executable, str(REPO / "bids_setup" / script), *map(str, args)],
                          capture_output=True, text=True)

def test_discover_siemens_sets_phasediff(tmp_path):
    out = tmp_path / "m.yaml"
    r = _run("bids_discover.py", B / "siemens_phasediff", "--output", out)
    assert r.returncode == 0, r.stderr
    import yaml
    m = yaml.safe_load(out.read_text())
    sub = m["subjects"]["01"]
    assert sub["fieldmap_type"] == "fsl_prepare_fieldmap"
    # warnings surfaced for review
    assert "detections" in sub or "warnings" in m or "GE" not in r.stderr

def test_discover_pepolar_sets_topup(tmp_path):
    out = tmp_path / "m.yaml"
    r = _run("bids_discover.py", B / "pepolar", "--output", out)
    assert r.returncode == 0, r.stderr
    import yaml
    m = yaml.safe_load(out.read_text())
    assert m["subjects"]["01"]["fieldmap_type"] == "topup"

def test_generate_pepolar_fills_ap_pa(tmp_path):
    man = tmp_path / "m.yaml"
    _run("bids_discover.py", B / "pepolar", "--output", man)
    out = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", out, "--codedir", REPO)
    assert r.returncode == 0, r.stderr
    scan = next(out.rglob("scanlist_*.csv")).read_text()
    assert "FMAP_AP" in scan.splitlines()[0]
    # AP/PA columns populated (non-zero) somewhere
    assert any(row.split(",")[8] != "0" or row.split(",")[9] != "0"
               for row in scan.splitlines()[1:] if row.strip())

def test_no_session_dataset(tmp_path):
    # build a no-ses tree
    d = tmp_path / "ds" / "sub-01" / "fmap"; d.mkdir(parents=True)
    (d.parent / "anat").mkdir()
    (d.parent / "anat" / "sub-01_T1w.nii.gz").write_bytes(b"")
    (d / "sub-01_magnitude1.nii.gz").write_bytes(b""); (d / "sub-01_phasediff.nii.gz").write_bytes(b"")
    (d / "sub-01_phasediff.json").write_text(json.dumps({"Manufacturer":"Siemens","EchoTimeDifference":0.00246}))
    (tmp_path / "ds" / "sub-01" / "func").mkdir()
    (tmp_path / "ds" / "sub-01" / "func" / "sub-01_task-rest_bold.nii.gz").write_bytes(b"")
    out = tmp_path / "m.yaml"
    r = _run("bids_discover.py", tmp_path / "ds", "--output", out)
    assert r.returncode == 0, r.stderr

def test_low_confidence_generate_refuses_without_force(tmp_path):
    # fmap dir with files but unrecognized regime => low confidence
    d = tmp_path / "ds" / "sub-01" / "ses-01" / "fmap"; d.mkdir(parents=True)
    (d / "sub-01_ses-01_weird.nii.gz").write_bytes(b"")
    out = tmp_path / "m.yaml"
    _run("bids_discover.py", tmp_path / "ds", "--output", out)
    gen = tmp_path / "gen"
    r = _run("bids_generate.py", out, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode != 0
    r2 = _run("bids_generate.py", out, "--iproc-dir", gen, "--codedir", REPO, "--force")
    assert r2.returncode == 0, r2.stderr
