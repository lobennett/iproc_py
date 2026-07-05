#!/bin/bash
set -xeou pipefail

SWAP=${1}
ROI=${2}
SIZE=${3}
SAMPLE=${4}
WIDTH=${5}
SLICED=${6}
LABEL=${7}
OUTFILE=${8}

fslroi ${SWAP} ${ROI} ${SIZE}
slicer ${ROI} -u -S ${SAMPLE} ${WIDTH} ${SLICED} 
convert ${SLICED} -background White -pointsize 20 label:${LABEL} +swap -gravity North-West -append ${OUTFILE} 
