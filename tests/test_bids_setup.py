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


def test_patch_json_sidecars_only_fills_missing_preserves_existing(tmp_path):
    """patch_json_sidecars must only add MISSING fields to an existing sidecar
    and must not overwrite or drop fields already present (review M5,
    idempotency)."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True); (s / "func").mkdir(); (s / "fmap").mkdir()
    (s / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_bold.json", {"RepetitionTime": 2.0})
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    phase_json = s / "fmap" / "sub-01_ses-01_phasediff.json"
    # Manufacturer + EchoTimeDifference already present (must NOT be touched);
    # CustomField is an arbitrary pre-existing field (must be preserved);
    # SeriesNumber is absent (must be the ONLY field filled in).
    _write_json(phase_json, {
        "Manufacturer": "Siemens",
        "EchoTimeDifference": 0.00246,
        "CustomField": "keep-me",
    })

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode == 0, r.stderr

    patched = json.loads(phase_json.read_text())
    assert patched["Manufacturer"] == "Siemens"
    assert patched["EchoTimeDifference"] == 0.00246
    assert patched["CustomField"] == "keep-me"
    assert "SeriesNumber" in patched  # the one missing field, now filled

    # Idempotent: re-running generate against the now-fully-populated sidecar
    # patches nothing further and leaves its content byte-for-byte equivalent.
    gen2 = tmp_path / "gen2"
    r2 = _run("bids_generate.py", man, "--iproc-dir", gen2, "--codedir", REPO)
    assert r2.returncode == 0, r2.stderr
    assert "Patched" not in r2.stderr
    assert json.loads(phase_json.read_text()) == patched


def test_patch_json_sidecars_corrupt_sidecar_warns_and_continues(tmp_path):
    """A malformed JSON sidecar must not abort the whole generate run: it
    should warn, skip patching just that one sidecar, and continue (review
    M5)."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True); (s / "func").mkdir(); (s / "fmap").mkdir()
    (s / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_bold.json", {"RepetitionTime": 2.0})
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    phase_json = s / "fmap" / "sub-01_ses-01_phasediff.json"
    _write_json(phase_json, {"Manufacturer": "Siemens", "EchoTimeDifference": 0.00246})

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    # Corrupt the sidecar AFTER discovery (discovery already captured the
    # metadata it needed into the manifest) to simulate an externally-edited
    # or truncated sidecar at generate time.
    phase_json.write_text("{not valid json,,,")
    anat_json = s / "anat" / "sub-01_ses-01_T1w.json"
    assert not anat_json.exists()

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode == 0, r.stderr  # one bad sidecar must not abort the run
    assert "WARNING" in r.stderr
    assert "phasediff.json" in r.stderr

    # The corrupt file is left exactly as-is (not overwritten with a fresh,
    # data-losing patch).
    assert phase_json.read_text() == "{not valid json,,,"

    # The rest of generation still completed: the T1w sidecar (a different
    # file) still got patched, and the scanlist/cfg were still written.
    assert anat_json.exists()
    assert json.loads(anat_json.read_text()).get("SeriesNumber")
    assert list(gen.rglob("*.cfg"))
    assert list(gen.rglob("scanlist_*.csv"))


def test_no_fieldmap_gate_lists_sessions_numerically(tmp_path):
    """Sessions ses-2 and ses-10 must be listed in NUMERIC order (ses-2 before
    ses-10) in the no-fieldmap gate error message, not lexical order (which
    would sort "10" before "2")."""
    ds = tmp_path / "ds"
    for ses in ("2", "10"):
        s = ds / "sub-01" / f"ses-{ses}" / "func"
        s.mkdir(parents=True)
        name = f"sub-01_ses-{ses}_task-rest_bold.nii.gz"
        (s / name).write_bytes(b"")
        _write_json(s / name.replace(".nii.gz", ".json"), {"RepetitionTime": 2.0})
    # anat in ses-2 so the missing-anat gate doesn't fire before the
    # no-fieldmap gate we're actually testing.
    anat_dir = ds / "sub-01" / "ses-2" / "anat"
    anat_dir.mkdir()
    (anat_dir / "sub-01_ses-2_T1w.nii.gz").write_bytes(b"")

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode != 0, "expected block: neither session has a fieldmap"

    pos2 = r.stderr.find("ses-2 ")
    pos10 = r.stderr.find("ses-10 ")
    assert pos2 != -1 and pos10 != -1, r.stderr
    assert pos2 < pos10, f"expected ses-2 listed before ses-10:\n{r.stderr}"


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


def test_series_number_in_sidecars_does_not_break_pipeline(tmp_path):
    """Real scanner/dcm2niix BIDS data routinely has an explicit SeriesNumber
    (and other numeric fields) in anat/func/fmap JSON sidecars. pybids returns
    such values as bids.layout.utils.PaddedInt rather than a plain int; if
    bids_discover.py serializes that object with yaml.dump (unsafe tag) instead
    of a plain int, bids_generate.py's yaml.safe_load(manifest) raises
    ConstructorError and the discover -> generate pipeline crashes end to end.

    This must PASS after the fix (plain-type coercion + yaml.safe_dump) and
    FAIL against the pre-fix code (ConstructorError surfaced as a nonzero
    bids_generate.py exit, or bids_discover.py itself failing to produce a
    safe-loadable manifest).
    """
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True)
    (s / "func").mkdir()
    (s / "fmap").mkdir()

    # Anat sidecar with SeriesNumber.
    (s / "anat" / "sub-01_ses-01_T1w.nii.gz").write_bytes(b"")
    _write_json(s / "anat" / "sub-01_ses-01_T1w.json",
                {"SeriesNumber": 5, "Manufacturer": "Siemens"})

    # Func sidecar with SeriesNumber + the usual numeric fields.
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_bold.json",
                {"SeriesNumber": 9, "RepetitionTime": 2.0, "EchoTime": 0.03,
                 "PhaseEncodingDirection": "j-"})

    # Fieldmap (phasediff) sidecar with SeriesNumber on both mag and phase.
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_magnitude1.json",
                {"SeriesNumber": 2})
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_phasediff.json",
                {"SeriesNumber": 3, "Manufacturer": "Siemens",
                 "EchoTimeDifference": 0.00246})

    man = tmp_path / "m.yaml"
    r_disc = _run("bids_discover.py", ds, "--output", man)
    assert r_disc.returncode == 0, r_disc.stderr

    # The manifest must be safe-loadable (this is what actually catches the
    # bug: pre-fix, the SeriesNumber PaddedInt is dumped with an unsafe
    # !!python/object/... tag that safe_load cannot construct).
    import yaml
    with open(man) as f:
        text = f.read()
    manifest = yaml.safe_load(text)  # raises yaml.constructor.ConstructorError pre-fix
    assert "!!python" not in text, text

    bold = manifest["subjects"]["01"]["sessions"]["01"]["bold"][0]
    assert bold["series_number"] == 9
    assert isinstance(bold["series_number"], int)

    gen = tmp_path / "gen"
    r_gen = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r_gen.returncode == 0, r_gen.stderr
    assert next(gen.rglob("scanlist_*.csv")).exists()
    assert next(gen.rglob("*.cfg")).exists()


