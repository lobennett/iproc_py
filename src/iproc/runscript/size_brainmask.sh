#!/bin/bash
set -xeou pipefail
TARGDIR=${1}
FNIRT_dilated_bm_out=${2}

#Create dilated brain mask for reducing file size
fslmaths ${TARGDIR}/mpr_reorient_brain_mask -dilM ${TARGDIR}/mpr_reorient_brain_mask_dil10

#dilate 9 times 
for i in `seq 1 1 9`; do
    fslmaths ${TARGDIR}/mpr_reorient_brain_mask_dil10 -dilM ${TARGDIR}/mpr_reorient_brain_mask_dil10
done

fslmaths ${TARGDIR}/anat_mni_underlay_brain_mask -dilM ${TARGDIR}/anat_mni_underlay_brain_mask_dil10
for i in `seq 1 1 9`; do
    fslmaths ${TARGDIR}/anat_mni_underlay_brain_mask_dil10 -dilM ${FNIRT_dilated_bm_out}
done
