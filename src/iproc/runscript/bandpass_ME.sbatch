#!/bin/sh
set -xeou pipefail
# iProc_p5c.sh
# R. Braga 2018

RESID_OUT=$1
RESID_OUT_AFNI=$2
SPACE_AFFIX=$3
BPSS_OUT=$4
OUTDIR=$5
MASK=$6
CODEDIR=$7
scratch_base=$8
rmfiles=${9:-''}
SCRATCHDIR=$(mktemp --directory --tmpdir=${scratch_base})

cd $SCRATCHDIR
#cd $OUTDIR

echo "If script fails, run: cd $SCRATCHDIR; rm ${BPSS_OUT}+*.BRIK ${BPSS_OUT}+*.HEAD"
cpus=$(python -c "import os; cpus=len(os.sched_getaffinity(0)); print(cpus)")
export OMP_NUM_THREADS=${cpus}
echo "OMP_NUM_THREADS=${OMP_NUM_THREADS}"

3dcopy ${RESID_OUT} ${RESID_OUT_AFNI}

if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    #we're running in a srun-safe environment
    srun -n 1 -c $SLURM_CPUS_PER_TASK 3dBandpass -prefix $BPSS_OUT -mask $MASK 0.01 0.1 ${RESID_OUT_AFNI}+${SPACE_AFFIX}.BRIK
else
    3dBandpass -prefix $BPSS_OUT -mask $MASK 0.01 0.1 ${RESID_OUT_AFNI}+${SPACE_AFFIX}.BRIK
fi

3dAFNItoNIFTI ${BPSS_OUT}*.BRIK -float
gzip -f ${BPSS_OUT}.nii

# tlrc or orig
if [ -n "$rmfiles" ]; then
    for f in $rmfiles;do
    #rm ${RESID_OUT}.BRIK ${RESID_OUT}.HEAD
        rm -rf "$f"
    done
fi

# prevent these from piling up
rm ${BPSS_OUT}+*.BRIK ${BPSS_OUT}+*.HEAD

rsync -av --remove-source-files ${SCRATCHDIR}/* ${OUTDIR}
