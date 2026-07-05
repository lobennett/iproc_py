# iProc Container Build Guide

Apptainer (Singularity) container for the iProc v2.6 preprocessing pipeline,
designed for Stanford Sherlock HPC.

## What's Inside

| Software | Version | Source | Purpose |
|----------|---------|--------|---------|
| FSL | 4.1.9 / 5.0.8 / 6.0.7+ | fsl.fmrib.ox.ac.uk (oldversions/ + fslconda installer) | Core neuroimaging (multi-version, runtime-switched — see mapping below) |
| FreeSurfer | 6.0.0 | surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/6.0.0/ | Surface reconstruction (`recon-all`) |
| AFNI | latest-stable* | afni.nimh.nih.gov/pub/dist/tgz/linux_openmp_64.tgz | Regression (`3dTproject`, `3dAFNItoNIFTI`) |
| ANTs | 2.4.4 (pinned) | github.com/ANTsX/ANTs/releases/download/v2.4.4/ | Advanced normalization |
| Python | 3.11 (deadsnakes PPA) | — | iProc runtime + tedana |
| GNU Parallel | Ubuntu 22.04 apt package | — | Task parallelization |
| dcm2niix | v1.0.20230411 (pinned) | github.com/rordenlab/dcm2niix/releases/ | DICOM-to-NIfTI conversion |
| ImageMagick | system (apt) | — | QC image generation |
| Connectome Workbench | 2.1.0 (pinned) | humanconnectome.org/storage/app/media/workbench/ | Surface data tools (not actively used by iProc; included for future use) |
| MRIcroGL | v1.2.20190902 (pinned) | github.com/rordenlab/MRIcroGL/releases/ | Visualization |
| Core Python deps | exact-pinned (numpy 1.25.2, scipy 1.16.3, nibabel 5.3.3, PyYAML 5.2, …) | PyPI | iProc runtime |
| tedana + ICA stack | NOT fully pinned (scikit-learn, nilearn, mapca, bokeh, robustica, seaborn, …) | PyPI | Multi-echo ICA — see reproducibility caveat below |

*AFNI has no dated/versioned Linux binary tarball upstream — see
"AFNI Version Pin" below for why it intentionally tracks latest-stable and
how the build records provenance to compensate.

**MATLAB is NOT required** — fully replaced by Python in the iProc codebase.

## Version Pins

All pins are also documented in a comment block at the top of `%post` in
`iproc.def`. URLs were verified reachable (HTTP 200) on 2026-07-05.

| Tool | Pin | Notes |
|---|---|---|
| dcm2niix | `v1.0.20230411` | Versioned GitHub release |
| FSL (→ iProc 4.0.3) | `4.1.9` | Closest available; see FSL Version Mapping below |
| FSL (→ iProc 5.0.4, 5.0.10) | `5.0.8` | Closest available |
| FSL (→ iProc 6.0.1) | `6.0.7+` | Installed via `fslinstaller.py` (conda); exact patch version floats within 6.0.x |
| FreeSurfer | `6.0.0` | Versioned tarball |
| ANTs | `2.4.4` | Versioned GitHub release |
| Connectome Workbench | `2.1.0` | `v1.3.2` (the version iProc historically validated against) is no longer distributed upstream |
| MRIcroGL | `v1.2.20190902` | Versioned GitHub release tag |
| Core Python deps | exact (`==`) pins | numpy/scipy/nibabel/PyYAML/… — first `pip install` block, `iproc.def` %post section 10 |
| tedana + ICA stack | **not** fully pinned | scikit-learn, nilearn, mapca, bokeh, robustica, seaborn, … — second block, section 10 (see caveat below) |

### Reproducibility caveat: tedana / multi-echo stack

Only the core iProc Python deps and the neuroimaging toolchain are exactly
pinned. The multi-echo **tedana** stack and its transitive deps
(scikit-learn, nilearn, mapca, bokeh, robustica, seaborn, threadpoolctl,
joblib, pybtex, tqdm, …) are installed *unpinned* — only `numpy==1.25.2` /
`scipy==1.16.3` are held fixed while they resolve. Multi-echo/ICA denoising
output is therefore **not guaranteed byte-reproducible across rebuilds**. If
you need reproducible multi-echo output, pin this stack yourself in
`iproc.def` %post section 10 and rebuild.

