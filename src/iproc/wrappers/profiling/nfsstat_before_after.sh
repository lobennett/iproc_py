#!/bin/bash
set -xeou pipefail
/usr/sbin/nfsstat -c
"$@"
/usr/sbin/nfsstat -c
