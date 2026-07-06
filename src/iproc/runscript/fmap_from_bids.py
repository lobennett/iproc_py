#!/usr/bin/env -S python3 -u

import os
import re
import sys
import json
import math
import shutil
import logging
import argparse as ap
import tempfile as tf
import subprocess as sp
import iproc.commons as commons

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def main():
    parser = ap.ArgumentParser('Import field map files from BIDS')
    parser.add_argument('--input-fmapm', nargs='+', default=[],
        help='Input BIDS magnitude field map files')
    parser.add_argument('--input-fmapp', nargs='+', default=[],
        help='Input BIDS phasediff field map files')
    parser.add_argument('--output-fmapm',
        help='Output fieldmap magnitude file')
    parser.add_argument('--output-fmapp',
        help='Output fieldmap phasediff file')
    parser.add_argument('--output-fieldmap',
        help='Output fieldmap file')
    parser.add_argument('--work-dir', 
        help='Working directory')
    parser.add_argument('--output-maskcopy',
        help='Copy of fieldmap mag_img_brain_mask file for QC PDF')
    args = parser.parse_args()
    
    if not os.path.exists(args.work_dir):
        os.makedirs(args.work_dir)

    fmapm_basename = os.path.basename(args.output_fmapm)
    fmapm_prefix = re.sub('.nii(.gz)?', '', fmapm_basename)

    # create a temporary directory for this process
    tempd = tf.mkdtemp(dir=args.work_dir)
    logger.info(f'created temporary working directory: {tempd}')
    os.chdir(tempd)

    # Preserve the original phase input path(s) before merge() destructively
    # pops from the list, so the adjacent JSON sidecar can still be located.
    orig_fmapp_inputs = list(args.input_fmapp)

    # copy or merge magnitude image(s)
    fmapm = os.path.join(tempd, os.path.basename(args.output_fmapm))
    merge(args.input_fmapm, fmapm)

    # copy or merge phasediff image(s)
    fmapp = os.path.join(tempd, os.path.basename(args.output_fmapp))
    merge(args.input_fmapp, fmapp)

    # extrate brain from magnitide image
    fmapm_bet = os.path.join(tempd, f'{fmapm_prefix}_brain')
    brain_extract(fmapm, fmapm_bet)

    # erode the brain mask slightly
    fmapm_eroded = os.path.join(tempd, f'{fmapm_prefix}_brain_ero.nii.gz')
    erode(fmapm_bet, fmapm_eroded)
    
    # Read Manufacturer from the phase input's adjacent JSON sidecar to decide
    # the fieldmap-preparation path. Siemens/Varian (or unknown/absent) take
    # upstream's exact fsl_prepare_fieldmap SIEMENS ... 2.46 path (delta_te is
    # kept hardcoded 2.46 for byte-behavior parity with upstream — it is NOT
    # read from JSON). GE/Philips take the Hz->rad/s branch (new capability).
    manufacturer = read_manufacturer(orig_fmapp_inputs)

    # prepare the field map
    fieldmap = os.path.join(tempd, os.path.basename(args.output_fieldmap))
    prepare_fieldmap((fmapp, fmapm_eroded), fieldmap,
                     manufacturer=manufacturer, delta_te=2.46)

    # move derived files to final destination
    logger.info('moving %s to %s', fmapm, args.output_fmapm)
    shutil.move(fmapm, args.output_fmapm)
    logger.info('moving %s to %s', fmapp, args.output_fmapp)
    shutil.move(fmapp, args.output_fmapp)
    logger.info('moving %s to %s', fieldmap, args.output_fieldmap)
    shutil.move(fieldmap, args.output_fieldmap)

    # also move some intermediate derived files
    dirname = os.path.dirname(args.output_fmapm)
    _dest = os.path.join(dirname, f'{os.path.basename(fmapm_bet)}.nii.gz')
    logger.info(f'moving {fmapm_bet}.nii.gz to {_dest}')
    shutil.move(f'{fmapm_bet}.nii.gz', _dest)
    _dest = os.path.join(dirname, f'{os.path.basename(fmapm_bet)}_mask.nii.gz')
    logger.info(f'moving {fmapm_bet}_mask.nii.gz to {_dest}')
    shutil.move(f'{fmapm_bet}_mask.nii.gz', _dest)
    _dest = os.path.join(dirname, os.path.basename(fmapm_eroded))
    logger.info(f'moving {fmapm_eroded} to {_dest}')
    shutil.move(fmapm_eroded, _dest)

    # added LMD:  copy the output mag_img_brain_mask file for use in QC PDF
    dirname = os.path.dirname(args.output_fmapm)
    fmapm_brainmask = os.path.join(dirname, f'{fmapm_prefix}_brain_mask')
    fmapm_brainmask_copy = os.path.basename(args.output_maskcopy)
    logger.info(f'copying {fmapm_brainmask}.nii.gz to {fmapm_brainmask_copy}')
    shutil.copy(f'{fmapm_brainmask}.nii.gz', fmapm_brainmask_copy)

    # remove the temporary directory
    logger.info(f'removing temporary directory {tempd}')
    shutil.rmtree(tempd)

