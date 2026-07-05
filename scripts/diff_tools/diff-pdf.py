#!/usr/bin/env python3

import filecmp
import logging
import tempfile
import subprocess as sp
from pathlib import Path
from argparse import ArgumentParser

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

def main():
    parser = ArgumentParser()
    parser.add_argument('-a', type=Path, required=True)    
    parser.add_argument('-b', type=Path, required=True)    
    args = parser.parse_args()

    A = args.a / 'QC'
    B = args.b / 'QC'

    for path_a in A.glob('*.pdf'):
        path_b = B / path_a.name
        if not path_b.exists():
            logger.warning(f'file does not exist {path_b}')
            continue
        logger.info(f'processing {path_a} and {path_b}')
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            tmpdir_a = tmpdir / 'A'
            tmpdir_b = tmpdir / 'B'
            tmpdir_a.mkdir()
            tmpdir_b.mkdir()
            pdf_to_png(path_a, tmpdir_a)
            pdf_to_png(path_b, tmpdir_b)
            logger.info(f'diffing {path_a} and {path_b}')
            dcmp = filecmp.dircmp(tmpdir_a, tmpdir_b)
            for item in dcmp.left_only:
                logger.error(f'file only in {tmpdir_a}: {item}')
                input('press enter to continue')
            for item in dcmp.right_only:
                logger.error(f'file only in {tmpdir_b}: {item}')
                input('press enter to continue')
            for item in dcmp.diff_files:
                logger.error(f'files are different {item}')
                input('press enter to continue')

def pdf_to_png(path, outdir):
    cmd = [
        'pdftoppm',
        '-png',
        str(path),
        str(outdir / path.stem)
    ]
    logger.info(f'converting {path} to png')
    logger.debug(f'running {cmd}')
    sp.check_output(cmd)

if __name__ == '__main__':
    main()
