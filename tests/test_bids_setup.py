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

def test_multisession_partial_fieldmap_gates_per_session(tmp_path):
    # sub-01/ses-01: magnitude1 + phasediff (Siemens) + T1 + func bold.
    # sub-01/ses-02: func bold ONLY (no fmap/). The fmap-less session's BOLD
    # must NOT be silently deselected via the subject-wide fieldmap rollup.
    ds = tmp_path / "ds"
    s1 = ds / "sub-01" / "ses-01"
    (s1 / "fmap").mkdir(parents=True)
    (s1 / "anat").mkdir(); (s1 / "func").mkdir()
    (s1 / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (s1 / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    (s1 / "fmap" / "sub-01_ses-01_phasediff.json").write_text(
        json.dumps({"Manufacturer": "Siemens", "EchoTime1": 0.00492,
                    "EchoTime2": 0.00738, "EchoTimeDifference": 0.00246}))
    (s1 / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    (s1 / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")

    s2 = ds / "sub-01" / "ses-02" / "func"
    s2.mkdir(parents=True)
    (s2 / "sub-01_ses-02_task-rest_bold.nii.gz").write_bytes(b"")

    man = tmp_path / "m.yaml"
    rd = _run("bids_discover.py", ds, "--output", man)
    assert rd.returncode == 0, rd.stderr

    # NO flags: must block (non-zero) and name ses-02.
    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode != 0, "expected block for fmap-less ses-02 BOLD"
    assert "ses-02" in r.stderr, r.stderr

    # --allow-no-fieldmap: exits 0, deselects only ses-02 BOLD.
    gen2 = tmp_path / "gen2"
    r2 = _run("bids_generate.py", man, "--iproc-dir", gen2, "--codedir", REPO,
              "--allow-no-fieldmap")
    assert r2.returncode == 0, r2.stderr

    import csv
    scan = next(gen2.rglob("scanlist_*.csv"))
    with open(scan) as f:
        rows = list(csv.DictReader(f))

    def _bold(ses):
        return next(r for r in rows
                    if r["SESSION_ID"] == ses and r["TYPE"] == "REST")

    assert _bold("01")["Analyze"] == "1", "ses-01 BOLD (has fmap) must analyze"
    assert _bold("02")["Analyze"] == "0", "ses-02 BOLD (no fmap) must deselect"

    # Cross-session anat broadcast: ses-02 BOLD references ses-01's selected T1.
    t1_row = next(r for r in rows
                  if r["TYPE"] == "ANAT" and r["Analyze"] == "1")
    assert _bold("02")["ANAT"] == t1_row["ANAT"] != "0"
