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
    # The phasediff decision is recorded per session for human review with a
    # real regime + confidence (not just the always-present "detections" key).
    dets = sub["detections"]
    assert dets, "expected a recorded fieldmap detection"
    assert dets[0]["regime"] == "phasediff"
    assert dets[0]["preptool"] == "fsl_prepare_fieldmap"
    assert dets[0]["confidence"] in ("high", "low")

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
    # The pepolar fixture carries only fieldmaps (no anat/bold), so the new
    # missing-anat gate requires --allow-missing-anat to proceed.
    r = _run("bids_generate.py", man, "--iproc-dir", out, "--codedir", REPO,
             "--allow-missing-anat")
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
    # --force clears the low-confidence gate; this fixture also lacks anat/bold,
    # so --allow-missing-anat is needed to reach a successful (exit 0) run.
    r2 = _run("bids_generate.py", out, "--iproc-dir", gen, "--codedir", REPO,
              "--force", "--allow-missing-anat")
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


# ---------------------------------------------------------------------------
# pybids-based discovery: entities that the old regexes silently dropped
# ---------------------------------------------------------------------------

def _write_json(path, obj):
    path.write_text(json.dumps(obj))


def test_entity_carrying_files_are_not_dropped(tmp_path):
    """BOLD with acq-/dir-, an acq- fieldmap, and an uncompressed .nii — all of
    which the hand-rolled regexes dropped — must appear in the manifest."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True)
    (s / "func").mkdir()
    (s / "fmap").mkdir()

    (s / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")

    # BOLD carrying acq- (compressed).
    (s / "func" / "sub-01_ses-01_task-rest_acq-mb_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_acq-mb_bold.json",
                {"RepetitionTime": 2.0, "EchoTime": 0.03})
    # BOLD carrying dir-.
    (s / "func" / "sub-01_ses-01_task-motor_dir-AP_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-motor_dir-AP_bold.json",
                {"RepetitionTime": 2.0})
    # BOLD with an uncompressed .nii extension.
    (s / "func" / "sub-01_ses-01_task-nback_bold.nii").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-nback_bold.json",
                {"RepetitionTime": 2.0})

    # acq- fieldmap (phasediff).
    (s / "fmap" / "sub-01_ses-01_acq-gre_magnitude1.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_acq-gre_phasediff.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_acq-gre_phasediff.json",
                {"Manufacturer": "Siemens", "EchoTime1": 0.00492,
                 "EchoTime2": 0.00738, "EchoTimeDifference": 0.00246})

    out = tmp_path / "m.yaml"
    r = _run("bids_discover.py", ds, "--output", out)
    assert r.returncode == 0, r.stderr
    import yaml
    m = yaml.safe_load(out.read_text())
    ses = m["subjects"]["01"]["sessions"]["01"]

    bold_tasks = sorted(b["task"] for b in ses["bold"])
    # 'rest' (acq-), 'motor' (dir-), 'nback' (uncompressed .nii) all present —
    # each of these was silently dropped by the old regexes.
    assert bold_tasks == ["motor", "nback", "rest"], bold_tasks
    # acq- fieldmap classified into mag + phase.
    assert ses["fmap_mag"] and ses["fmap_phase"]
    assert "acq-gre_magnitude1" in ses["fmap_mag"][0]["file"]
    assert "acq-gre_phasediff" in ses["fmap_phase"][0]["file"]
    assert m["subjects"]["01"]["fieldmap_type"] == "fsl_prepare_fieldmap"


def test_runs_sort_numerically(tmp_path):
    """run-10 must sort after run-2 (numeric, not lexical)."""
    ds = tmp_path / "ds"
    f = ds / "sub-01" / "ses-01" / "func"
    f.mkdir(parents=True)
    for run in (2, 10):
        name = f"sub-01_ses-01_task-rest_run-{run:02d}_bold.nii.gz"
        (f / name).write_bytes(b"")
        _write_json(f / name.replace(".nii.gz", ".json"), {"RepetitionTime": 2.0})
    out = tmp_path / "m.yaml"
    r = _run("bids_discover.py", ds, "--output", out)
    assert r.returncode == 0, r.stderr
    import yaml
    m = yaml.safe_load(out.read_text())
    runs = [b["run"] for b in m["subjects"]["01"]["sessions"]["01"]["bold"]]
    assert runs == [2, 10], runs


def test_missing_t1_blocks_generate(tmp_path):
    """A subject with no T1 must block generate unless --allow-missing-anat."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "func").mkdir(parents=True)
    (s / "fmap").mkdir()
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_bold.json",
                {"RepetitionTime": 2.0})
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_phasediff.json",
                {"Manufacturer": "Siemens", "EchoTimeDifference": 0.00246})

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode != 0, "missing T1 must block"
    assert "T1w" in r.stderr and "01" in r.stderr, r.stderr

    gen2 = tmp_path / "gen2"
    r2 = _run("bids_generate.py", man, "--iproc-dir", gen2, "--codedir", REPO,
              "--allow-missing-anat")
    assert r2.returncode == 0, r2.stderr