def merge(input, output):
    if not input:
        raise ValueError('merge function input is empty')
    # only symlink a single image
    if len(input) == 1:
        input = input.pop()
        logger.info('copying {0} to {1}'.format(input, output))
        if os.path.exists(output):
            return
        shutil.copy2(input, output)
        return
    # merge multiple images if necessary
    cmd = [
        'fslmerge',
        '-t',
        output
    ]
    cmd.extend(input)
    logger.info(cmd)
    commons.check_output(cmd)

def brain_extract(input, output):
    cmd = [
        'bet2',
        input,
        output,
        '-m'
    ]
    _cmd = sp.list2cmdline(cmd)
    cmd = f'module load fsl/4.0.3-ncf && {_cmd}'
    logger.info(cmd)
    commons.check_output(cmd, shell=True)

def erode(input, output, invert=True):
    '''
    Basically zero out any voxels outside the mask
    '''
    cmd = [
        'fslmaths',
        input,
        '-ero',
        output
    ]
    _cmd = sp.list2cmdline(cmd)
    cmd = f'module load fsl/4.0.3-ncf && {_cmd}'
    logger.info(cmd)
    commons.check_output(cmd, shell=True)

def read_manufacturer(fmapp_inputs):
    '''Read 'Manufacturer' from the phase input's adjacent JSON sidecar.

    Returns the manufacturer string (upper-cased), or '' if no sidecar exists
    or the field is absent/unreadable. Only the manufacturer is read here; the
    echo-time delta is intentionally NOT read, because the Siemens/Varian path
    keeps upstream's hardcoded 2.46 ms for byte-behavior parity with upstream.
    '''
    for inp in fmapp_inputs:
        candidate = re.sub(r'\.nii(\.gz)?$', '.json', inp)
        if os.path.exists(candidate):
            try:
                with open(candidate) as f:
                    js = json.load(f)
            except Exception as e:  # noqa: BLE001
                logger.warning('could not read JSON sidecar %s: %s', candidate, e)
                return ''
            mfr = js.get('Manufacturer', '') or ''
            logger.info('phase JSON sidecar %s: Manufacturer=%r', candidate, mfr)
            return mfr.upper()
    logger.info('no phase JSON sidecar found; defaulting to upstream SIEMENS path')
    return ''


def choose_fieldmap_cmd(manufacturer, delta_te, phase, eroded_mag, out):
    '''Build the fieldmap-preparation argv (pure; no FSL execution).

    GE/Philips -> ``fslmaths <phase> -mul <2*pi> -mas <eroded_mag> <out>``:
        GE/Philips fieldmaps are Hz maps; multiply by 2*pi for Hz->rad/s then
        mask with the eroded brain magnitude. This is a new capability upstream
        lacks (upstream/fsl_prepare_fieldmap only supports SIEMENS/VARIAN).

    Otherwise (Siemens/Varian, or manufacturer absent/unknown) ->
        ``fsl_prepare_fieldmap SIEMENS <phase> <eroded_mag> <out> 2.46``:
        upstream's exact command. ``delta_te`` is passed in hardcoded (2.46)
        and never read from JSON, so this path stays byte-behavior-identical
        to upstream.
    '''
    mfr = (manufacturer or '').upper()
    if 'GE' in mfr or 'PHILIPS' in mfr:
        two_pi = 2 * math.pi
        logger.warning(
            'GE/Philips fieldmap (Manufacturer=%s): using Hz->rad/s conversion '
            '(x%.6f) -- VERIFY results', mfr, two_pi)
        return ['fslmaths', phase, '-mul', f'{two_pi:.6f}', '-mas', eroded_mag, out]
    return ['fsl_prepare_fieldmap', 'SIEMENS', phase, eroded_mag, out, str(delta_te)]


def prepare_fieldmap(input, output, manufacturer=None, delta_te=2.46):
    fmapp, fmapm_eroded = input
    cmd = choose_fieldmap_cmd(manufacturer, delta_te, fmapp, fmapm_eroded, output)
    logger.info(cmd)
    commons.check_output(cmd)

if __name__ == '__main__':
    main()

