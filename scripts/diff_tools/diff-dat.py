#!/usr/bin/env python3
"""
Compare two space-delimited text files containing matrices of float values.
Uses numpy.allclose to check if values are close within a tolerance of 1e-10.

This script is useful when comparing nuisance .dat files. 

The reason for testing for closeness rather than equality is to support 
migrating from Matlab to SciPy for calculating nuisance regressors. There are 
known small differences (e.g., 1e-10) between Matlab detrend and 
scipy.signal.detrend.
"""

import numpy as np
import sys
import argparse
from pathlib import Path
import warnings

def load_matrix(filename):
    """Load a space-delimited matrix from a text file."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            matrix = np.loadtxt(filename)
        return matrix
    except Exception as e:
        print(f"Error loading {filename}: {e}", file=sys.stderr)
        sys.exit(1)

def compare_matrices(file1, file2, rtol=1e-10, atol=1e-10, verbose=False):
    # Load matrices
    matrix1 = load_matrix(file1)
    matrix2 = load_matrix(file2)
    
    # Check shapes match
    if matrix1.shape != matrix2.shape:
        print(f"Shape mismatch: {file1} has shape {matrix1.shape}, "
              f"{file2} has shape {matrix2.shape}")
        return False
    
    if verbose:
        print(f"Matrix shape: {matrix1.shape}")
        print(f"Tolerance - rtol: {rtol}, atol: {atol}")
    
    # Compare using allclose
    are_close = np.allclose(matrix1, matrix2, rtol=rtol, atol=atol)
    
    if verbose:
        if are_close:
            max_diff = np.max(np.abs(matrix1 - matrix2))
            print(f"Matrices are close (max absolute difference: {max_diff:.2e})")
        else:
            diff = np.abs(matrix1 - matrix2)
            max_diff = np.max(diff)
            max_idx = np.unravel_index(np.argmax(diff), diff.shape)
            print(f"Matrices differ significantly")
            print(f"Max absolute difference: {max_diff:.2e} at position {max_idx}")
            print(f"Value in {file1}: {matrix1[max_idx]}")
            print(f"Value in {file2}: {matrix2[max_idx]}")
    
    return are_close


def main():
    parser = argparse.ArgumentParser(
        description="Compare two space-delimited matrix files for numerical closeness"
    )
    parser.add_argument("file1", type=Path, help="First matrix file")
    parser.add_argument("file2", type=Path, help="Second matrix file")
    parser.add_argument(
        "--rtol", 
        type=float, 
        default=1e-10,
        help="Relative tolerance (default: 1e-10)"
    )
    parser.add_argument(
        "--atol", 
        type=float, 
        default=1e-10,
        help="Absolute tolerance (default: 1e-10)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed comparison information"
    )
    
    args = parser.parse_args()

    if not args.file1.exists():
        #print(f"File 1 does not exist {args.file1}")
        sys.exit()
    if not args.file2.exists():
        #print(f"File 2 does not exist {args.file2}")
        sys.exit()

    # Compare matrices
    are_close = compare_matrices(
        args.file1, 
        args.file2, 
        rtol=args.rtol, 
        atol=args.atol,
        verbose=args.verbose
    )
    
    # Print result and exit with appropriate code
    if are_close:
        print("✓ Matrices are close within tolerance")
        sys.exit(0)
    else:
        print(f"File 1: {args.file1}")
        print(f"File 2: {args.file2}")
        print("✗ Matrices differ beyond tolerance")
        sys.exit(1)


if __name__ == "__main__":
    main()
