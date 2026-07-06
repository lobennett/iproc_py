"""Unit tests for ``commons.resolve_bids_metadata`` — the BIDS inheritance
resolver used by ``runscript/func_from_bids.py`` so metadata stored only in
inherited, higher-level sidecars (e.g. MSC's root ``task-*_bold.json``) is
found even when there is no per-run sidecar."""
from pathlib import Path

from iproc import commons


def _touch(p: Path, content: str = ""):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_inherited_root_sidecar(tmp_path):
    root = tmp_path / "ds"
    _touch(root / "dataset_description.json", '{"Name":"t","BIDSVersion":"1.9.0"}')
    # metadata ONLY at the root, keyed by task (MSC layout)
    _touch(root / "task-rest_bold.json",
           '{"EchoTime":0.027,"EffectiveEchoSpacing":0.00059,'
           '"PhaseEncodingDirection":"j-"}')
    nii = (root / "sub-01" / "ses-func01" / "func"
           / "sub-01_ses-func01_task-rest_run-01_bold.nii.gz")
    _touch(nii)

    md = commons.resolve_bids_metadata(str(nii))
    assert md["EchoTime"] == 0.027
    assert md["EffectiveEchoSpacing"] == 0.00059
    assert md["PhaseEncodingDirection"] == "j-"


def test_wrong_task_sidecar_not_applied(tmp_path):
    root = tmp_path / "ds"
    _touch(root / "dataset_description.json", '{"Name":"t"}')
    _touch(root / "task-rest_bold.json", '{"EchoTime":0.027}')
    _touch(root / "task-motor_bold.json", '{"EchoTime":0.030}')
    nii = (root / "sub-01" / "func" / "sub-01_task-motor_run-01_bold.nii.gz")
    _touch(nii)

    md = commons.resolve_bids_metadata(str(nii))
    assert md["EchoTime"] == 0.030  # motor, not rest


def test_sibling_overrides_inherited(tmp_path):
    root = tmp_path / "ds"
    _touch(root / "dataset_description.json", '{"Name":"t"}')
    _touch(root / "task-rest_bold.json",
           '{"EchoTime":0.027,"RepetitionTime":2.2}')
    nii = (root / "sub-01" / "func" / "sub-01_task-rest_run-01_bold.nii.gz")
    _touch(nii)
    # adjacent sidecar overrides the more-specific key, inherits the rest
    _touch(root / "sub-01" / "func" / "sub-01_task-rest_run-01_bold.json",
           '{"EchoTime":0.099}')

    md = commons.resolve_bids_metadata(str(nii))
    assert md["EchoTime"] == 0.099          # sibling wins
    assert md["RepetitionTime"] == 2.2      # inherited from root


def test_suffix_must_match(tmp_path):
    root = tmp_path / "ds"
    _touch(root / "dataset_description.json", '{"Name":"t"}')
    # a phasediff sidecar must NOT leak into bold metadata
    _touch(root / "task-rest_bold.json", '{"EchoTime":0.027}')
    _touch(root / "phasediff.json", '{"EchoTime1":0.004}')
    nii = (root / "sub-01" / "func" / "sub-01_task-rest_bold.nii.gz")
    _touch(nii)

    md = commons.resolve_bids_metadata(str(nii))
    assert md == {"EchoTime": 0.027}
