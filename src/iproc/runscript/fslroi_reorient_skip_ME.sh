#!/bin/bash
set -xeou pipefail
#TODO(maybe): just write a wrapper with $@

INFILE=$1
OUTFILE=$2
TMIN=$3
TSIZE=$4

fslroi ${INFILE} ${OUTFILE} ${TMIN} ${TSIZE}
INDIR=$(dirname ${INFILE})
OUTDIR=$(dirname ${OUTFILE})
cp $INDIR/*echoTime_e1.sec $OUTDIR/
cp $INDIR/*dwellTime_e1.sec $OUTDIR/
cp $INDIR/*_e1.json $OUTDIR/
