import numpy as np, nibabel as nib
from pathlib import Path
from iproc.orientation import registration_policy, Policy

def _write_t1(path, affine):
    nib.save(nib.Nifti1Image(np.zeros((4,4,4), dtype="int16"), affine), str(path))

def test_default_is_upstream(tmp_path):
    p = tmp_path / "t1.nii.gz"; _write_t1(p, np.diag([-1,1,1,1]).astype(float))  # LAS-ish
    pol = registration_policy(str(p))
    assert pol.swapdim is True
    assert pol.source == "upstream"

def test_opt_in_fork_variant(tmp_path):
    p = tmp_path / "t1.nii.gz"; _write_t1(p, np.eye(4))
    pol = registration_policy(str(p), config={"orientation_mode": "fork_no_swap"})
    assert pol.swapdim is False
    assert pol.flirt_search == (-30, 30)
    assert pol.source == "fork"

def test_warns_when_already_ras(tmp_path, caplog):
    p = tmp_path / "t1.nii.gz"; _write_t1(p, np.eye(4))  # RAS
    import logging
    with caplog.at_level(logging.WARNING):
        pol = registration_policy(str(p))
    assert pol.swapdim is True  # still upstream default
    assert any("RAS" in r.message for r in caplog.records)
