from pathlib import Path
import pytest
from iproc.fieldmap import detect_regime, plan_fieldmaps, Decision
B = Path(__file__).parent / "fixtures" / "bids"

def _fmap(name): return B / name / "sub-01" / "ses-01" / "fmap"

def test_siemens_phasediff():
    d = detect_regime(_fmap("siemens_phasediff"))
    assert d.value == "phasediff"
    assert d.confidence == "high"
    assert d.evidence["manufacturer"] == "SIEMENS"
    assert abs(d.evidence["delta_te_ms"] - 2.46) < 1e-6
    assert d.evidence["preptool"] == "fsl_prepare_fieldmap"

def test_ge_phasediff_flagged():
    d = detect_regime(_fmap("ge_phasediff"))
    assert d.value == "phasediff"
    assert d.evidence["manufacturer"] == "GE"
    assert d.evidence["ge_special"] is True
    assert any("GE" in w for w in d.warnings)

def test_pepolar_topup():
    d = detect_regime(_fmap("pepolar"))
    assert d.value == "pepolar"
    assert d.evidence["preptool"] == "topup"
    assert d.evidence["pe_dirs"] == ["j-", "j"]

def test_none_regime():
    d = detect_regime(_fmap("none"))   # dir doesn't exist
    assert d.value == "none"
    assert d.confidence == "high"

def test_plan_fieldmaps_returns_plans():
    plans = plan_fieldmaps(B / "siemens_phasediff" / "sub-01")
    assert plans and plans[0].regime == "phasediff"
    assert plans[0].preptool == "fsl_prepare_fieldmap"

def test_direct_regime():
    d = detect_regime(_fmap("direct"))
    assert d.value == "direct"
    assert d.confidence == "low"
    assert d.evidence["preptool"] == "direct"
    assert len(d.warnings) >= 1

def test_phasediff_missing_manufacturer_defaults_siemens():
    d = detect_regime(_fmap("siemens_no_mfr"))
    assert d.value == "phasediff"
    assert d.confidence == "low"
    assert d.evidence["manufacturer"] == "SIEMENS"
    assert any("Manufacturer" in w for w in d.warnings)

def test_phasediff_echotime1_echotime2_fallback():
    d = detect_regime(_fmap("siemens_te12"))
    assert d.value == "phasediff"
    assert abs(d.evidence["delta_te_ms"] - 2.46) < 1e-6


def test_inheritance_metadata_lookup_resolves_high_confidence(tmp_path):
    """MSC-style: no per-file sidecar; inherited Manufacturer/echo-times come
    from a metadata_lookup (pybids get_metadata). Should be high-confidence."""
    fmap = tmp_path / "sub-01" / "ses-01" / "fmap"
    fmap.mkdir(parents=True)
    (fmap / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (fmap / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")  # NO .json sidecar

    inherited = {"Manufacturer": "Siemens", "EchoTime1": 0.00519, "EchoTime2": 0.00765}
    d = detect_regime(fmap, metadata_lookup=lambda p: inherited)
    assert d.value == "phasediff"
    assert d.confidence == "high"                     # not spuriously low
    assert d.evidence["manufacturer"] == "SIEMENS"
    assert abs(d.evidence["delta_te_ms"] - 2.46) < 1e-6
    assert not d.warnings                              # no "missing" warnings


def test_no_sidecar_without_lookup_stays_low_confidence(tmp_path):
    """Fallback preserved: no sidecar + no lookup → conservative low confidence."""
    fmap = tmp_path / "sub-01" / "ses-01" / "fmap"
    fmap.mkdir(parents=True)
    (fmap / "sub-01_ses-01_magnitude1.nii.gz").write_bytes(b"")
    (fmap / "sub-01_ses-01_phasediff.nii.gz").write_bytes(b"")
    d = detect_regime(fmap)  # no metadata_lookup, no .json
    assert d.value == "phasediff"
    assert d.confidence == "low"
    assert any("missing" in w.lower() for w in d.warnings)
