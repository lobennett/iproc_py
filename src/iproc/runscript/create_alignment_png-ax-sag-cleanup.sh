#!/bin/bash
set -xeou pipefail

INFILE=${1}
AX_SWAP=${2}
SAG_SWAP=${3}
AX_ROI=${4}
SAG_ROI=${5}
AX_SIZE=${6}
SAG_SIZE=${7}
AX_SAMPLE=${8}
SAG_SAMPLE=${9}
AX_WIDTH=${10}
SAG_WIDTH=${11}
AX_SLICED=${12}
SAG_SLICED=${13}
AX_OUTFILE=${14}
SAG_OUTFILE=${15}
AX_LABEL=${16}
SAG_LABEL=${17}
CODEDIR=${18}
SWAP_FILES=${19}
ROI_FILES=${20}
PHOTO_FILES=${21}

fslswapdim "${INFILE}" -x y -z "${AX_SWAP}"
${CODEDIR}/runscript/create_alignment_png.sh "${AX_SWAP}" "${AX_ROI}" "${AX_SIZE}" "${AX_SAMPLE}" "${AX_WIDTH}" "${AX_SLICED}" "${AX_LABEL}" "${AX_OUTFILE}"

fslswapdim "${INFILE}" y z -x "${SAG_SWAP}" 
${CODEDIR}/runscript/create_alignment_png.sh "${SAG_SWAP}" "${SAG_ROI}" "${SAG_SIZE}" "${SAG_SAMPLE}" "${SAG_WIDTH}" "${SAG_SLICED}" "${SAG_LABEL}" "${SAG_OUTFILE}"

#rm ${SWAP_FILES} 
#rm ${ROI_FILES} 
#rm ${PHOTO_FILES}
