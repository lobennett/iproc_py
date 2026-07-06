"""
Unit tests for iproc.steps._resolve_unique_bids_file, the deterministic
BIDS-file resolution helper introduced to fix:
  * SCI-2: non-deterministic glob.glob()[0] selection, and
  * I-a:  plain canonical T1w (no interposed BIDS entity) failing to match.
"""
import os

import pytest

from iproc.steps import _resolve_unique_bids_file


def _touch(path):
    path.write_bytes(b"")
    return str(path)


def test_zero_matches_raises(tmp_path):
    with pytest.raises(IOError) as exc:
        _resolve_unique_bids_file(
            [str(tmp_path / "sub-01_ses-01_run-1_T1w.nii.gz")], "T1w file"
        )
    assert "No T1w file found" in str(exc.value)


def test_exactly_one_match_returned(tmp_path):
    f = _touch(tmp_path / "sub-01_ses-01_acq-mprage_run-1_T1w.nii.gz")
    got = _resolve_unique_bids_file(
        [str(tmp_path / "sub-01_ses-01_*_run-1_T1w.nii.gz")], "T1w file"
    )
    assert got == f


def test_two_matches_raises_listing_both(tmp_path):
    a = _touch(tmp_path / "sub-01_ses-01_acq-mprage_run-1_T1w.nii.gz")
    b = _touch(tmp_path / "sub-01_ses-01_acq-highres_run-1_T1w.nii.gz")
    with pytest.raises(IOError) as exc:
        _resolve_unique_bids_file(
            [str(tmp_path / "sub-01_ses-01_*_run-1_T1w.nii.gz")], "T1w file"
        )
    msg = str(exc.value)
    assert "Ambiguous" in msg
    assert os.path.basename(a) in msg
    assert os.path.basename(b) in msg


def test_canonical_no_entity_name_resolves_via_union(tmp_path):
    # I-a regression: a plain canonical T1w with no interposed entity must
    # resolve when both the no-entity and with-entity patterns are unioned.
    f = _touch(tmp_path / "sub-01_ses-01_run-1_T1w.nii.gz")
    patterns = [
        str(tmp_path / "sub-01_ses-01_run-1_T1w.nii.gz"),
        str(tmp_path / "sub-01_ses-01_*_run-1_T1w.nii.gz"),
    ]
    got = _resolve_unique_bids_file(patterns, "T1w file")
    assert got == f


def test_acq_entity_name_resolves_via_union(tmp_path):
    f = _touch(tmp_path / "sub-01_ses-01_acq-mprage_run-1_T1w.nii.gz")
    patterns = [
        str(tmp_path / "sub-01_ses-01_run-1_T1w.nii.gz"),
        str(tmp_path / "sub-01_ses-01_*_run-1_T1w.nii.gz"),
    ]
    got = _resolve_unique_bids_file(patterns, "T1w file")
    assert got == f


def test_union_deduplicates_overlapping_patterns(tmp_path):
    # The with-entity pattern also matches acq- files; unioning it with the
    # no-entity pattern must not double-count into a false ambiguity.
    f = _touch(tmp_path / "sub-01_ses-01_acq-mprage_run-1_T1w.nii.gz")
    patterns = [
        str(tmp_path / "sub-01_ses-01_*_run-1_T1w.nii.gz"),
        str(tmp_path / "sub-01_ses-01_acq-mprage_run-1_T1w.nii.gz"),
    ]
    got = _resolve_unique_bids_file(patterns, "T1w file")
    assert got == f


def test_result_is_sorted_deterministic(tmp_path):
    # Whatever the filesystem order, ambiguous candidates are reported sorted.
    names = [
        "sub-01_ses-01_acq-zeta_run-1_T1w.nii.gz",
        "sub-01_ses-01_acq-alpha_run-1_T1w.nii.gz",
        "sub-01_ses-01_acq-mid_run-1_T1w.nii.gz",
    ]
    for n in names:
        _touch(tmp_path / n)
    with pytest.raises(IOError) as exc:
        _resolve_unique_bids_file(
            [str(tmp_path / "sub-01_ses-01_*_run-1_T1w.nii.gz")], "T1w file"
        )
    msg = str(exc.value)
    listed = [line.strip() for line in msg.splitlines() if line.strip().startswith(str(tmp_path))]
    assert listed == sorted(listed)


def test_predicate_filters_matches(tmp_path):
    # Mirrors func resolution: case-insensitive task filtering via predicate.
    _touch(tmp_path / "sub-01_ses-01_task-rest_run-1_bold.nii.gz")
    _touch(tmp_path / "sub-01_ses-01_task-restingextra_run-1_bold.nii.gz")
    got = _resolve_unique_bids_file(
        str(tmp_path / "sub-01_ses-01_task-*_run-1_bold.nii.gz"),
        "BOLD file",
        predicate=lambda f: f.lower().count("task-rest_") == 1,
    )
    assert got == str(tmp_path / "sub-01_ses-01_task-rest_run-1_bold.nii.gz")


def test_single_pattern_string_accepted(tmp_path):
    f = _touch(tmp_path / "sub-01_ses-01_run-1_T1w.nii.gz")
    got = _resolve_unique_bids_file(
        str(tmp_path / "sub-01_ses-01_run-1_T1w.nii.gz"), "T1w file"
    )
    assert got == f
