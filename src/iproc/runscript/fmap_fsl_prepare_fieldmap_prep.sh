#!/bin/bash
set -xeou pipefail
# Fieldmap prep script, originally from fm.sh.
# separated from xnat download for modularity.
FDIR=$1
outfile=$2 
MASK_COPY=$3 ## added by LMD for FMAP QCss

cd $FDIR
#Brain extract 
bet2 $FDIR/mag_img $FDIR/mag_img_brain -m
fslmaths $FDIR/mag_img_brain -ero $FDIR/mag_img_brain_ero

#fsl_prepare_fieldmap <scanner> <phase_image> <magnitude_image> <out_image> <deltaTE (in ms)> [--nocheck]
module load fsl/5.0.4-ncf
# 'almost always 2.46, unless you changed the echo times' https://lcni.uoregon.edu/kb-articles/kb-0003
fsl_prepare_fieldmap SIEMENS $FDIR/pha_img $FDIR/mag_img_brain_ero $outfile 2.46
cp mag_img_brain_mask.nii.gz $MASK_COPY  ## added by LMD for FMAP QC

