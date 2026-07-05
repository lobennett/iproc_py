from pathlib import Path
from iproc.config import Config, ConfigError
import pytest
FIX = Path(__file__).parent / "fixtures" / "minimal.cfg"
def _c():
    c = Config(); c.parse(str(FIX)); return c
def test_plain_values():
    c = _c()
    assert c.iproc.SUB == "TEST01"
    assert c.fmap.PREPTOOL == "fsl_prepare_fieldmap"
def test_extended_interpolation():
    c = _c()
    assert c.iproc.OUTDIR == "/tmp/iproc_base/mri_data"
    assert c.csv.SCANLIST == "/tmp/iproc_base/mri_data/TEST01/scanlist.csv"
def test_missing_raises():
    with pytest.raises(ConfigError):
        _ = _c().iproc.NOPE
def test_get_default():
    assert _c().get("iproc", "nope", default="fb") == "fb"