# ---------------------------------------------------------------------------
# Cross-session anat (MSC-style): T1 in ses-struct*, BOLD/fmap in ses-func*
# ---------------------------------------------------------------------------

def _build_cross_session_ds(tmp_path):
    """T1 lives in ses-struct01/anat; BOLD+fmap live in ses-func01."""
    ds = tmp_path / "ds"
    st = ds / "sub-MSC01" / "ses-struct01" / "anat"
    st.mkdir(parents=True)
    (st / "sub-MSC01_ses-struct01_run-01_T1w.nii.gz").write_bytes(b"")
    _write_json(st / "sub-MSC01_ses-struct01_run-01_T1w.json",
                {"SeriesNumber": 52, "Manufacturer": "Siemens"})

    fu = ds / "sub-MSC01" / "ses-func01"
    (fu / "func").mkdir(parents=True)
    (fu / "fmap").mkdir()
    (fu / "func" / "sub-MSC01_ses-func01_task-rest_run-01_bold.nii.gz").write_bytes(b"")
    _write_json(fu / "func" / "sub-MSC01_ses-func01_task-rest_run-01_bold.json",
                {"SeriesNumber": 9, "RepetitionTime": 2.0})
    (fu / "fmap" / "sub-MSC01_ses-func01_magnitude1.nii.gz").write_bytes(b"")
    _write_json(fu / "fmap" / "sub-MSC01_ses-func01_magnitude1.json",
                {"SeriesNumber": 6})
    (fu / "fmap" / "sub-MSC01_ses-func01_phasediff.nii.gz").write_bytes(b"")
    _write_json(fu / "fmap" / "sub-MSC01_ses-func01_phasediff.json",
                {"SeriesNumber": 7, "Manufacturer": "Siemens",
                 "EchoTimeDifference": 0.00246})
    return ds


