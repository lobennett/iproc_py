#!/bin/bash
set -xeou pipefail

MERGED_VOL=${1}
#shifts allow us to pass in variable number of items to merge
shift
MERGE_FODDER=$@

fslmerge -t ${MERGED_VOL} ${MERGE_FODDER}
fslmaths ${MERGED_VOL} -Tmean ${MERGED_VOL}
