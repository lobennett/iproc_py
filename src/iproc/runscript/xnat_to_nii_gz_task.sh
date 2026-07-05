#!/bin/bash
set -xeou 

echo "----- IN XNAT TO NII GZ TASK -----"
workdir=${1}
sessionid=${2}
task_scan_no=${3}
codedir=${4}
xnat_alias=${5}
project=${6}

outfile=${7}

SKIP=${8}
NUMVOL=${9}
NUMECHOS=${10}
qdir=${11}

bold_no=$(printf %03d ${task_scan_no})
fname_base=${sessionid}_bld${bold_no}

OUTDIR=$(dirname ${outfile})
scratch_base=${workdir}/${task_scan_no}/
mkdir -p $scratch_base
SCRATCHDIR=$(mktemp --directory --tmpdir=${scratch_base}) #makes the "tmp.*" directory, cd's to that

ArcGet.py -f flat -a ${xnat_alias} --label ${sessionid} --output-dir ${SCRATCHDIR} --scans ${task_scan_no} --project ${project}
cd ${SCRATCHDIR}
dcm=`ls | head -1` 	### get first listed file in the scratch directory

# get echo time from dicom
echo "***----- IN MULTI-ECHO VERSION OF XNAT_TO_NII_GZ_TASK -----***"
#dcm2niix -s y -b o -o . -f metadata $dcm  ### -s: single file mode, -b: BIDS json sidecar file, -o/-f output directory/filename


### old version, pre-scanner software upgrade in Feb 2024
### pulling echo time from dicom doesn't work this way any more
### also do not need to divide by 1000, already in msecs

# EchoTime_keypair='0018 0081' # from iproc v.1.1.1
# EchoTime=$(mri_probedicom --i $dcm --t $EchoTime_keypair | cut -d* -f1) # from iproc v.1.1.1

# EchoTime multiplied by conversion factor from MS to Sec
#EchoTime_sec=$(bc -l <<< "((1/1000) * $EchoTime)") 
#precision=4
#EchoTime_sec=$(/usr/bin/printf "%.*f\n" $precision $EchoTime_sec)
#if [ -z "$EchoTime_sec" ]; then
#    exit 1 
#fi

#For multi-echo, this creates a nii.gz volume for EACH echo with _e{echoNum} suffix
${codedir}/dss.sh $qdir dcm2niix -z y -o . -f ${fname_base} ${dcm}

# --------------------------------------------
# --------------- SINGLE ECHO ----------------
# --------------------------------------------

