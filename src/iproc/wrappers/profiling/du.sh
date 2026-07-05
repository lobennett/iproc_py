#!/bin/bash
# to calculate cumulative disk size 
set -xeou pipefail
mountpoint=$1
shift

du -s $mountpoint
"$@"
echo "du -s :"
du -s $mountpoint