> **Build note (`PyYAML==5.2`):** this pin installed cleanly locally and
> matches upstream, but building `PyYAML==5.2` on the Linux container under
> Python 3.11 is a Phase-B / container-build verification item — confirm the
> wheel/sdist builds there before relying on the image.

### AFNI Version Pin

AFNI does not publish dated/versioned tarballs for its Linux binary
distribution — only a rolling "latest" tgz per platform at a fixed URL
(confirmed against the directory listing at
`https://afni.nimh.nih.gov/pub/dist/tgz/` on 2026-07-05; unlike the macOS
builds, which do carry versioned filenames such as
`macos_12_x86_64.AFNI_25.3.03.tgz`, no equivalent exists for
`linux_openmp_64.tgz`).

iProc only calls `3dTproject` and `3dAFNItoNIFTI`, both long-stable,
narrowly-scoped utilities, so the container intentionally tracks AFNI's
"latest stable" Linux build rather than block on a pin upstream doesn't
offer. As a partial mitigation, the build captures provenance at build
time:
- The tarball's HTTP `Last-Modified`/`ETag` headers, written to
  `/opt/afni-download-provenance.txt` inside the image.
- The actual installed `afni -version` string, written to
  `/opt/afni/INSTALLED_VERSION.txt` inside the image.

At doc time (2026-07-05) the tarball's `Last-Modified` header was
`Wed, 01 Jul 2026 22:38:21 GMT`. Check `/opt/afni/INSTALLED_VERSION.txt`
in any built image for the version actually baked in.

## FSL Version Mapping

iProc switches between FSL 4.0.3, 5.0.4, 5.0.10, and 6.0.1 at runtime.
FSL no longer distributes those exact versions as binaries. The container
installs the closest available and maps them via symlinks + module shim:

| iProc requests | Container installs | Source |
|---|---|---|
| 4.0.3 | 4.1.9 | fsl.fmrib.ox.ac.uk/fsldownloads/oldversions/ |
| 5.0.4, 5.0.10 | 5.0.8 | fsl.fmrib.ox.ac.uk/fsldownloads/oldversions/ |
| 6.0.1 | 6.0.7+ | fslinstaller.py (conda) |

**To use the exact validated versions**, copy them from Sherlock (see below).

## Before You Build: Stage Your FreeSurfer License

`container/downloads/` is intentionally empty in this repo (no FSL
tarballs, no license) — those are user-supplied, not vendored. Before
running `build.sh`, you **must** place your own FreeSurfer license file at:

```
container/downloads/license.txt
```

Get a free license at https://surfer.nmr.mgh.harvard.edu/registration.html.
`iproc.def`'s `%files` section copies `downloads/license.txt` into the
image at `/opt/freesurfer-6.0.0/license.txt`; the build will fail with a
clear error if it's missing.

## Build (Quick Start)

The only file you need to provide is the FreeSurfer license. Everything
else downloads automatically during the build.

```bash
cd iProc/container

# FreeSurfer license (must be staged by you — see above)
ls downloads/license.txt   # should exist

# Build (~30-60 min, needs ~25 GB disk, internet access)
./build.sh
```

## (Optional) Use Exact FSL Versions from Sherlock

If you want bit-identical reproduction of iProc's validated pipeline, copy
the exact FSL installations from Sherlock before building:

```bash
# SSH into Sherlock
ssh ${USER}@login.sherlock.stanford.edu

# For each FSL version, find and tar the installation:
module load system
module load fsl/4.0.3    # or however Sherlock names it
tar czf fsl-4.0.3.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)

module swap fsl/4.0.3 fsl/5.0.4
tar czf fsl-5.0.4.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)

module swap fsl/5.0.4 fsl/5.0.10
tar czf fsl-5.0.10.tar.gz -C $(dirname $FSLDIR) $(basename $FSLDIR)

# Copy back to your Mac
exit
scp ${USER}@login.sherlock.stanford.edu:fsl-*.tar.gz container/downloads/
```

