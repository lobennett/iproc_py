#!/bin/bash
set -xeou pipefail
MERGE_IN=${1}
MERGE_OUT=${2}
NUMVOL=${3}
REORIENT_OUT=${4}
DILMASK=${5}
MEAN_OUT=${6}
MIDVOL_OUT=${7}
rmfiles=${8:-''}

## extracted from iProc_p4a_sbatch.py
fslmerge -t ${MERGE_OUT} ${MERGE_IN}*
fslreorient2std ${MERGE_OUT} ${REORIENT_OUT}
fslmaths ${REORIENT_OUT} -mul ${DILMASK} ${REORIENT_OUT}
fslmaths ${REORIENT_OUT} -Tmean ${MEAN_OUT}
fslroi ${REORIENT_OUT} ${MIDVOL_OUT} `expr ${NUMVOL} / 2` 1
#rm ${MERGE_IN}*
#rm ${MERGE_OUT} 
#if [ -n "$rmfiles" ]; then
#    for f in $rmfiles;do
#        rm -rf "$f"
#    done
#fi
