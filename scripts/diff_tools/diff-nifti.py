#!/usr/bin/env python3
"""
Compare two NIfTI files' data arrays and headers, without depending on FSL.

Upstream's own `diff-nifti.py` (vendored here as `diff-nifti-fsl.py`) shells
out to `fslmaths`/`fslstats` and takes a (file, directory) pair rather than
two file paths. `scripts/validate_against_baseline.sh` falls back to this
script when the `niftidiff` binary (a Sherlock/FreeSurfer tool, distinct from
either script here) is not on PATH, so it needs a dependency-light, two-file
tool that only requires nibabel (already an `iproc` dependency). This is
that tool.

Exit status:
  0 - data arrays and affines match (within tolerance); no shape/dtype diff.
  1 - a comparison-relevant difference was found (shape, affine, or data).

Header fields that are known to vary harmlessly between runs (e.g. free-text
`descrip`/`aux_file` fields, or extensions carrying tool-version/timestamp
provenance) are reported for visibility but do NOT affect the exit code.
See docs/validation.md ("acceptable header nondeterminism") for the
rationale.
"""

import argparse
import sys

import nibabel as nib
import numpy as np

# Header fields that commonly carry non-scientific metadata (tool version
# strings, free-text notes, timestamps) and are allowed to differ without
# failing validation. Everything else in the header is reported informationally
# but, like these, does not by itself fail the run -- only shape/affine/data
# differences do (see module docstring).
INFORMATIONAL_FIELDS = {"descrip", "aux_file"}


def compare_headers(hdr1, hdr2):
    """Return (informational_diffs, other_diffs) as lists of description strings."""
    informational = []
    other = []
    keys = sorted(set(hdr1.keys()) | set(hdr2.keys()))
    for key in keys:
        try:
            v1 = hdr1[key]
        except KeyError:
            v1 = None
        try:
            v2 = hdr2[key]
        except KeyError:
            v2 = None
        a1, a2 = np.asarray(v1), np.asarray(v2)
        try:
            equal = bool(np.array_equal(a1, a2, equal_nan=True))
        except TypeError:
            # equal_nan only applies to inexact dtypes; non-numeric fields
            # (e.g. byte strings) fall back to plain equality.
            equal = bool(np.array_equal(a1, a2))
        if equal:
            continue
        msg = f"  {key}: {v1!r} != {v2!r}"
        if key in INFORMATIONAL_FIELDS:
            informational.append(msg)
        else:
            other.append(msg)
    return informational, other


def main():
    parser = argparse.ArgumentParser(
        description="Compare two NIfTI files' data arrays and headers (nibabel-based, no FSL required)."
    )
    parser.add_argument("file1", help="Path to the first (reference/baseline) NIfTI file")
    parser.add_argument("file2", help="Path to the second (new/candidate) NIfTI file")
    parser.add_argument("--rtol", type=float, default=0.0, help="Relative tolerance for data comparison (default: 0.0, i.e. exact)")
    parser.add_argument("--atol", type=float, default=0.0, help="Absolute tolerance for data comparison (default: 0.0, i.e. exact)")
    args = parser.parse_args()

    try:
        img1 = nib.load(args.file1)
        img2 = nib.load(args.file2)
    except Exception as exc:
        print(f"ERROR: could not load one or both files: {exc}", file=sys.stderr)
        return 2

    failures = []

    if img1.shape != img2.shape:
        failures.append(f"shape differs: {img1.shape} != {img2.shape}")

    affine_close = np.allclose(img1.affine, img2.affine, rtol=1e-7, atol=1e-6)
    if not affine_close:
        failures.append(f"affine differs:\n{img1.affine}\nvs\n{img2.affine}")

    informational, header_failures = compare_headers(img1.header, img2.header)
    failures.extend(header_failures)

    if img1.shape == img2.shape:
        data1 = np.asarray(img1.dataobj)
        data2 = np.asarray(img2.dataobj)
        if args.rtol or args.atol:
            data_equal = np.allclose(data1, data2, rtol=args.rtol, atol=args.atol, equal_nan=True)
        else:
            data_equal = np.array_equal(data1, data2) or (
                np.isnan(data1).all() and np.isnan(data2).all()
            )
        if not data_equal:
            diff = data1.astype(np.float64) - data2.astype(np.float64)
            finite = diff[np.isfinite(diff)]
            max_abs = float(np.max(np.abs(finite))) if finite.size else float("nan")
            n_diff = int(np.sum(~np.isclose(data1, data2, rtol=args.rtol, atol=args.atol, equal_nan=True)))
            failures.append(
                f"data differs: {n_diff}/{data1.size} voxels differ, max abs diff = {max_abs:.6g}"
            )

    print(f"File 1 (reference): {args.file1}")
    print(f"File 2 (candidate): {args.file2}")

    if informational:
        print("Informational header differences (not fatal):")
        for line in informational:
            print(line)

    if failures:
        print("DIFFERENT:")
        for line in failures:
            print(line)
        return 1

    print("IDENTICAL (within tolerance).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
