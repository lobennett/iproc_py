"""Tests for the T8 nipreps-style BIDS-App CLI (``iproc.app.cli`` / ``iproc-app``).

This is an ADDITIVE second console entry point that wraps the
discover -> generate -> (optional) stage flow. It never replaces the existing
config-based ``iproc -c <cfg> -s <stage>`` engine, and these tests never run a
real pipeline stage (they stay FSL-free).
"""
from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pytest

from iproc.app import cli
from iproc.app import config


# ---------------------------------------------------------------------------
# Config singleton isolation (settings live as class attributes)
# ---------------------------------------------------------------------------

_SECTION_CLASSES = (config.execution, config.workflow, config.environment)


@pytest.fixture(autouse=True)
def _isolate_config_state():
    def _snapshot():
        return [
            {k: v for k, v in vars(cls).items() if not k.startswith("__")}
            for cls in _SECTION_CLASSES
        ]

    before = _snapshot()
    yield
    for cls, snap in zip(_SECTION_CLASSES, before):
        for key in list(vars(cls).keys()):
            if key.startswith("__"):
                continue
            if key not in snap:
                delattr(cls, key)
        for key, value in snap.items():
            setattr(cls, key, value)


# ---------------------------------------------------------------------------
# BIDS fixture builders
# ---------------------------------------------------------------------------


def _touch(path: Path, content: bytes | str = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content)
    else:
        path.write_bytes(content)


def _make_anat_only_subject(root: Path, label: str) -> None:
    """A subject with just a T1w -- enough for pybids to enumerate it."""
    _touch(root / f"sub-{label}" / "anat" / f"sub-{label}_T1w.nii.gz")


def _make_complete_subject(root: Path, label: str) -> None:
    """A single-session subject with anat + bold + Siemens phasediff fmap.

    Enough for discover to select a T1/midvol and for generate to pass its
    safety gates (high-confidence phasediff fieldmap) without extra flags.
    """
    base = root / f"sub-{label}" / "ses-01"
    _touch(base / "anat" / f"sub-{label}_ses-01_T1w.nii.gz")
    _touch(base / "func" / f"sub-{label}_ses-01_task-rest_bold.nii.gz")
    _touch(base / "fmap" / f"sub-{label}_ses-01_magnitude1.nii.gz")
    _touch(base / "fmap" / f"sub-{label}_ses-01_phasediff.nii.gz")
    _touch(
        base / "fmap" / f"sub-{label}_ses-01_phasediff.json",
        json.dumps({"Manufacturer": "Siemens", "EchoTimeDifference": 0.00246}),
    )


@pytest.fixture
def two_subject_bids(tmp_path):
    root = tmp_path / "bids"
    _make_anat_only_subject(root, "MSC01")
    _make_anat_only_subject(root, "MSC02")
    return root


@pytest.fixture
def complete_bids(tmp_path):
    root = tmp_path / "bids"
    _make_complete_subject(root, "01")
    return root


# ---------------------------------------------------------------------------
# Parser / validation
# ---------------------------------------------------------------------------


def test_build_parser_positionals_and_choices():
    parser = cli.build_parser()
    args = parser.parse_args(["/b", "/o", "participant"])
    assert str(args.bids_dir) == "/b"
    assert str(args.output_dir) == "/o"
    assert args.analysis_level == "participant"
    # group is a valid *choice* (rejected later in validation, not by argparse)
    args2 = parser.parse_args(["/b", "/o", "group"])
    assert args2.analysis_level == "group"


def test_version_prints_installed_distribution_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert metadata.version("iproc") in out


def test_version_falls_back_to_vendored_version_when_dist_not_found(capsys):
    from iproc.__version__ import __version__ as IPROC_VERSION

    with patch(
        "iproc.app.cli.metadata.version",
        side_effect=metadata.PackageNotFoundError,
    ):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert IPROC_VERSION in out


