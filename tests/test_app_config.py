"""Tests for the T6 nipreps-style config-as-module singleton (iproc.app.config).

This module is additive and independent of the vendored, per-subject
configparser-based `iproc.config.Config` -- do not conflate the two.
"""
from pathlib import Path

import pytest

from iproc.app import config
from iproc.__version__ import __version__ as IPROC_VERSION

_SECTION_CLASSES = (config.execution, config.workflow, config.environment)


@pytest.fixture(autouse=True)
def _isolate_config_state():
    """Snapshot/restore class-attribute state so tests can't leak into each other.

    `execution`/`workflow`/`environment` are singleton classes -- settings live
    as class attributes, not instance attributes -- so mutating them in one
    test would otherwise bleed into the next.
    """

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
# Defaults
# ---------------------------------------------------------------------------


def test_execution_defaults_are_sane():
    assert config.execution.bids_dir is None
    assert config.execution.output_dir is None
    assert config.execution.work_dir is None
    assert config.execution.participant_label == []
    assert config.execution.log_level == 25
    assert config.execution.dry_run is False
    assert config.execution.layout is None


def test_workflow_defaults_are_sane():
    assert config.workflow.analysis_level == "participant"
    assert config.workflow.stage is None
    assert config.workflow.resolution == "222"
    assert config.workflow.skip == 7
    assert config.workflow.smoothing == 6.0


# ---------------------------------------------------------------------------
# environment: read-only, populated at import
# ---------------------------------------------------------------------------


def test_environment_populated_at_import():
    env = config.environment.get()
    assert env["version"] == IPROC_VERSION
    assert isinstance(env["python_version"], str) and env["python_version"]
    assert isinstance(env["cpu_count"], int) and env["cpu_count"] >= 1
    # pybids best-effort: either a version string or None, never missing
    assert "pybids_version" in env


def test_environment_not_overwritten_by_from_dict():
    original = config.environment.get()
    config.from_dict({"environment": {"version": "bogus", "cpu_count": 999999}})
    assert config.environment.get() == original


def test_environment_load_is_noop_even_called_directly():
    original = config.environment.get()
    config.environment.load({"version": "bogus"})
    assert config.environment.get() == original


# ---------------------------------------------------------------------------
# get() shape: excludes hidden + callables + underscore-prefixed
# ---------------------------------------------------------------------------


def test_get_excludes_hidden_layout():
    config.execution.layout = object()  # simulate a live pybids BIDSLayout handle
    exported = config.execution.get()
    assert "layout" not in exported
    assert set(exported.keys()) == {
        "bids_dir",
        "output_dir",
        "work_dir",
        "participant_label",
        "log_level",
        "dry_run",
    }


def test_get_excludes_callables_and_underscore_attrs():
    exported = config.workflow.get()
    assert "load" not in exported
    assert "get" not in exported
    assert not any(k.startswith("_") for k in exported)


# ---------------------------------------------------------------------------
# Round trip: to_dict()/from_dict()
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_round_trip(tmp_path):
    config.execution.bids_dir = tmp_path / "bids"
    config.execution.output_dir = tmp_path / "out"
    config.execution.work_dir = tmp_path / "work"
    config.execution.participant_label = ["01", "02"]
    config.execution.log_level = 15
    config.execution.dry_run = True
    config.execution.layout = object()  # must not survive round trip

    config.workflow.analysis_level = "participant"
    config.workflow.stage = "align"
    config.workflow.resolution = "333"
    config.workflow.skip = 3
    config.workflow.smoothing = 4.5

    snapshot = config.to_dict()

    # blow away in-memory state, then restore purely from the dict
    config.execution.bids_dir = None
    config.execution.output_dir = None
    config.execution.work_dir = None
    config.execution.participant_label = []
    config.execution.log_level = 25
    config.execution.dry_run = False
    config.workflow.stage = None
    config.workflow.resolution = "222"
    config.workflow.skip = 7
    config.workflow.smoothing = 6.0

    config.from_dict(snapshot)

    assert config.execution.bids_dir == tmp_path / "bids"
    assert isinstance(config.execution.bids_dir, Path)
    assert config.execution.output_dir == tmp_path / "out"
    assert isinstance(config.execution.output_dir, Path)
    assert config.execution.work_dir == tmp_path / "work"
    assert isinstance(config.execution.work_dir, Path)
    assert config.execution.participant_label == ["01", "02"]
    assert config.execution.log_level == 15
    assert config.execution.dry_run is True

    assert config.workflow.stage == "align"
    assert config.workflow.resolution == "333"
    assert config.workflow.skip == 3
    assert config.workflow.smoothing == 4.5

    assert "execution" in snapshot
    assert "layout" not in snapshot["execution"]


# ---------------------------------------------------------------------------
# Round trip: dumps()/loads() -- JSON serialization
# ---------------------------------------------------------------------------


def test_dumps_is_json_and_paths_become_strings():
    config.execution.bids_dir = Path("/data/bids")
    payload = config.dumps()

    import json

    parsed = json.loads(payload)  # must not raise -- this is plain JSON
    assert parsed["execution"]["bids_dir"] == "/data/bids"
    assert "layout" not in parsed["execution"]


def test_dumps_loads_round_trip_restores_path_types():
    config.execution.bids_dir = Path("/data/bids")
    config.execution.output_dir = Path("/data/out")
    config.execution.work_dir = Path("/data/work")
    config.execution.participant_label = ["07"]
    config.workflow.smoothing = 8.0

    payload = config.dumps()

    config.execution.bids_dir = None
    config.execution.output_dir = None
    config.execution.work_dir = None
    config.execution.participant_label = []
    config.workflow.smoothing = 6.0

    config.loads(payload)

    assert config.execution.bids_dir == Path("/data/bids")
    assert isinstance(config.execution.bids_dir, Path)
    assert config.execution.output_dir == Path("/data/out")
    assert config.execution.work_dir == Path("/data/work")
    assert config.execution.participant_label == ["07"]
    assert config.workflow.smoothing == 8.0


def test_layout_never_serialized_even_when_set():
    config.execution.layout = "pretend-bids-layout-handle"
    payload = config.dumps()
    assert "pretend-bids-layout-handle" not in payload
    assert "layout" not in payload


# ---------------------------------------------------------------------------
# File round trip: to_filename()/load()
# ---------------------------------------------------------------------------


def test_to_filename_and_load_file_round_trip(tmp_path):
    config.execution.bids_dir = tmp_path / "bids"
    config.execution.participant_label = ["03"]
    config.workflow.stage = "midvol"

    cfg_path = tmp_path / "config.json"
    config.to_filename(cfg_path)
    assert cfg_path.exists()

    config.execution.bids_dir = None
    config.execution.participant_label = []
    config.workflow.stage = None

    config.load(cfg_path)

    assert config.execution.bids_dir == tmp_path / "bids"
    assert isinstance(config.execution.bids_dir, Path)
    assert config.execution.participant_label == ["03"]
    assert config.workflow.stage == "midvol"


def test_loads_accepts_path_like_str_argument(tmp_path):
    config.execution.output_dir = tmp_path / "out"
    cfg_path = tmp_path / "config.json"
    config.to_filename(str(cfg_path))
    config.execution.output_dir = None
    config.load(str(cfg_path))
    assert config.execution.output_dir == tmp_path / "out"
