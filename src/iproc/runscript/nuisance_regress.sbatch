#!/bin/sh
set -xeou pipefail
# iProc_p5b.sh
# R. Braga 2018

RESID_IN=$1
NUIS_OUT=$2
RESID_OUT=$3
OUTDIR=$4
MASK=$5
CODEDIR=$6
scratch_base=$7
SCRATCHDIR=$(mktemp --directory --tmpdir=${scratch_base})

cd $SCRATCHDIR
#cd $OUTDIR
# do we really need to be doing this?
nuis_name=$(basename ${NUIS_OUT})
cp $NUIS_OUT ./${nuis_name}_tmp 

cpus=$(python -c "import os; cpus=len(os.sched_getaffinity(0)); print(cpus)")
export OMP_NUM_THREADS=${cpus}
echo "OMP_NUM_THREADS=${OMP_NUM_THREADS}"

if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    #we're running in a srun-safe environment
    srun -n 1 -c $SLURM_JOB_CPUS_PER_NODE 3dTproject -ort ${nuis_name}_tmp -input $RESID_IN -mask $MASK -prefix $RESID_OUT
else
    3dTproject -ort ${nuis_name}_tmp -input $RESID_IN -mask $MASK -prefix $RESID_OUT
fi

## during the above step, somehow AFNI understands if the input volume or mask is anat (orig) or MNI (tlrc), and names the output file accordingly.

rm ${nuis_name}_tmp

#cd $OUTDIR

3dAFNItoNIFTI ${RESID_OUT}*.BRIK -float
# 3dAFNItoNIFTI ${RESID_OUT}+orig.BRIK -float

gzip -f ${RESID_OUT}.nii


rsync -av --remove-source-files ${SCRATCHDIR}/* ${OUTDIR}