def test_cross_session_anat_generate_emits_anat_row_and_broadcasts(tmp_path):
    """MSC-style dataset (T1 in ses-struct01, BOLD/fmap in ses-func01):

    the generated scanlist must have a TYPE=ANAT row under struct01 carrying
    the T1's series number, AND the func01 BOLD row must carry that same T1
    series number in its ANAT column (the cross-session link).
    """
    ds = _build_cross_session_ds(tmp_path)

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0

    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode == 0, r.stderr

    import csv
    scan = next(gen.rglob("scanlist_*.csv"))
    with open(scan) as f:
        rows = list(csv.DictReader(f))

    # An ANAT-type row exists, is under struct01, selected, and carries the T1
    # series number in the ANAT column.
    anat_rows = [r for r in rows if r["TYPE"] == "ANAT"]
    assert len(anat_rows) == 1, rows
    anat = anat_rows[0]
    assert anat["SESSION_ID"] == "struct01"
    assert anat["Analyze"] == "1"
    assert anat["ANAT"] == "52"

    # The func01 BOLD row references the struct01 T1 by series number.
    bold = next(r for r in rows if r["TYPE"] == "REST")
    assert bold["SESSION_ID"] == "func01"
    assert bold["ANAT"] == "52"
    assert bold["Analyze"] == "1"

    # The cfg points T1_SESS at the struct session.
    cfg = next(gen.rglob("*.cfg")).read_text()
    assert "T1_SESS=struct01" in cfg


