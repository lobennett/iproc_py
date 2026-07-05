#!/bin/bash
set -xeou pipefail
MERGE_IN=${1}
MERGE_OUT=${2}
NUMVOL=${3}
DILMASK=${4}
MEAN_OUT=${5}
MIDVOL_OUT=${6}
rmfiles=${7:-''}

## extracted from iProc_p4a_sbatch.py
fslmerge -t ${MERGE_OUT} ${MERGE_IN}*
fslmaths ${MERGE_OUT} -mul ${DILMASK} ${MERGE_OUT}
fslmaths ${MERGE_OUT} -Tmean ${MEAN_OUT}
fslroi ${MERGE_OUT} ${MIDVOL_OUT} `expr ${NUMVOL} / 2` 1
#rm ${MERGE_IN}*
if [ -n "$rmfiles" ]; then
    for f in $rmfiles;do
        rm -rf "$f"
    done
fi
