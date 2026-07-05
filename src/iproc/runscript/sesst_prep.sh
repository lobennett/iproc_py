#!/bin/bash
set -xeou pipefail

sub_dir=${1}
SESST=${2}
TARGDIR=${3}
mpr_reorient=${4}

#these files may not exist at the time, but this was the most convenient place to put this
#TODO: make relative or do straight copies
ln -sf ${TARGDIR}/${SESST}_mpr_reorient.nii.gz ${TARGDIR}/mpr_reorient.nii.gz 
ln -sf ${TARGDIR}/${SESST}_mpr_reorient_brain.nii.gz ${TARGDIR}/mpr_reorient_brain.nii.gz 
ln -sf ${TARGDIR}/${SESST}_mpr_reorient_brain_mask.nii.gz ${TARGDIR}/mpr_reorient_brain_mask.nii.gz 
ln -sf ${TARGDIR}/${SESST}_mpr.nii.gz ${TARGDIR}/mpr.nii.gz 
# future commands expect this format, but sess_scanNo was needed to run multiple anatomicals, so remove e.g. _015/
ln -sf ${sub_dir} ${sub_dir%_*} 

# copy the output T1w (1x1x1mm) from recon-all to the cross_session_maps/templates folder
mpr=${TARGDIR}/${SESST}_mpr.nii.gz
mri_convert $sub_dir/mri/T1.mgz ${mpr}
fslreorient2std ${mpr} ${mpr_reorient}

# copy the T1w brainmask from recon-all (which is not binarized) to the cross_session_maps/templates 
# folder and binarize it
mri_convert ${sub_dir}/mri/brainmask.mgz ${TARGDIR}/${SESST}_mpr_brain_mask_tmp.nii.gz
fslreorient2std ${TARGDIR}/${SESST}_mpr_brain_mask_tmp ${TARGDIR}/${SESST}_mpr_reorient_brain_mask_tmp
rm ${TARGDIR}/${SESST}_mpr_brain_mask_tmp.nii.gz
fslmaths ${TARGDIR}/${SESST}_mpr_reorient_brain_mask_tmp -bin ${TARGDIR}/${SESST}_mpr_reorient_brain_mask.nii.gz
rm ${TARGDIR}/${SESST}_mpr_reorient_brain_mask_tmp.nii.gz

# copy the brain extracted T1w from recon-all to cross_session_maps/templates
mri_convert ${sub_dir}/mri/brain.mgz ${TARGDIR}/${SESST}_mpr_brain.nii.gz
fslreorient2std ${TARGDIR}/${SESST}_mpr_brain ${TARGDIR}/${SESST}_mpr_reorient_brain
