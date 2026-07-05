# External Dependencies

These are the software packages iProc was developed with and validated 
against.

!!! question "Can I upgrade these dependencies?"

    iProc may run perfectly fine with newer versions of the dependencies 
    shown below, but the results have never been validated.

Software          | Versions                            | Download
------------------|-------------------------------------|------------------------
[Python][]        | `3.11`                              | [:material-download:][Python DL]
[GNU Parallel][]  | `20180522`                          | [:material-download:][GNU Parallel DL]
[AFNI][]          | `16.3.13`                           | [:material-download:][AFNI DL]
[FSL][]           | `4.0.3`, `5.0.4`, `5.0.10`, `6.0.1` | [:material-download:][FSL DL]
[MRIcron][]       | `2012_12_12`                        | [:material-download:][MRIcron DL]
[MRIcroGL][]      | `2019_09_04`                        | [:material-download:][MRIcroGL DL]
[FreeSurfer][]    | `6.0.0`                             | [:material-download:][FreeSurfer DL]
[ImageMagick][]   | `6.7.8-10`                          | [:material-download:][ImageMagick DL]
[ANTs][]          | `2.4.4`                             | [:material-download:][ANTs DL]
[dcm2niix][]      | `1.0.20230411`                      | [:material-download:][dcm2niix DL]

[Python]: https://www.python.org/
[Python DL]: https://docs.astral.sh/uv/guides/install-python/
[GNU Parallel]: https://www.gnu.org/software/parallel/
[GNU Parallel DL]: https://ftp.gnu.org/gnu/parallel/parallel-20180522.tar.bz2
[MRIcron]: https://github.com/neurolabusc/MRIcron
[MRIcron DL]: https://www.nitrc.org/frs/download.php/5153/lx64.zip
[AFNI]: https://afni.nimh.nih.gov/
[AFNI DL]: https://afni.nimh.nih.gov/pub/dist/tgz/AFNI_ARCHIVE/AFNI_16.3.13.tgz
[FSL]: https://fsl.fmrib.ox.ac.uk/fsl/docs/
[FSL DL]: https://fsl.fmrib.ox.ac.uk/fsl/docs/install/index.html#installing-older-versions-of-fsl
[MRIcroGL]: https://github.com/rordenlab/MRIcroGL
[MRIcroGL DL]: https://github.com/rordenlab/MRIcroGL/releases/tag/v1.2.20190902
[FreeSurfer]: https://surfer.nmr.mgh.harvard.edu/
[FreeSurfer DL]: https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/6.0.0/freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.0.tar.gz
[ImageMagick]: https://imagemagick.org/
[ImageMagick DL]: https://imagemagick.org/archive/releases/ImageMagick-6.7.8-10.tar.xz
[ANTs]: https://github.com/ANTsX/ANTs
[ANTs DL]: https://github.com/ANTsX/ANTs/releases/tag/v2.4.4
[dcm2niix]: https://github.com/rordenlab/dcm2niix
[dcm2niix DL]: https://github.com/rordenlab/dcm2niix/releases/tag/v1.0.20230411

---

## Container / Sherlock

The table above lists what **upstream** iProc was developed and validated
against. This package (`iproc`) does not require you to install any of that
by hand — it ships an Apptainer (Singularity) container, built from
`container/iproc.def`, that provides the closest available versions of every
dependency, pinned and documented in `container/README.md`. On Sherlock (or
any Apptainer-capable HPC), you always run `iproc` **inside this container**,
not against a bare-metal install.

What the container provides, and how it maps onto the table above:

| Software | Container version | How it's exposed |
|---|---|---|
| FSL | `4.1.9` / `5.0.8` / `6.0.7+` (mapped to iProc's `4.0.3` / `5.0.4`, `5.0.10` / `6.0.1` requests) | Runtime-switched via a `module_shim.sh` — a bash `module()` function that intercepts `module load fsl/X.Y.Z-ncf` and repoints `FSLDIR`/`PATH` at `/opt/fsl-{version}`. No iProc source changes needed; see "FSL Version Mapping" in `container/README.md`. |
| FreeSurfer | `6.0.0` | Installed at `/opt/freesurfer-6.0.0`; requires a user-supplied license staged at `container/downloads/license.txt` before building the image (not vendored — see `container/README.md`). |
| AFNI | "latest-stable" (intentionally unpinned — upstream publishes no dated Linux tarball) | Only `3dTproject`/`3dAFNItoNIFTI` are used by iProc; build-time provenance (`Last-Modified` header, `afni -version`) is captured to `/opt/afni/INSTALLED_VERSION.txt` inside the image so any built `.sif` is auditable. |
| ANTs | `2.4.4` (pinned) | Installed from the versioned GitHub release. |
| dcm2niix | `v1.0.20230411` (pinned) | Installed from the versioned GitHub release. |
| Python | `3.11` (deadsnakes PPA) | `iproc` itself, plus `tedana`, run from `/opt/iproc-venv` inside the container. |

Not required to match the upstream table exactly, but also bundled: GNU
Parallel (serial fallback used where the container lacks it — see
`docs/fork-audit.md` §A), ImageMagick (QC images), Connectome Workbench and
MRIcroGL (included for completeness, not on iProc's own critical path).
**MATLAB is not required** — fully replaced by Python in this codebase.

### Running on Sherlock

You do not `apptainer shell`/`exec` by hand for routine runs — use
`launch/iproc-run` (see `docs/usage.md`), which builds the
`apptainer exec ... iproc -c <cfg> -s <stage> ...` invocation for you from a
site profile (`src/iproc/data/site_profiles/sherlock.yaml`), handling bind
mounts (`/oak`, `/scratch`), partitions, and per-stage SLURM resources. See
`container/README.md` for building the image (`container/build.sh` or
`container/build_sherlock.sh`) and staging the FreeSurfer license, and
`docs/validation.md` for how the container's dependency choices (e.g. the
FSL version mapping) factor into Phase B numeric validation against
upstream's own environment.
