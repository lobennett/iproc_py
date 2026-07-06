# Usage

End-to-end guide to running `iproc`: installing it, understanding the six
processing stages and their manual QC checkpoints, choosing between local /
container / cluster execution, and driving the whole thing from a BIDS
dataset.

## Install

For local development and running the test suite:

```bash
uv venv --seed --python 3.11 .venv
source .venv/bin/activate
pip install -e '.[test]'
iproc --help
```

(`--seed` makes `uv venv` install `pip` into the venv — plain `uv venv`
leaves the venv without one.)

For real processing runs, you do **not** install iProc's scientific
dependencies (FSL, FreeSurfer, AFNI, ANTs, dcm2niix — see
`docs/dependencies.md`) yourself. Those live in the Apptainer container
(`container/iproc.def`); see "Running via the container" below and
`container/README.md` for building it.

## The six stages

`iproc` processes a subject through six sequential stages, each invoked as
`iproc -c <subject.cfg> -s <stage> [--bids <bids_dir>] --executor local`
(`--bids` is only needed for `setup`). Each stage is a SLURM job (or a local
run) per subject; wait for a stage to finish and do its QC checkpoint before
starting the next — later stages consume outputs from earlier ones and
non-deterministic-looking failures are almost always a skipped QC step
upstream.

1. **`setup`** — Ingests BIDS data (fieldmaps, anatomicals, functionals)
   into iProc's working layout and runs FreeSurfer `recon-all` on the
   selected T1.
   **QC checkpoint:** check the `fmap_qc` PDF for fieldmap quality; check
   `recon-all`'s pial/white-matter surface boundaries on the T1; if multiple
   T1s were collected, pick the best one and update `T1_SESS`/`T1_SCAN_NO`
   in the subject's `.cfg`.

2. **`bet`** — Brain extraction on the MNI-warped T1.
   **QC checkpoint:** check the brain-extraction mask — too tight (cutting
   into cortex) or too loose (including skull/dura)?

3. **`unwarp_motioncorrect_align`** — Fieldmap-based unwarping, motion
   correction, and alignment of every BOLD run to a midvolume template.
   **QC checkpoint:** check each run's alignment to the midvol and mean-BOLD
   templates; review motion parameters (framewise-displacement plots) for
   runs that may need to be excluded.

4. **`T1_warp_and_mask`** — Boundary-based registration (BOLD-to-T1),
   T1-to-MNI warp computation, and mask generation.
   **QC checkpoint:** check `bbregister` output (BOLD-to-T1 alignment) and
   the brain extraction of the T1 in MNI space.

5. **`combine_and_apply_warp`** — Combines all transforms (motion, unwarp,
   BBR, T1-to-MNI) into a single interpolation applied once, in both native
   and MNI space (avoids repeated resampling blur).
   **QC checkpoint:** check the single-interpolation QC PDFs; verify the
   `fsaverage6` symlink exists under the subject's `recon_all` output before
   proceeding — `filter_and_project`'s surface step needs it.

   *(Multi-echo datasets insert an optional `tedana` ICA-denoising pass here,
   between `combine_and_apply_warp` and `filter_and_project` — see
   `bids_setup/README.md` Stage 6.)*

6. **`filter_and_project`** — Nuisance regression, bandpass filtering, and
   surface projection to `fsaverage6` (both unsmoothed and smoothed
   outputs).
   **No further QC checkpoint** — this is the terminal stage; outputs are
   `{BOLD}_anat.nii.gz`, `{BOLD}_mni.nii.gz`, and
   `{lh,rh}.{BOLD}_fsaverage6[_sm{X}].nii.gz` per BOLD run.

None of these QC checkpoints are automated by `iproc` itself — they are
manual review steps between stages, matching upstream's own workflow. Do not
chain all six stages unattended for a first run on new data; the fieldmap
and alignment checkpoints (stages 1, 3, 4) are where scanner- or
regime-specific problems surface.

## Running: local vs. container vs. cluster

**Local / bare-metal** (dev, or a host that already has FSL/FreeSurfer/AFNI/
ANTs/dcm2niix on `PATH`):

```bash
iproc -c mri_data/s03/subject_lists/s03.cfg -s setup --bids /path/to/bids/sub-s03 --executor local
```

**Inside the container**, on any Apptainer host (see `container/README.md`
to build `iproc.sif`):

```bash
# --writable-tmpfs: ephemeral overlay so `pip install -e .` can write into the
# read-only in-image /opt/iproc-venv. set -eo pipefail surfaces install/run
# failures instead of masking them.
apptainer exec --writable-tmpfs --bind $OAK:/oak,$SCRATCH:/scratch $CONTAINER bash -c "
    set -eo pipefail
    source /opt/module_shim.sh
    source /opt/iproc-venv/bin/activate
    cd $IPROC_CODE && pip install -e .
    iproc -c \$CONFIG -s setup --bids \$BIDS --executor local
"
```

**Via `launch/iproc-run`** (the recommended path for real HPC runs) — a
site-profile-driven wrapper that submits one `sbatch` job per subject,
wrapping the same `apptainer exec ... iproc ...` invocation above, with the
container path, bind mounts, storage roots, partitions, and per-stage
resources all coming from a YAML site profile instead of being hardcoded:

