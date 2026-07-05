#!/bin/bash
set -xeou pipefail

BET_OUT=${1}
TARGET=${2}
FLIRT_OUT=${3}
FLIRT_MAT_OUT=${4}

flirt -in ${BET_OUT} -ref ${TARGET} -out ${FLIRT_OUT} -omat ${FLIRT_MAT_OUT} -bins 256 -cost corratio -searchrx -180 180 -searchry -180 180 -searchrz -180 180 -dof 12 -interp trilinear
