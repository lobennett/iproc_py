#!/bin/sh
set -xeou pipefail

RESID_IN=$1
WB_TS=$2
WB_MASK=$3
RESID_OUT=$4
OUTDIR=$5
MASK=$6
CODEDIR=$7
scratch_base=$8
MCOUT_TS=$9
MCOUTWB_TS=${10}
SCRATCHDIR=$(mktemp --directory --tmpdir=${scratch_base})

cpus=$(python -c "import os; cpus=len(os.sched_getaffinity(0)); print(cpus)")
export OMP_NUM_THREADS=${cpus}
echo "OMP_NUM_THREADS=${OMP_NUM_THREADS}"

pushd ${SCRATCHDIR}
#pushd ${OUTDIR}

fslmeants -i ${RESID_IN} -o ${WB_TS} -m ${WB_MASK}
# note: this WB_TS is identical in all respects to the one produced
#by runscript/calculate_nuisance_params.sh

paste -d ' ' ${WB_TS} ${MCOUT_TS} | tr -s " " > ${MCOUTWB_TS}

# remove from -input value each column in whole-brain timeseries
if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    #we're running in a srun-safe environment
    srun -n 1 -c $SLURM_CPUS_PER_TASK 3dTproject -ort ${MCOUTWB_TS} -input ${RESID_IN} -mask ${MASK} -prefix ${RESID_OUT}
else
    3dTproject -ort ${MCOUTWB_TS} -input ${RESID_IN} -mask ${MASK} -prefix ${RESID_OUT}
fi

3dAFNItoNIFTI ${RESID_OUT}*.BRIK -float

gzip -f ${RESID_OUT}*.nii
# delete the intermediates from earlier in this script
rm -f ${RESID_OUT}*.BRIK ${RESID_OUT}*.HEAD
rsync -av --remove-source-files ${SCRATCHDIR}/* ${OUTDIR}

