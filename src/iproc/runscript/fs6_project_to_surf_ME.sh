#!/bin/bash
set -xeou pipefail
# Written by Rodrigo Braga - November 2017

BOLD_TEDANA=$1
BOLD_OUT=$2
BOLD2=$3
SESST=$4
BOLDPATH=$5
OUTPATH=$6
scratch_base=$7
SMOOTH=$8
SMOOTH_NAME=${SMOOTH/./p}
mkdir -p $OUTPATH

#tmpdir=$(mktemp --directory --tmpdir=${scratch_base})

cd $OUTPATH

echo "------- RUNNING MULTI-ECHO FS6_PROJECT_TO_SURF_ME.SH -------"

if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    #we're running in a srun-safe environment
    _IPROC_RUNNER="srun --export=ALL -n 1 -c $SLURM_CPUS_PER_TASK"
else
    _IPROC_RUNNER=""
fi
#Project data
$_IPROC_RUNNER parallel -j 4 --tmpdir=${OUTPATH} <<EOF
mri_vol2surf --mov $BOLDPATH/tedana/${BOLD_TEDANA}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o ${OUTPATH}/lh.${BOLD_OUT}_fsaverage6.nii.gz --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/tedana/${BOLD_TEDANA}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o ${OUTPATH}/rh.${BOLD_OUT}_fsaverage6.nii.gz --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD2}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o ${OUTPATH}/lh.${BOLD2}_fsaverage6.nii.gz --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD2}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o ${OUTPATH}/rh.${BOLD2}_fsaverage6.nii.gz --reshape --interp trilinear
EOF

#Smooth data
$_IPROC_RUNNER parallel -j 4 --tmpdir=${OUTPATH} <<EOF
mri_surf2surf --hemi lh --s fsaverage6 --sval ${OUTPATH}/lh.${BOLD_OUT}_fsaverage6.nii.gz --cortex --fwhm-trg ${SMOOTH} --tval ${OUTPATH}/lh.${BOLD_OUT}_fsaverage6_sm${SMOOTH_NAME}.nii.gz --reshape
mri_surf2surf --hemi rh --s fsaverage6 --sval ${OUTPATH}/rh.${BOLD_OUT}_fsaverage6.nii.gz --cortex --fwhm-trg ${SMOOTH} --tval ${OUTPATH}/rh.${BOLD_OUT}_fsaverage6_sm${SMOOTH_NAME}.nii.gz --reshape
mri_surf2surf --hemi lh --s fsaverage6 --sval ${OUTPATH}/lh.${BOLD2}_fsaverage6.nii.gz --cortex --fwhm-trg ${SMOOTH} --tval ${OUTPATH}/lh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii.gz --reshape
mri_surf2surf --hemi rh --s fsaverage6 --sval ${OUTPATH}/rh.${BOLD2}_fsaverage6.nii.gz --cortex --fwhm-trg ${SMOOTH} --tval ${OUTPATH}/rh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii.gz --reshape

EOF


echo "Output at:"
echo "${OUTPATH}/lh.${BOLD_OUT}_fsaverage6_sm${SMOOTH_NAME}.nii.gz"
