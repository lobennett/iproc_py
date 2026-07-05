#!/bin/bash
set -xeou pipefail
SESST=${1}
TARGDIR=${2}
MOVIMG=${3}
VREG_REG=${4}
VREG_MAT=${5}
rmfiles=${6:-''}

bbregister --bold --s $SESST --init-fsl --mov ${MOVIMG} --reg ${VREG_REG} --fslmat ${VREG_MAT}


if [ -n "$rmfiles" ]; then
    for f in $rmfiles;do
        rm -rf "$f"
    done
fi
