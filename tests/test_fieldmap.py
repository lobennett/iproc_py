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