Then uncomment the corresponding `%files` lines in `iproc.def` and rebuild.

## Transfer to Sherlock

```bash
scp iproc.sif ${USER}@login.sherlock.stanford.edu:$SCRATCH/containers/
```

## Running on Sherlock

### Interactive test
```bash
# --writable-tmpfs gives an ephemeral overlay so `pip install -e .` can write
# into the otherwise read-only in-image /opt/iproc-venv.
apptainer shell --writable-tmpfs --bind $SCRATCH:/scratch,$OAK:/oak \
    $SCRATCH/containers/iproc.sif
```

Inside the container:
```bash
source /opt/iproc-venv/bin/activate
cd /path/to/iProc
pip install -e .      # first time only (needs --writable-tmpfs, above)
iproc --help
```

### SLURM batch job
```bash
#!/bin/bash
#SBATCH --job-name=iproc_setup
#SBATCH --partition=normal
#SBATCH --time=04:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4

CONTAINER=$SCRATCH/containers/iproc.sif
IPROC_DIR=$OAK/path/to/iProc
CONFIG=$OAK/path/to/mri_data/SUB/subject_lists/SUB.cfg
BIDS=$OAK/path/to/bids/sub-SUB

# --writable-tmpfs: ephemeral overlay so `pip install -e .` can write into the
# read-only in-image /opt/iproc-venv. set -eo pipefail so a failed install/run
# fails the job instead of passing silently.
apptainer exec \
    --writable-tmpfs \
    --bind $SCRATCH:/scratch,$OAK:/oak \
    $CONTAINER \
    bash -c "
        set -eo pipefail
        source /opt/module_shim.sh
        source /opt/iproc-venv/bin/activate
        cd ${IPROC_DIR}
        pip install -e .
        iproc -c ${CONFIG} -s setup --bids ${BIDS} --executor local
    "
```

### All stages in sequence
```bash
for stage in setup bet unwarp_motioncorrect_align T1_warp_and_mask \
             combine_and_apply_warp filter_and_project; do
    apptainer exec --writable-tmpfs --bind $SCRATCH:/scratch,$OAK:/oak \
        $CONTAINER bash -c "
            set -eo pipefail
            source /opt/module_shim.sh
            source /opt/iproc-venv/bin/activate
            cd ${IPROC_DIR}
            iproc -c ${CONFIG} -s ${stage} --bids ${BIDS} --executor local
        "
done
```

## How the Module Shim Works

The `module_shim.sh` defines a bash `module()` function that intercepts
`module load fsl/X.Y.Z-ncf` calls and swaps `FSLDIR` + `PATH` to point
at the correct `/opt/fsl-{version}` installation. No iProc source code
changes are needed.

The shim is loaded via:
- `BASH_ENV=/opt/module_shim.sh` for non-interactive shells (Python subprocess)
- `/etc/profile.d/module_shim.sh` for login shells
- `/bin/sh -> bash` so Python's `shell=True` uses bash

## Troubleshooting

### "module: command not found"
```bash
apptainer exec iproc.sif bash -c 'type module'
# Should output: module is a function
```

### FSL version not switching
```bash
apptainer exec iproc.sif bash -c '
    source /opt/module_shim.sh
    echo "Default: $FSLDIR"
    module load fsl/4.0.3-ncf
    echo "After 4.0.3: $FSLDIR"
    module load fsl/6.0.1-ncf
    echo "After 6.0.1: $FSLDIR"
'
```

### Old FSL binaries fail with glibc errors
If FSL 4.1.9 binaries crash on Ubuntu 22.04, change the base image in
`iproc.def` line 2 to `rockylinux:8` and swap `apt-get` for `dnf`.

### FreeSurfer license errors
The license is baked into the image. You can also override at runtime:
```bash
apptainer exec --bind /path/to/license.txt:/opt/freesurfer-6.0.0/license.txt ...
```
