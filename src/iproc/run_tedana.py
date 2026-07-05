
import os
import re
import json
import argparse
import pandas as pd
from tedana import workflows

parser = argparse.ArgumentParser()

parser.add_argument('--sub',default=None, type=str,help='subject name, e.g., 1AB23')
parser.add_argument('--ses',default=None, type=str,help='session name e.g, 240401_1AB23')
parser.add_argument('--task',default=None, type=str,help='task name')
parser.add_argument('--run',default=None, type=int,help='3 digit run number as a string')
parser.add_argument('--mridatadir',default=None, type=str,help='full path to mri_data[_AP|_PA]')
parser.add_argument('--outname',default=None, type=str,help='name of output directory within mri_data session directory')
parser.add_argument('--space',default=None, type=str,help='MNI or NAT')
parser.add_argument('--resolution',default=None, type=str,help='111 or 222')


args = parser.parse_args()

sub = args.sub
ses = args.ses
task = args.task
run = args.run
mridatadir = args.mridatadir
outname = args.outname
space = args.space
resolution = args.resolution


# e.g., python run_tedana.py --mridatadir /path/to/mri_data --sub 1AB23 --ses 240401_1AB23 --task NBACKMECOR --run 8 --space MNI

data_dir = os.path.join(mridatadir,sub,f'{space}{resolution}',ses,f'{task}_{run:03d}')

print(data_dir)

# # Obtain Echo files
#find the prefix and suffix to that echo #
if space == 'MNI':
    nifti_files=[ f for f in os.listdir(data_dir)
            if (('_anat_mni_e' in f) & (f.endswith('.nii.gz'))) ]
elif space == 'NAT':
    nifti_files=[ f for f in os.listdir(data_dir)
            if (('_anat_e' in f) & (f.endswith('.nii.gz'))) ]
nifti_files.sort()
print(nifti_files)
numechos = len(nifti_files)

nifti_paths = [ os.path.join(data_dir,f) for f in nifti_files ]

print(f' ----- found {numechos} echos ----- ')

json_dir = os.path.join(mridatadir,sub,'NAT',ses,f'{task}_{run:03d}')
json_files=[ f for f in os.listdir(json_dir)
        if (('_reorient_skip_e' in f) & (f.endswith('.json'))) ]
json_files.sort()
print(json_files)


echo_times=[ json.load(open(os.path.join(json_dir,f)))['EchoTime'] for f in json_files ]
#echo_times.sort()
print(echo_times)

outDir=os.path.join(data_dir,outname)
print(outDir)

if os.path.isdir(outDir):
    print(f'Tedana was previously run for participant {sub}  Remove directory if they need to be reanalyzed')
        
else:
    workflows.tedana_workflow(
    nifti_paths,
    echo_times,
    out_dir=outDir,
    prefix=f'{ses}_bld{run:03}',
    fittype="curvefit",
    tedpca="kic",
    verbose=True,
    gscontrol=None)