if [ $NUMECHOS -eq 1 ]; then
	# here is where BIDS directory would start
	mv *.nii.gz tmp.nii.gz

	# check that we have enough time points  
	total_timepoints=$(fslnvols "${SCRATCHDIR}/tmp.nii.gz" )
	((requested_timepoints=${SKIP}+${NUMVOL}))
	if [ "$total_timepoints" -lt "$requested_timepoints" ]; then
	    echo "total timepoints are less than the sum of skipped and the numvol set in the task csv."
	    exit 1
	fi
	# for now, just to get the BIDS info
	dcm2niix -x i -z i -w 1 -s y -f ${fname_base} -o "${OUTDIR}" $dcm 
	# we only want the JSON
	rm "${OUTDIR}"/${fname_base}.nii.gz
	#BandwidthPerPixelPhaseEncode_keypair='0019 1028'
	#BandwidthPerPixelPhaseEncode=$(mri_probedicom --i $dcm --t $BandwidthPerPixelPhaseEncode_keypair)

	#AcquisitionMatrixText_keypair='0051 100b'
	#This is usually the case, but is not guaranteed according to https://lcni.uoregon.edu/kb-articles/kb-0003
	#MatrixSizePhase=$(mri_probedicom --i $dcm --t $AcquisitionMatrixText_keypair | cut -d* -f1)
	#EffectiveEchoSpacing=$(bc -l <<< "(1/($BandwidthPerPixelPhaseEncode * $MatrixSizePhase))") 

	EchoTime=$(sed -rn 's@\s+"EchoTime": (.*),@\1@p' *.json)
	#EchoTime_sec=$(bc -l <<< "((1/1000) * $EchoTime)") 
	precision=4
	#EchoTime_sec=$(/usr/bin/printf "%.*f\n" $precision $EchoTime_sec)
	EchoTime_sec=$(/usr/bin/printf "%.*f\n" $precision $EchoTime)
	if [ -z "$EchoTime_sec" ]; then
	    exit 1 
	fi

	EffectiveEchoSpacing=$(sed -rn 's@\s+"EffectiveEchoSpacing": (.*),@\1@p' *.json)
	precision=5
	EffectiveEchoSpacing=$(/usr/bin/printf "%.*f\n" $precision $EffectiveEchoSpacing)
	if [ -z "$EffectiveEchoSpacing" ]; then
	    exit 1
	fi

	fslmaths tmp.nii.gz tmp.nii.gz -odt float #convert to float
	fslroi ${SCRATCHDIR}/tmp ${SCRATCHDIR}/tmp_reorient_skip.nii.gz ${SKIP} ${NUMVOL} #trim extra timepoints
	rsync --remove-source-files -aP "${SCRATCHDIR}/tmp_reorient_skip.nii.gz" ${outfile}.nii.gz
	#write echo time to a file
	echo $EchoTime_sec > $OUTDIR/${fname_base}_echoTime.sec
	echo $EffectiveEchoSpacing > $OUTDIR/${fname_base}_dwellTime.sec
# --------------------------------------------
# --------------- MULTI ECHO -----------------
# --------------------------------------------

# same as single echo above, but do it for each echo which have a _e# suffix

else 
	for THISECHO in $(seq 1 $NUMECHOS); do
		# here is where BIDS directory would start
		mv *_e${THISECHO}.nii.gz tmp_e${THISECHO}.nii.gz

		# check that we have enough time points  
		total_timepoints=$(fslnvols "${SCRATCHDIR}/tmp_e${THISECHO}.nii.gz" )
		((requested_timepoints=${SKIP}+${NUMVOL}))
		if [ "$total_timepoints" -lt "$requested_timepoints" ]; then
		    echo "total timepoints are less than the sum of skipped and the numvol set in the task csv."
		    exit 1
		fi

		EchoTime=$(sed -rn 's@\s+"EchoTime": (.*),@\1@p' *_e${THISECHO}.json)
		precision=4
		EchoTime_sec=$(/usr/bin/printf "%.*f\n" $precision $EchoTime)
		if [ -z "$EchoTime_sec" ]; then
		    exit 1 
		fi

		EffectiveEchoSpacing=$(sed -rn 's@\s+"EffectiveEchoSpacing": (.*),@\1@p' *_e${THISECHO}.json)
		precision=5
		EffectiveEchoSpacing=$(/usr/bin/printf "%.*f\n" $precision $EffectiveEchoSpacing)
		if [ -z "$EffectiveEchoSpacing" ]; then
		    exit 1
		fi

		fslmaths tmp_e${THISECHO}.nii.gz tmp_e${THISECHO}.nii.gz -odt float #convert to float
		fslroi ${SCRATCHDIR}/tmp_e${THISECHO} ${SCRATCHDIR}/tmp_reorient_skip_e${THISECHO}.nii.gz ${SKIP} ${NUMVOL} #trim extra timepoints
		rsync --remove-source-files -aP ${SCRATCHDIR}/*_e${THISECHO}.json ${outfile}_e${THISECHO}.json
		rsync --remove-source-files -aP "${SCRATCHDIR}/tmp_reorient_skip_e${THISECHO}.nii.gz" ${outfile}_e${THISECHO}.nii.gz

		#write echo time to a file
		echo $EchoTime_sec > $OUTDIR/${fname_base}_echoTime_e${THISECHO}.sec
		echo $EffectiveEchoSpacing > $OUTDIR/${fname_base}_dwellTime_e${THISECHO}.sec
	done
fi
