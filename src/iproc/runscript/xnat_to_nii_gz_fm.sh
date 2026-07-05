#!/bin/bash
set -xeou
#Apply fieldmap correction # iProc_fm.sh 4GP28 170712_HTP02020 33 34 /ncf/cnl03/25/users/DN2/fm_test

sessionid=$1
# In XNAT, M is magnitude image (e.g. 33 in DN2), P is phase (e.g. 34 in DN2)
# M is always collected first, and has twice as many slices as P
MNUM=$2
PNUM=$3
FDIR=$4
codedir=$5
xnat_alias=$6
project=$7
outfile=$8
qdir=${9}
outdir=$10
maskcopy=$11

cd $FDIR

# # # # 
#Download Magnitude image and convert to nifti
ArcGet.py -f flat -a ${xnat_alias} -l $sessionid -p $project --scans $MNUM -o mag_img
cd $FDIR/mag_img
dcm=$(ls | head -1)
echo 'foo'
${codedir}/dss.sh $qdir dcm2niix -b y -z y -o . ${dcm}
mv `ls *.nii.gz | tail -1` ../mag_img.nii.gz 

#Download Phase image and convert to nifti
cd $FDIR
ArcGet.py -f flat -a ${xnat_alias} -l $sessionid -p $project --scans $PNUM -o pha_img
cd $FDIR/pha_img
dcm=`ls | head -1`
${codedir}/dss.sh $qdir dcm2niix -b y -z y -o . ${dcm}
mv *.nii.gz ../pha_img.nii.gz

cd $FDIR
rm -r $FDIR/pha_img
rm -r $FDIR/mag_img

${codedir}/runscript/fmap_fsl_prepare_fieldmap_prep.sh ${FDIR} ${outfile}.nii.gz ${maskcopy}