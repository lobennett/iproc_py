#!/bin/bash
set -xeou pipefail
TARGDIR=${1}

# Mask MPR on MNI space
betcmd="bet2 $TARGDIR/anat_mni_underlay.nii.gz $TARGDIR/anat_mni_underlay_brain -f 0.5 -m"
echo $betcmd; $betcmd
echo "Check Brain extraction"
echo "fslview $TARGDIR/anat_mni_underlay.nii.gz $TARGDIR/anat_mni_underlay_brain"

