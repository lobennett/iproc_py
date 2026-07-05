#!/usr/bin/env python

import numpy as np
import sys

def main(outliers_path, numvol, outfile_path):
    # Read the values from the outliers file
    # Open the file in read mode
    with open(outliers_path, 'r') as file:
        values_list_from_file = [int(line.strip()) for line in file if line.strip()]

    # Set N from command line argument
    N = int(numvol)
    
    # Length of the values list from the file
    M = len(values_list_from_file)

    # Initialize an N x M matrix with zeros
    matrix = np.zeros((N, M))

    # For each value in values_list_from_file, set the matrix to have a value of 1 at the index of the value
    for i, value in enumerate(values_list_from_file):
        if value < N:  # Check to ensure the index does not exceed the matrix dimensions
            matrix[value, i] = 1  # Note: values are treated as indices, assuming 0-based indexing for the matrix

    # Save the matrix to the specified outfile
    np.savetxt(outfile_path, matrix, fmt='%d', delimiter=' ')

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python create_motion_outlier_matrix.py $OUTLIERS $NUMVOL $OUTFILE")
    else:
        main(sys.argv[1], sys.argv[2], sys.argv[3])
