#!/usr/bin/env -S python3 -u
"""
Compare two NIfTI files by subtracting them and reporting statistics. 
Subtracting images will more robustly reveal L/R flip issues.

This script takes a file path and a directory, finds the same filename in the 
directory, subtracts the files using fslmaths, and reports mean, min, and max 
voxel intensities of the difference.
"""

import sys
import argparse
import logging
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

logger = logging.getLogger("compare-nifti")
logging.basicConfig(level=logging.INFO)

def run_command(cmd):
    """Run a shell command and return the output."""
    try:
        result = subprocess.run(
            cmd, 
            shell=True, 
            check=True, 
            capture_output=True, 
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}")
        print(f"Error message: {e.stderr}")
        sys.exit(1)


def check_fsl_installed():
    """Check if FSL is installed and available."""
    try:
        subprocess.run(
            ["which", "fslmaths"], 
            check=True, 
            capture_output=True
        )
    except subprocess.CalledProcessError:
        print("Error: FSL does not appear to be installed or is not in PATH.")
        print("Please install FSL or ensure it's properly configured.")
        sys.exit(1)


def compare_files(file1, file2):
    """
    Compare two NIfTI files using fslmaths and fslstats.
    
    Args:
        file1: Path to first NIfTI file
        file2: Path to second NIfTI file
    
    Returns:
        Dictionary with mean, min, and max values
    """
    # Create temporary directory that will be automatically cleaned up
    with TemporaryDirectory() as tmpdir:
        # Create temporary file for difference image
        diff_file = Path(tmpdir) / 'diff.nii.gz'
        
        # Subtract file2 from file1
        logger.debug(f"Subtracting files: {file1} - {file2}")
        run_command(f"fslmaths {file1} -sub {file2} {diff_file}")
        
        # Get statistics
        mean = run_command(f"fslstats {diff_file} -m")
        min_val,max_val = run_command(f"fslstats {diff_file} -R").split()
        
        return {
            'mean': float(mean),
            'min': float(min_val),
            'max': float(max_val)
        }


def main():
    parser = argparse.ArgumentParser(
        description='Compare two NIfTI files using fslmaths subtraction'
    )
    
    parser.add_argument(
        'file1',
        help='Path to the first NIfTI file'
    )
    
    parser.add_argument(
        'directory',
        help='Directory containing the second file with the same name'
    )
    
    args = parser.parse_args()
    
    # Check if FSL is installed
    check_fsl_installed()
    
    # Convert to Path objects
    file1_path = Path(args.file1)
    directory_path = Path(args.directory)
    
    # Check if first file exists
    if not file1_path.exists():
        logger.critical(f"Error: File not found: {file1_path.resolve()}")
        sys.exit()
    
    # Check if directory exists
    if not directory_path.is_dir():
        logger.critical(f"Error: Directory not found: {directory_path.resolve()}")
        sys.exit(1)
    
    # Get the filename from the first file
    filename = file1_path.name
    
    # Construct path to second file
    file2_path = directory_path / file1_path
    
    # Check if second file exists
    if not file2_path.exists():
        logger.critical(f"Error: File not found in directory: {file2_path.resolve()}")
        sys.exit()
    
    # Compare the files
    logger.info(f"Comparing files")
    logger.info(f"  File 1: {file1_path.resolve()}")
    logger.info(f"  File 2: {file2_path.resolve()}")
    logger.debug(f"\nComputing difference (File1 - File2)...")

    stats = compare_files(file1_path, file2_path)
    
   
    # Interpretation hint
    if abs(stats['mean']) == 0.0 and abs(stats['min']) == 0.0 and abs(stats['max']) == 0.0:
        logger.info("The files appear to be identical (all differences zero).")
    else:
        logger.critical(f"The files differ. Range of differences: [{stats['min']:.6f}, {stats['max']:.6f}]")
        logger.critical(f"Mean voxel intensity:    {stats['mean']:12.6f}")
        logger.critical(f"Minimum value:           {stats['min']:12.6f}")
        logger.critical(f"Maximum value:           {stats['max']:12.6f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