def test_nonexistent_bids_dir_errors(tmp_path, capsys):
    missing = tmp_path / "nope"
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        cli.main([str(missing), str(out), "participant"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "does not exist" in err.lower()


def test_output_dir_equals_bids_dir_errors(complete_bids, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([str(complete_bids), str(complete_bids), "participant"])
    assert exc.value.code != 0
    err = capsys.readouterr().err.lower()
    assert "output" in err and "bids" in err


def test_group_level_not_supported(complete_bids, tmp_path, capsys):
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        cli.main([str(complete_bids), str(out), "group"])
    assert exc.value.code != 0
    err = capsys.readouterr().err.lower()
    assert "not supported" in err


# ---------------------------------------------------------------------------
# Participant resolution
# ---------------------------------------------------------------------------


def test_resolve_participants_discovers_all(two_subject_bids):
    got = cli.resolve_participants(two_subject_bids, None)
    assert got == ["MSC01", "MSC02"]


def test_resolve_participants_strips_sub_prefix_and_intersects(two_subject_bids):
    # mix a bare label and a 'sub-'-prefixed label
    got = cli.resolve_participants(two_subject_bids, ["MSC01", "sub-MSC02"])
    assert got == ["MSC01", "MSC02"]


def test_resolve_participants_missing_label_errors(two_subject_bids):
    with pytest.raises(SystemExit) as exc:
        cli.resolve_participants(two_subject_bids, ["MSC01", "BOGUS"])
    # the error must name the missing label
    assert "BOGUS" in str(exc.value)


# ---------------------------------------------------------------------------
# Config population
# ---------------------------------------------------------------------------


def test_config_populated_from_args(complete_bids, tmp_path):
    out = tmp_path / "out"
    parser = cli.build_parser()
    args = parser.parse_args(
        [str(complete_bids), str(out), "participant",
         "--stage", "setup", "--skip", "5", "--smoothing", "3.0",
         "--resolution", "111"]
    )
    participants = cli.resolve_participants(complete_bids, args.participant_label)
    cli.populate_config(args, participants)

    assert config.execution.bids_dir == complete_bids.resolve()
    assert config.execution.output_dir == out.resolve()
    assert config.execution.participant_label == ["01"]
    assert config.workflow.stage == "setup"
    assert config.workflow.analysis_level == "participant"
    assert config.workflow.skip == 5
    assert config.workflow.smoothing == 3.0
    assert config.workflow.resolution == "111"


# ---------------------------------------------------------------------------
# Dry run: prints a plan, writes nothing, exits 0
# ---------------------------------------------------------------------------


def test_dry_run_prints_plan_and_writes_nothing(complete_bids, tmp_path, capsys):
    out = tmp_path / "out"
    rc = cli.main([str(complete_bids), str(out), "participant", "--dry-run"])
    assert rc == 0
    printed = capsys.readouterr().out
    # resolved participant + would-run discovery/generation commands
    assert "01" in printed
    assert "dry" in printed.lower() or "would" in printed.lower()
    assert "discover" in printed.lower()
    assert "generate" in printed.lower()
    # no heavy side effects: no iProc derivatives written
    assert not (out / "mri_data").exists()


def test_dry_run_with_stage_shows_stage_command_but_does_not_run(complete_bids, tmp_path, capsys):
    out = tmp_path / "out"
    rc = cli.main([str(complete_bids), str(out), "participant",
                   "--stage", "setup", "--dry-run"])
    assert rc == 0
    printed = capsys.readouterr().out
    assert "setup" in printed
    assert "iproc" in printed.lower()
    assert not (out / "mri_data").exists()


# ---------------------------------------------------------------------------
# Real (non-dry) participant run: discovery + generation, no stage
# ---------------------------------------------------------------------------


def test_participant_run_generates_configs_and_prints_guidance(complete_bids, tmp_path, capsys):
    out = tmp_path / "out"
    rc = cli.main([str(complete_bids), str(out), "participant"])
    assert rc == 0

    cfg = out / "mri_data" / "01" / "subject_lists" / "01.cfg"
    scan = out / "mri_data" / "01" / "subject_lists" / "scanlist_01.csv"
    assert cfg.exists(), "expected generated .cfg under output_dir"
    assert scan.exists(), "expected generated scanlist under output_dir"

    printed = capsys.readouterr().out
    # next-step guidance names the ordered stages + the manual-QC note
    assert "setup" in printed
    assert "filter_and_project" in printed
    assert "qc" in printed.lower()


def test_run_writes_bids_derivatives_description(complete_bids, tmp_path):
    import json
    out = tmp_path / "out"
    rc = cli.main([str(complete_bids), str(out), "participant"])
    assert rc == 0
    desc = out / "dataset_description.json"
    assert desc.exists(), "iproc-app should mark output_dir as a BIDS-Derivatives dataset"
    data = json.loads(desc.read_text())
    assert data["DatasetType"] == "derivative"
    assert data["GeneratedBy"][0]["Name"] == "iproc"


def test_dry_run_does_not_write_dataset_description(complete_bids, tmp_path):
    out = tmp_path / "out"
    rc = cli.main([str(complete_bids), str(out), "participant", "--dry-run"])
    assert rc == 0
    assert not (out / "dataset_description.json").exists()


# ---------------------------------------------------------------------------
# Real (non-dry) participant run WITH --stage: live engine invocation, mocked
# ---------------------------------------------------------------------------


def test_live_stage_run_invokes_iproc_engine_once_per_participant(complete_bids, tmp_path):
    """``--stage`` without ``--dry-run`` subprocess-invokes the ``iproc`` engine.

    Mocks ``subprocess.run`` so this stays FSL-free while still covering the
    live stage-invocation branch (``_run_participant``'s step 3), asserting
    the exact command built by ``_stage_command`` is run once per participant.
    """
    out = tmp_path / "out"
    with patch("iproc.app.cli.subprocess.run") as mock_run:
        rc = cli.main(
            [str(complete_bids), str(out), "participant", "--stage", "setup"]
        )
    assert rc == 0

    expected_cfg = out / "mri_data" / "01" / "subject_lists" / "01.cfg"
    expected_cmd = [
        "iproc",
        "-c", str(expected_cfg),
        "-s", "setup",
        "--bids", str(complete_bids / "sub-01"),
        "--executor", "local",
    ]
    mock_run.assert_called_once_with(expected_cmd, check=True)
