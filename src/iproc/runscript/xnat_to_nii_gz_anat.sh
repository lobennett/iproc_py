#!/bin/bash
set -xeou 

workdir_anat=${1}
sessionid=${2}
ANAT_SCAN_NO=${3}
codedir=${4}
xnat_alias=${5}
project=${6}

outfile=${7}
outfile_reorient=${8}
qdir=${9}

scratch_base=${workdir_anat}/${ANAT_SCAN_NO}
mkdir -p $scratch_base
ANAT_SCRATCHDIR=$(mktemp --directory --tmpdir=${scratch_base})
# automatically creates outdir and downloads dicoms into it
ArcGet.py -f flat -a ${xnat_alias} --label ${sessionid} --output-dir ${ANAT_SCRATCHDIR} --scans ${ANAT_SCAN_NO} --project ${project}
cd ${ANAT_SCRATCHDIR}
dcm=`ls | head -1`
#${codedir}/dss.sh $qdir dcm2nii -r N ${dcm}
${codedir}/dss.sh $qdir dcm2niix -b y -z y -o . ${dcm}
# here is where BIDS directory would start
mv *.nii.gz tmp1.nii.gz 
#mri_convert --left-right-reverse-pix tmp1.nii.gz tmp.nii.gz

# check the orientation to make sure we are in AIL at this point
# [A]nterior-to-Posterior, [I]nferior-to-Superior, [L]eft-to-Right
#orientation="$(3dinfo -orient tmp.nii.gz | tr -d '[:space:]')"
#if [ "${orientation}" != "AIL" ]; then
#  echo "CRITICAL - T1w must be in [A]nterior-to-Posterior, [I]nferior-to-Superior, [L]eft-to-Right"
#  exit 1
#fi

# check the orientation to make sure we are in AIL at this point
# L P I
orientation="$(3dinfo -orient tmp1.nii.gz | tr -d '[:space:]')"
if [ "${orientation}" != "LPI" ]; then
  echo f"NOTE: Orientation is {$orientation}. Expecting LPI"
  #exit 1
fi

# # cast all pixel data to float if necessary
fslmaths tmp1.nii.gz tmp.nii.gz -odt float
# # move and flip axes (reorient) to [R]ight-to-Left, [P]osterior-to-Anterior, [I]nferior-to-Superior
#fslswapdim tmp.nii.gz -x y z tmp2.nii.gz

#rsync -aP "${ANAT_SCRATCHDIR}/tmp.nii.gz" ${outfile}
rsync --remove-source-files -aP "${ANAT_SCRATCHDIR}/tmp.nii.gz" ${outfile_reorient}
