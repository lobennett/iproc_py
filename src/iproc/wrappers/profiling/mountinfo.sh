#!/bin/bash
set -xeou pipefail
mountpoint=$1
shift

tmpfile=$(mktemp)
cat /proc/self/mountstats > $tmpfile
"$@"
/usr/sbin/mountstats mountstats --since $tmpfile $mountpoint
