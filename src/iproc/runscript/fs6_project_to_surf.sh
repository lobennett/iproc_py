#!/bin/bash
set -xeou pipefail
# Written by Rodrigo Braga - November 2017

BOLD=$1
BOLD2=$2
BOLD3=$3
SESST=$4
BOLDPATH=$5
OUTPATH=$6
scratch_base=$7
SMOOTH=$8
BOLD4=$9
SMOOTH_NAME=${SMOOTH/./p}
mkdir -p $OUTPATH

#tmpdir=$(mktemp --directory --tmpdir=${scratch_base})
tmpdir=$OUTPATH

cd $tmpdir

if [ "${IPROC_SRUN:-NO}" == "YES" ] ; then
    _IPROC_RUNNER="srun --export=ALL -n 1 -c $SLURM_CPUS_PER_TASK"
else
    _IPROC_RUNNER=""
fi
#Project data
$_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir} <<EOF
mri_vol2surf --mov $BOLDPATH/${BOLD}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/lh.${BOLD}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/rh.${BOLD}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD2}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/lh.${BOLD2}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD2}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/rh.${BOLD2}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD3}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/lh.${BOLD3}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD3}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/rh.${BOLD3}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD4}.nii.gz --regheader $SESST --hemi lh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/lh.${BOLD4}_fsaverage6.nii --reshape --interp trilinear
mri_vol2surf --mov $BOLDPATH/${BOLD4}.nii.gz --regheader $SESST --hemi rh --projfrac 0.5 --trgsubject fsaverage6 --o $tmpdir/rh.${BOLD4}_fsaverage6.nii --reshape --interp trilinear
EOF

#Smooth data
$_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir} <<EOF
mri_surf2surf --hemi lh --s fsaverage6 --sval $tmpdir/lh.${BOLD}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/lh.${BOLD}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi rh --s fsaverage6 --sval $tmpdir/rh.${BOLD}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/rh.${BOLD}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi lh --s fsaverage6 --sval $tmpdir/lh.${BOLD2}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/lh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi rh --s fsaverage6 --sval $tmpdir/rh.${BOLD2}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/rh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi lh --s fsaverage6 --sval $tmpdir/lh.${BOLD3}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/lh.${BOLD3}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi rh --s fsaverage6 --sval $tmpdir/rh.${BOLD3}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/rh.${BOLD3}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi lh --s fsaverage6 --sval $tmpdir/lh.${BOLD4}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/lh.${BOLD4}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
mri_surf2surf --hemi rh --s fsaverage6 --sval $tmpdir/rh.${BOLD4}_fsaverage6.nii --cortex --fwhm-trg ${SMOOTH} --tval $tmpdir/rh.${BOLD4}_fsaverage6_sm${SMOOTH_NAME}.nii --reshape
EOF

$_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir} <<EOF
gzip -f $tmpdir/lh.${BOLD}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/rh.${BOLD}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/lh.${BOLD}_fsaverage6.nii
gzip -f $tmpdir/rh.${BOLD}_fsaverage6.nii
EOF

$_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir} <<EOF
gzip -f $tmpdir/lh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/rh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/lh.${BOLD2}_fsaverage6.nii
gzip -f $tmpdir/rh.${BOLD2}_fsaverage6.nii
EOF

$_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir} <<EOF
gzip -f $tmpdir/lh.${BOLD3}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/rh.${BOLD3}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/lh.${BOLD3}_fsaverage6.nii
gzip -f $tmpdir/rh.${BOLD3}_fsaverage6.nii
EOF

$_IPROC_RUNNER parallel -j 4 --tmpdir=${tmpdir} <<EOF
gzip -f $tmpdir/lh.${BOLD4}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/rh.${BOLD4}_fsaverage6_sm${SMOOTH_NAME}.nii
gzip -f $tmpdir/lh.${BOLD4}_fsaverage6.nii
gzip -f $tmpdir/rh.${BOLD4}_fsaverage6.nii
EOF

#rsync -av --remove-source-files ${tmpdir}/* ${OUTPATH}

echo "Output at:"
echo "$OUTPATH/lh.${BOLD2}_fsaverage6_sm${SMOOTH_NAME}.nii.gz"