```bash
launch/iproc-run <profile.yaml> <subjects.txt> <stage> [--bids-root PATH] [--dry-run]

# e.g., on Sherlock:
launch/iproc-run src/iproc/data/site_profiles/sherlock.yaml subjects.txt setup \
    --bids-root $OAK/data/my_bids_dataset
launch/iproc-run src/iproc/data/site_profiles/sherlock.yaml subjects.txt bet
```

`subjects.txt` is one subject label per line (`#`-prefixed and blank lines
ignored). `--bids-root` is required only for the `setup` stage. Two profiles
ship out of the box — `generic-slurm.yaml` (portable default for any vanilla
SLURM cluster) and `sherlock.yaml` (real Stanford Sherlock paths/partitions)
— and `launch/iproc-init` is an interactive wizard for generating a new
profile for a different site without hand-writing YAML:

```bash
launch/iproc-init --out my-site.yaml   # interactive prompts
launch/iproc-init --out my-site.yaml --non-interactive --name my-cluster \
    --container /path/to/iproc.sif --output-root /data/iproc_out --partition batch
```

See `launch/README.md` for the full site-profile schema, resource/partition
resolution rules, and known limitations (e.g. `fsl.mode`/`modules` are
parsed but not yet acted on).

## From a BIDS dataset: discover → generate → run

`iproc` itself consumes a per-subject `.cfg` + `scanlist_<sub>.csv`, not a
BIDS dataset directly. `bids_setup/` bridges the two in two steps, meant to
be run in order with a manual review in between:

1. **`bids_setup/bids_discover.py <bids_root> --output manifest.yaml [...]`**
   — scans the BIDS tree and writes an editable YAML manifest: per-subject
   T1 selection, midvolume target, per-task TR/volume counts, and a
   per-session fieldmap regime detection (`fsl_prepare_fieldmap` /
   `topup` / `direct` / `none`) with a confidence level, rationale, and any
   warnings. Handles both `ses-`-organized and session-less BIDS layouts.

2. **Review the manifest** (`manifest.yaml`) before proceeding — this is
   not optional. Check `t1_selection`, `midvol`, per-task `TR`/`num_volumes`,
   and especially `detections`/`fieldmap_confidence`: a `low`-confidence
   detection means the tool is guessing (e.g. a missing `Manufacturer` or
   `EchoTimeDifference`, ambiguous phase-encoding directions, or an
   unrecognized regime), and every warning is worth reading before you
   generate configs from it.

3. **`bids_setup/bids_generate.py manifest.yaml --iproc-dir <dir> --codedir <dir> [...]`**
   — reads the (reviewed) manifest and writes the actual `.cfg` and
   `scanlist_<sub>.csv` files per subject, plus
   `configs/tasktype_consolidated.csv`. Refuses to run (nonzero exit) if any
   subject is low-confidence unless `--force`, and refuses if any subject
   has BOLD runs with no usable fieldmap unless `--allow-no-fieldmap` — see
   `docs/generalization.md` for exactly what these gates do and do not mean.

4. **Run the stages** (above), either directly, via `bids_setup/run_subjects.sh`
   (Sherlock-specific, hardcoded paths — see `bids_setup/README.md`), or via
   the portable `launch/iproc-run`.

See `bids_setup/README.md` for the full flag reference (`--skip`,
`--smoothing`, `--resolution`, `--echo-time-diff`, `--manufacturer`,
`--force`, `--allow-no-fieldmap`), example manifest/cfg output, and the
design-decision table (T1 selection, MIDVOL target, SeriesNumber synthesis,
etc.).

## BIDS-App interface (`iproc-app`)

For a standard, nipreps-style entry point there is an additive console command
(the config-based `iproc -c <cfg> -s <stage>` engine is unchanged and remains
the thing that actually runs a stage):

```bash
iproc-app <bids_dir> <output_dir> participant [--participant-label LBL ...] \
    [-w WORKDIR] [--stage STAGE] [--dry-run]
```

It resolves participants from the BIDS tree (pybids), runs discover → generate
to produce each subject's iProc `.cfg`/scanlist under `output_dir`, and — because
iProc requires **manual QC between stages** — does *not* blindly run all six
stages: pass `--stage <name>` to run exactly one stage (handed to the `iproc`
engine), or omit it to just prepare configs and print ordered next-step guidance.
Only `participant` level is supported (iProc is single-subject); `group` is
rejected. `--dry-run` prints the plan and writes nothing.

**Outputs.** `iproc-app` writes a BIDS-Derivatives `dataset_description.json` at
the `output_dir` root (`DatasetType: derivative`, `GeneratedBy: iproc`, with an
acknowledgement pointing back to upstream harvard-nrg/iProc). Individual iProc
result files currently keep their iProc-native names under
`output_dir/mri_data/<sub>/...`; full per-file BIDS-Derivatives naming
(`space-*`, `desc-*`) is future work.

## Examples

- `bids_setup/README.md` — a worked example end to end (discover → review →
  generate → run all six stages), using a GE CNI-style dataset.
- `container/README.md` — SLURM batch-job examples for each stage, and the
  "all stages in sequence" loop.
- `docs/validation.md` — how a reference subject (MSC, Siemens
  phasediff) is intended to be run through this same discover→generate→run
  flow for the Phase B methodological check.
