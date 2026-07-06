"""Tests for the T9 BIDS-Derivatives ``dataset_description.json`` helper.

``iproc-app``'s ``output_dir`` should be a valid BIDS-Derivatives dataset,
which minimally means a top-level ``dataset_description.json`` declaring it
a derivative. These tests cover the standalone helper in isolation; CLI
wire-in (real run writes it, dry-run does not) is covered in
``tests/test_app_cli.py``.
"""
from __future__ import annotations

import json
from importlib import metadata
from pathlib import Path
from unittest.mock import patch

import pytest

from iproc.app import derivatives


def test_write_dataset_description_creates_output_dir(tmp_path):
    out = tmp_path / "does" / "not" / "exist" / "yet"
    assert not out.exists()

    derivatives.write_dataset_description(out)

    assert out.is_dir()


def test_write_dataset_description_returns_path_to_file(tmp_path):
    out = tmp_path / "out"
    result = derivatives.write_dataset_description(out)

    assert result == out / "dataset_description.json"
    assert result.exists()


def test_write_dataset_description_writes_valid_derivative_json(tmp_path):
    out = tmp_path / "out"
    path = derivatives.write_dataset_description(out)

    data = json.loads(path.read_text())

    assert data["Name"] == "iProc (individualized fMRI preprocessing)"
    assert data["BIDSVersion"] == "1.9.0"
    assert data["DatasetType"] == "derivative"

    generated_by = data["GeneratedBy"]
    assert isinstance(generated_by, list) and len(generated_by) == 1
    assert generated_by[0]["Name"] == "iproc"
    assert generated_by[0]["Version"]  # non-empty
    assert generated_by[0]["CodeURL"] == "https://github.com/lobennett/iproc_py"

    # HowToAcknowledge points back at upstream harvard-nrg/iProc.
    assert "harvard-nrg/iProc" in data["HowToAcknowledge"]


def test_write_dataset_description_uses_installed_dist_version(tmp_path):
    out = tmp_path / "out"
    path = derivatives.write_dataset_description(out)
    data = json.loads(path.read_text())

    assert data["GeneratedBy"][0]["Version"] == metadata.version("iproc")


def test_write_dataset_description_falls_back_when_dist_not_found(tmp_path):
    from iproc.__version__ import __version__ as IPROC_VERSION

    out = tmp_path / "out"
    with patch(
        "iproc.app.derivatives.metadata.version",
        side_effect=metadata.PackageNotFoundError,
    ):
        path = derivatives.write_dataset_description(out)

    data = json.loads(path.read_text())
    assert data["GeneratedBy"][0]["Version"] == IPROC_VERSION


def test_write_dataset_description_is_idempotent(tmp_path):
    out = tmp_path / "out"
    first = derivatives.write_dataset_description(out)
    first_data = json.loads(first.read_text())

    second = derivatives.write_dataset_description(out)
    second_data = json.loads(second.read_text())

    assert first == second
    assert first_data == second_data
