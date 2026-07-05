#!/bin/sh
set -xeou pipefail
# iProc_p5c.sh
# R. Braga 2018

RESID_OUT=$1
BPSS_OUT=$2
OUTDIR=$3
MASK=$4
CODEDIR=$5
scratch_base=$6
rmfiles=${7:-''}
SCRATCHDIR=$(mktemp --directory --tmpdir=${scratch_base})

cd $SCRATCHDIR
#cd $OUTDIR

echo "If script fails, run: cd $SCRATCHDIR; rm ${BPSS_OUT}+*.BRIK ${BPSS_OUT}+*.HEAD"
cpus=$(python -c "import os; cpus=len(os.sched_getaffinity(0)); print(cpus)")
export OMP_NUM_THREADS=${cpus}
echo "OMP_NUM_THREADS=${OMP_NUM_THREADS}"

if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    #we're running in a srun-safe environment
    srun -n 1 -c $SLURM_CPUS_PER_TASK 3dBandpass -prefix $BPSS_OUT -mask $MASK 0.01 0.1 ${RESID_OUT}.BRIK
else
    3dBandpass -prefix $BPSS_OUT -mask $MASK 0.01 0.1 ${RESID_OUT}.BRIK
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
