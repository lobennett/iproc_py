#!/bin/bash
set -xeou pipefail

# this script runs reorient2std on the input, then passes the rest of the arguments to the specified script.

INFILE=${1}
OUTFILE=${2}
SCRIPT=${3}
shift
shift
shift

fslreorient2std ${INFILE} ${OUTFILE}

${SCRIPT} "$@"
