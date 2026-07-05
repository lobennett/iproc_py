#!/bin/bash -l
set -xeou pipefail
module load centos6/0.0.1-fasrc01 parallel/20180522-fasrc01 ncf/1.0.0-fasrc01 miniconda2/3.19.0-ncf afni/2016_09_04-ncf fsl/5.0.4-ncf freesurfer/6.0.0-ncf mricrogl/2019_09_04-ncf matlab/7.4-ncf yaxil/0.2.2-ncf
export SUBJECTS_DIR=$1
export IPROC_SRUN=$2
export SLURM_CPUS_PER_TASK=$3
shift
shift
shift
"$@"