def test_mixed_regime_blocks_generate(tmp_path):
    """A subject mixing phasediff and topup across sessions must block unless
    --force (the cfg has a single global PREPTOOL)."""
    ds = tmp_path / "ds"
    # ses-01: phasediff. ses-02: topup (AP/PA epi). Both with anat+bold so the
    # missing-anat gate is satisfied and the mixed-regime gate is what fires.
    s1 = ds / "sub-01" / "ses-01"
    (s1 / "anat").mkdir(parents=True); (s1 / "func").mkdir(); (s1 / "fmap").mkdir()
    (s1 / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    (s1 / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s1 / "func" / "sub-01_ses-01_task-rest_bold.json",
                {"RepetitionTime": 2.0})
    (s1 / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (s1 / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    _write_json(s1 / "fmap" / "sub-01_ses-01_phasediff.json",
                {"Manufacturer": "Siemens", "EchoTimeDifference": 0.00246})

    s2 = ds / "sub-01" / "ses-02"
    (s2 / "func").mkdir(parents=True); (s2 / "fmap").mkdir()
    (s2 / "func" / "sub-01_ses-02_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s2 / "func" / "sub-01_ses-02_task-rest_bold.json",
                {"RepetitionTime": 2.0})
    (s2 / "fmap" / "sub-01_ses-02_dir-AP_epi.nii.gz").write_bytes(b"")
    _write_json(s2 / "fmap" / "sub-01_ses-02_dir-AP_epi.json",
                {"PhaseEncodingDirection": "j-"})
    (s2 / "fmap" / "sub-01_ses-02_dir-PA_epi.nii.gz").write_bytes(b"")
    _write_json(s2 / "fmap" / "sub-01_ses-02_dir-PA_epi.json",
                {"PhaseEncodingDirection": "j"})

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode != 0, "mixed regime must block"
    assert "regime" in r.stderr.lower(), r.stderr

    gen2 = tmp_path / "gen2"
    r2 = _run("bids_generate.py", man, "--iproc-dir", gen2, "--codedir", REPO,
              "--force")
    assert r2.returncode == 0, r2.stderr


def test_direct_regime_refused(tmp_path):
    """The 'direct' fieldmap regime must be refused: iProc has no such preptool."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True); (s / "func").mkdir(); (s / "fmap").mkdir()
    (s / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_bold.json",
                {"RepetitionTime": 2.0})
    (s / "fmap" / "sub-01_ses-01_magnitude.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_fieldmap.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_fieldmap.json",
                {"Units": "Hz"})

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0
    import yaml
    mani = yaml.safe_load(man.read_text())
    assert mani["subjects"]["01"]["fieldmap_type"] == "direct"

    gen = tmp_path / "gen"
    # 'direct' is low-confidence, so --force is needed to clear that gate; the
    # direct-refusal must still fire even under --force.
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO,
             "--force")
    assert r.returncode != 0, "direct regime must be refused"
    assert "direct" in r.stderr.lower(), r.stderr
    # No config should have been written.
    assert not list(gen.rglob("*.cfg"))


def test_missing_tr_warns(tmp_path):
    """A task whose BOLD lacks RepetitionTime must warn loudly on generate."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True); (s / "func").mkdir(); (s / "fmap").mkdir()
    (s / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    # BOLD with NO sidecar => no RepetitionTime.
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_phasediff.json",
                {"Manufacturer": "Siemens", "EchoTimeDifference": 0.00246})

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode == 0, r.stderr
    assert "RepetitionTime" in r.stderr, r.stderr
