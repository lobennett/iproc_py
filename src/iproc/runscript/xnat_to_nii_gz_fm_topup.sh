#!/bin/bash
set -xeou
#Apply fieldmap correction # iProc_fm.sh 4GP28 170712_HTP02020 33 34 /ncf/cnl03/25/users/DN2/fm_test

# echo every line to stdout as it runs, and exit if any command returns nonzero,
# even if there is a pipe


sessionid=$1
first_FM_no=$2
second_FM_no=$3
FDIR=$4
codedir=$5
xnat_alias=$6
project=$7
outfile=$8
qdir=$9
OUTDIR=${10}
MASK_COPY=${11}

# change later if it comes up
b02b0=$codedir/configs/b02b0.cnf

cd $FDIR


dir1=AP_img
dir2=PA_img

# # # # 
#Download Magnitude image and convert to nifti
ArcGet.py -f flat -a ${xnat_alias} -l $sessionid -p $project --scans $first_FM_no -o $dir1
cd $FDIR/$dir1
dcm=$(ls | head -1)
${codedir}/dss.sh $qdir dcm2niix -b y -z y -o . ${dcm}
# ${codedir}/dss.sh $qdir dcm2nii ${dcm} <- deprecated, prior to XA30 upgrade
mv `ls *.nii.gz | tail -1` ../$dir1.nii.gz #Second image is what we want

#Download Phase image
cd $FDIR
ArcGet.py -f flat -a ${xnat_alias} -l $sessionid -p $project --scans $second_FM_no -o $dir2
cd $FDIR/$dir2
dcm=`ls | head -1`

#Get BIDS JSON sidecar for Phase image and parse out TotalReadoutTime
echo "running dcm2niix to produce json sidecar ../${dir2}.json for input file ${dcm}"
dcm2niix -b o -o ../ -f "${dir2}" "${dcm}"
echo "running jq to parse TotalReadoutTime from ../${dir2}.json"
TotalReadoutTime=$(jq ".TotalReadoutTime" "../${dir2}.json")
echo "TotalReadoutTime=${TotalReadoutTime}"

#Convert Phase image to NIFTI
${codedir}/dss.sh $qdir dcm2niix -b y -z y -o . ${dcm}
# ${codedir}/dss.sh $qdir dcm2nii ${dcm} <- deprecated, prior to XA30
mv *.nii.gz ../$dir2.nii.gz

cd $FDIR

# compute and write dicom info
datain=$FDIR/topupDatain.dat
# in case there is already such a file, overwrite it
rm -f $datain
echo "0 -1 0 $TotalReadoutTime" >> $datain
echo "0 1 0 $TotalReadoutTime" >> $datain
# we're assuming that the PA and AP files have all the same scan parameters here, e.g. TotalReadoutTime
${codedir}/runscript/fmap_topup_prep.sh ${FDIR} ${outfile} ${datain} ${b02b0} ${OUTDIR} ${MASK_COPY} # added OUTDIR and MASK_COPY LMD

rm -r $FDIR/$dir2
rm -r $FDIR/$dir1
