#!/bin/bash 
set -xeou pipefail

SUB=${1}
BNAME=${2}
TEMPLATE_DIR=${3}
RES_STR=${4}
outfile=${5}
rmfiles=${6:-''}

if [ "$RES_STR" = "1p2i" ]; then
	echo $RES_STR
	fslcreatehd 176 176 130 1 1.2 1.2 1.2 1 0 0 0 16 ${TEMPLATE_DIR}/${SUB}_D01_${BNAME}_midvol_hdr_tmp.nii.gz
else
	echo $RES_STR
	fslcreatehd 106 106 78 1 2 2 2 1 0 0 0 16 ${TEMPLATE_DIR}/${SUB}_D01_${BNAME}_midvol_hdr_tmp.nii.gz
fi

flirt -in ${TEMPLATE_DIR}/${SUB}_D01_${BNAME}_midvol_unwarp.nii.gz -applyxfm -out ${outfile} -paddingsize 0.0 -interp trilinear -ref ${TEMPLATE_DIR}/${SUB}_D01_${BNAME}_midvol_hdr_tmp.nii.gz

ln -sf ${outfile} $TEMPLATE_DIR/${SUB}_midvol_unwarp_${RES_STR}.nii.gz

if [ -n "$rmfiles" ]; then
    for f in $rmfiles;do
        rm -rf "$f"
    done
fi
