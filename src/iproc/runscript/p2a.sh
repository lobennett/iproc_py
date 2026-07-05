#!/bin/bash
set -xeou pipefail
## Usage: iProc_p2a.sh {OUTDIR} {SCAN} {NUMVOL}
OUTDIR=$1
SCAN=$2
NUMVOL=$3
OUTFILE=$4
ME=$5

touch ${OUTFILE} #${OUTDIR}/${SCAN}_regressors_mc.dat

if [ "$ME" = "1" ]; then
	echo " ----- IN p2a.sh: MULTI ECHO -----"
	tail -n ${NUMVOL} ${OUTDIR}/${SCAN}_reorient_skip_mc_e1.par | awk 'BEGIN {n=0; init=0;} ($1 !~/#/) { ncol = NF; init = 1; } (init == 1 && $1 !~/#/) { if (NF != ncol) { print "format error"; exit -1;} for (j=1;j<=ncol;j++) data[n,int((j+2)%6) + 1] = $j; n++;} END { for (i = 0; i < n; i++) { printf("%d", i+1); for (j = 1;j <=ncol; j++) printf ("%10.6f", data[i,j]); printf("%10.6f\n",1);}}' > ${OUTFILE} #${OUTDIR}/${SCAN}_regressors_mc.dat
else
	echo " ----- IN p2a.sh: SINGLE ECHO -----"
	tail -n ${NUMVOL} ${OUTDIR}/${SCAN}_reorient_skip_mc.par | awk 'BEGIN {n=0; init=0;} ($1 !~/#/) { ncol = NF; init = 1; } (init == 1 && $1 !~/#/) { if (NF != ncol) { print "format error"; exit -1;} for (j=1;j<=ncol;j++) data[n,int((j+2)%6) + 1] = $j; n++;} END { for (i = 0; i < n; i++) { printf("%d", i+1); for (j = 1;j <=ncol; j++) printf ("%10.6f", data[i,j]); printf("%10.6f\n",1);}}' > ${OUTFILE} #${OUTDIR}/${SCAN}_regressors_mc.dat
fi