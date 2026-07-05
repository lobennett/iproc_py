#!/usr/bin/env python
'''
This script will crawl over a directory (-d) and produce a YAML formatted 
summary (-o) for specific file types:

- For binary files (e.g., .dat), you'll receive a simple CRC32.

- For NIFTI-1 files (e.g., .nii, .nii.gz), you'll receive a complex object containing the shape, mean, 
  standad deviation, min, and max.
  
- For FreeSurfer stats files (e.g., aseg.stats, lh.aparc.stats), you'll receive 
  a CRC32 of the file content after masking out content that is known to change 
  between invocations e.g., CreationTime, AnnotationFileTimeStamp, and user.
'''
import io
import re
import os
import zlib
import yaml
import logging
import nibabel as nib
import argparse as ap

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def main():
    parser = ap.ArgumentParser()
    parser.add_argument('-d', '--directory')
    parser.add_argument('-o', '--output-file')
    args = parser.parse_args()

    compare = {
        re.compile('.*\.nii(\.gz)?'): nifti_summary,
        re.compile('(aseg|(lh\.|rh\.)aparc).*\.stats'): freesurfer_summary,
        re.compile('(?!rusage).*\.dat'): binary_summary
    }

    args.directory = args.directory.rstrip('/') + '/'
    summary = dict()
    for root,dirs,files in os.walk(args.directory):
        if 'crash.iproc' in root:
            continue
        for f in files:
            fullfile = os.path.join(root, f)
            truncated = fullfile.replace(args.directory, '')
            file_summary = None
            for regex,func in iter(list(compare.items())):
                if regex.match(f):
                    logger.info('summarizing %s', truncated)
                    file_summary = func(fullfile)
                    break
            if file_summary:
                summary[truncated] = file_summary
    with open(args.output_file, 'w') as fo:
        fo.write(yaml.safe_dump(summary, default_flow_style=False))

def freesurfer_summary(f):
    mask = [
        re.compile('(CreationTime) .*()'),
        re.compile('(hostname) .*()'),
        re.compile('(user) .*()'),
        re.compile('(SUBJECTS_DIR) .*()'),
        re.compile('(AnnotationFileTimeStamp) .*()'),
        re.compile('(SegVolFileTimeStamp) .*()'),
        re.compile('(ColorTable) .*()'),
        re.compile('(ColorTableTimeStamp) .*()'),
        re.compile('(InVolFileTimeStamp) .*()'),
        re.compile('(PVVolFileTimeStamp) .*()'),
        re.compile('(cmdline.* --ctab) .* (--subject.*)')
    ]
    with open(f, 'r') as fo:
        content = fo.read()
    for m in mask:
        content = m.sub('\\1 ... \\2', content)
    return {
        'crc32': crc32(content)
    }

def binary_summary(f):
    return {
        'crc32': crc32file(f)
    }

def nifti_summary(f):
    nii = nib.load(f)
    return {
        'shape': nii.shape,
        'mean': float(nii.get_data().mean()),
        'stdev': float(nii.get_data().std()),
        'min': float(nii.get_data().min()),
        'max': float(nii.get_data().max())
    }
    
def crc32(x):
    return _crc32(io.BytesIO(x))

def crc32file(f):
    with open(f) as fp:
        return _crc32(fp)

def _crc32(f):
    prev = 0
    for line in f:
        prev = zlib.crc32(line, prev)
    return format(prev & 0xFFFFFFFF, '08x')

if __name__ == '__main__':
    main()