def test_same_session_generate_unchanged(tmp_path):
    """Regression: when the T1 shares the BOLD's session, the scanlist has the
    ANAT row under that single session and the BOLD row references it — the
    same-session case must not change."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True); (s / "func").mkdir(); (s / "fmap").mkdir()
    (s / "anat" / "sub-01_ses-01_run-01_T1w.nii.gz").write_bytes(b"")
    _write_json(s / "anat" / "sub-01_ses-01_run-01_T1w.json", {"SeriesNumber": 5})
    (s / "func" / "sub-01_ses-01_task-rest_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_bold.json",
                {"SeriesNumber": 9, "RepetitionTime": 2.0})
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_magnitude1.json", {"SeriesNumber": 2})
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_phasediff.json",
                {"SeriesNumber": 3, "Manufacturer": "Siemens",
                 "EchoTimeDifference": 0.00246})

    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0
    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO)
    assert r.returncode == 0, r.stderr

    import csv
    with open(next(gen.rglob("scanlist_*.csv"))) as f:
        rows = list(csv.DictReader(f))
    anat = next(r for r in rows if r["TYPE"] == "ANAT")
    bold = next(r for r in rows if r["TYPE"] == "REST")
    assert anat["SESSION_ID"] == "01" and bold["SESSION_ID"] == "01"
    assert anat["ANAT"] == "5" and bold["ANAT"] == "5"


def test_match_scan_no_to_bids_cross_session_no_crash(tmp_path):
    """iproc.bids.match_scan_no_to_bids must NOT crash when a session lacks a
    modality: a func session (no anat/) and a struct session (no func/, no
    fmap/) must each be handled, and the struct session's anat must receive
    its BIDS_ID from its OWN anat/ dir.
    """
    from iproc.config import Config
    from iproc import csvHandler
    from iproc.bids import match_scan_no_to_bids

    # --- BIDS tree: T1 in ses-struct01, BOLD+fmap in ses-func01 ---
    # pybids needs a dataset root + sub-XX layer (match_scan_no_to_bids receives
    # the SUBJECT dir and indexes from its parent).
    bids = tmp_path / "bids"
    bids.mkdir(parents=True, exist_ok=True)
    (bids / "dataset_description.json").write_text('{"Name":"t","BIDSVersion":"1.9.0"}')
    sub_dir = bids / "sub-MSC01"
    st = sub_dir / "ses-struct01" / "anat"; st.mkdir(parents=True)
    (st / "sub-MSC01_ses-struct01_run-01_T1w.nii.gz").write_bytes(b"")
    _write_json(st / "sub-MSC01_ses-struct01_run-01_T1w.json", {"SeriesNumber": 52})

    fu = sub_dir / "ses-func01"
    (fu / "func").mkdir(parents=True); (fu / "fmap").mkdir()
    (fu / "func" / "sub-MSC01_ses-func01_task-rest_run-01_bold.nii.gz").write_bytes(b"")
    _write_json(fu / "func" / "sub-MSC01_ses-func01_task-rest_run-01_bold.json",
                {"SeriesNumber": 9})
    (fu / "fmap" / "sub-MSC01_ses-func01_magnitude1.nii.gz").write_bytes(b"")
    _write_json(fu / "fmap" / "sub-MSC01_ses-func01_magnitude1.json", {"SeriesNumber": 6})
    (fu / "fmap" / "sub-MSC01_ses-func01_phasediff.nii.gz").write_bytes(b"")
    _write_json(fu / "fmap" / "sub-MSC01_ses-func01_phasediff.json", {"SeriesNumber": 7})

    # --- task + scanlist CSVs ---
    task_csv = tmp_path / "task.csv"
    task_csv.write_text("TYPE,TR,SKIP,SMOOTHING,NUMVOL,NUMECHOS\nREST,2.0,4,6,100,1\n")
    scan_csv = tmp_path / "scanlist.csv"
    scan_csv.write_text(
        "SUBJID,SESSION_ID,Analyze,BLD,TYPE,ANAT,FMAP_MAG,FMAP_PHASE,FMAP_AP,FMAP_PA,T2,T2_SESSION_ID\n"
        "MSC01,struct01,1,0,ANAT,52,0,0,0,0,0,0\n"
        "MSC01,func01,1,9,REST,52,6,7,0,0,0,0\n"
        "MSC01,func01,1,0,FMAP,0,6,7,0,0,0,0\n"
    )

    cfg = tmp_path / "m.cfg"
    cfg.write_text(
        "[iproc]\nSUB=MSC01\nBASEDIR=/tmp/x\nOUTDIR=${basedir}/mri_data\n"
        "MASKSDIR=${basedir}/mni_masks\n"
        "[template]\nMIDVOL_SESS=func01\nMIDVOL_BOLDNO=009\nMIDVOL_VOLNO=50\n"
        "FD_THRESH=0.4\nFD_LABEL=0p4\n"
        "[fmap]\nPREPTOOL=fsl_prepare_fieldmap\n"
        "[csv]\nSCANLIST=${iproc:outdir}/${iproc:sub}/scanlist.csv\n"
        "[out_atlas]\nRESOLUTION=222\n"
    )

    conf = Config(); conf.parse(str(cfg))
    scans = csvHandler.scansHandler(conf)
    scans.ingest_task_csv(str(task_csv))
    scans.ingest_bold_csv(str(scan_csv))

    # Must not raise (upstream raised IOError on the func session's missing anat/).
    match_scan_no_to_bids(str(sub_dir), scans)

    # struct01's anat got its BIDS_ID from its own anat/ dir.
    struct = scans.scan_by_session["struct01"]
    assert struct.anat_scans["52"]["BIDS_ID"] == "01"
    # func01's BOLD got its BIDS_ID and links the anat by series number.
    func = scans.scan_by_session["func01"]
    assert func.bold_scans[9]["BIDS_ID"] == "01"
    assert func.bold_scans[9]["ANAT"] == "52"


def _build_two_t1_ds(tmp_path):
    """One session with TWO T1w runs (series 4, 5) plus a BOLD + Siemens
    phasediff fieldmap — the minimal multi-T1 subject for averaging."""
    ds = tmp_path / "ds"
    s = ds / "sub-01" / "ses-01"
    (s / "anat").mkdir(parents=True)
    (s / "func").mkdir()
    (s / "fmap").mkdir()
    for run, sn in (("01", 4), ("02", 5)):
        (s / "anat" / f"sub-01_ses-01_run-{run}_T1w.nii.gz").write_bytes(b"")
        _write_json(s / "anat" / f"sub-01_ses-01_run-{run}_T1w.json",
                    {"SeriesNumber": sn, "Manufacturer": "Siemens"})
    (s / "func" / "sub-01_ses-01_task-rest_run-01_bold.nii.gz").write_bytes(b"")
    _write_json(s / "func" / "sub-01_ses-01_task-rest_run-01_bold.json",
                {"SeriesNumber": 9, "RepetitionTime": 2.0})
    (s / "fmap" / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_magnitude1.json", {"SeriesNumber": 6})
    (s / "fmap" / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    _write_json(s / "fmap" / "sub-01_ses-01_phasediff.json",
                {"SeriesNumber": 7, "Manufacturer": "Siemens",
                 "EchoTimeDifference": 0.00246})
    return ds


def _generate(tmp_path, ds, *extra):
    man = tmp_path / "m.yaml"
    assert _run("bids_discover.py", ds, "--output", man).returncode == 0
    gen = tmp_path / "gen"
    r = _run("bids_generate.py", man, "--iproc-dir", gen, "--codedir", REPO, *extra)
    assert r.returncode == 0, r.stderr
    import csv
    with open(next(gen.rglob("scanlist_*.csv"))) as f:
        rows = list(csv.DictReader(f))
    cfg = next(gen.rglob("*.cfg")).read_text()
    return rows, cfg


def test_average_t1_marks_all_anat_and_sets_cfg_flag(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path), "--average-t1")
    anat = [r for r in rows if r["TYPE"] == "ANAT"]
    assert len(anat) == 2, rows
    assert all(r["Analyze"] == "1" for r in anat), anat
    assert "T1_AVERAGE=true" in cfg


def test_default_selects_single_t1_and_flag_false(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path))
    anat = [r for r in rows if r["TYPE"] == "ANAT"]
    assert len(anat) == 2, rows
    assert sum(1 for r in anat if r["Analyze"] == "1") == 1, anat
    assert "T1_AVERAGE=false" in cfg


def test_default_path_renders_fs6_home(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path))
    assert "FS6=/opt/freesurfer-6.0.0/subjects/fsaverage6" in cfg
    assert "FS6=None" not in cfg


def test_braga_path_renders_fs7_home(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path), "--braga")
    assert "FS6=/opt/freesurfer-7.1.1/subjects/fsaverage6" in cfg


def test_braga_emits_section_and_resolution(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path), "--braga")
    assert "[BRAGA]" in cfg
    assert "BRAGA_MODE=true" in cfg
    assert "BRAIN_EXTRACT=synthstrip" in cfg
    assert "FS_VERSION=7" in cfg
    assert "NATIVE_SURFACE=true" in cfg
    assert "SLICE_TIMING=false" in cfg
    assert "NORDIC=false" in cfg
    assert "MARSS=false" in cfg
    assert "MBFACTOR=1" in cfg
    assert "RESOLUTION=111" in cfg


def test_default_emits_braga_section_off(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path))
    assert "[BRAGA]" in cfg
    assert "BRAGA_MODE=false" in cfg
    assert "BRAIN_EXTRACT=bet" in cfg
    assert "FS_VERSION=6" in cfg
    assert "NATIVE_SURFACE=false" in cfg


def test_braga_brain_extract_override(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path),
                          "--braga", "--brain-extract", "bet")
    assert "BRAIN_EXTRACT=bet" in cfg
    assert "RESOLUTION=111" in cfg  # rest still braga


def test_default_cfg_keeps_existing_sections(tmp_path):
    rows, cfg = _generate(tmp_path, _build_two_t1_ds(tmp_path))
    for section in ("[iproc]", "[template]", "[fmap]", "[csv]", "[fs]",
                    "[T1]", "[out_atlas]", "[BRAGA]"):
        assert section in cfg
    assert "T1_AVERAGE=false" in cfg          # unrelated flag still correct
    assert "RESOLUTION=" in cfg               # from manifest, unchanged
