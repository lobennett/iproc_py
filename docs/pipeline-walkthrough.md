# iProc pipeline: step-by-step walkthrough

This document walks the full iProc pipeline as it actually executes in this
package — every stage, the internal steps and tools each one runs, what flows
in and out, and the decision points (both the config-time choices that route
the pipeline and the manual QC gates between stages).

It is deliberately more detailed than the six-stage summary in
[`usage.md`](usage.md#the-six-stages); read that first for the big picture,
then come here to understand *what is happening inside each stage and why*.

Scientific behavior replicates upstream **harvard-nrg/iProc** (`v2.6.0-beta.4`).
The stage logic lives in `src/iproc/cli/iproc.py`; each numbered step below is a
`steps.<name>()` call that builds one or more jobs (a `JobSpec` DAG) which the
selected executor runs. The heavy lifting is in the bash/Python runscripts under
`src/iproc/runscript/`, which wrap FSL, FreeSurfer, AFNI, and ANTs.

---

## Mental model

iProc is an **individualized (deeply-sampled, single-subject)** pipeline: one
subject with many BOLD runs, often across many sessions, is registered into a
common per-subject space and projected to the cortical surface. Two ideas drive
the design:

1. **Compose transforms, interpolate once.** Motion correction, fieldmap
   unwarping, BOLD→T1 (BBR), and T1→MNI are each *computed* separately, then
   concatenated into a single warp that is applied in **one** resampling step.
   Repeated resampling blurs data; iProc avoids it (`combine_and_apply_warp`).

2. **Output in three spaces.** Every BOLD run ends up in native-T1 volume space,
   MNI volume space, and on the `fsaverage6` cortical surface (smoothed and
   unsmoothed).

The pipeline is **six sequential stages** with **manual QC gates between them**.
The gates are not automated — this matches upstream's workflow, and skipping them
is the most common cause of confusing downstream failures.

```
                 config-time routing decisions
   BIDS dataset ──► discover ──► manifest.yaml ──► generate ──► subject.cfg + scanlist.csv
        │                          (editable)                          │
        └──────────────────────────────────────────────────────────────┘
                                       │
   ┌───────────────────────────────────▼──────────────────────────────────┐
   │ 1 setup ─► 2 bet ─► 3 unwarp_motioncorrect_align ─► 4 T1_warp_and_mask │
   │ ─► 5 combine_and_apply_warp ─► 6 filter_and_project                    │
   └───────────────────────────────────────────────────────────────────────┘
     ▲QC       ▲QC        ▲QC (x2)              ▲QC             ▲QC        (terminal)
```

---

## Decision points set *before* the pipeline runs (config generation)

For a BIDS dataset the routing choices are made once, when you generate the
config, not during the run. `iproc-discover` inspects the dataset with pybids and
writes an **editable** `manifest.yaml`; `iproc-generate` turns that into the
per-subject `.cfg` + `scanlist.csv` the six stages consume. (See
[`usage.md`](usage.md#from-a-bids-dataset-discover--generate--run).) The choices
that matter most:

| Decision | How it is made | Where to override |
|---|---|---|
| **Fieldmap regime** | `fieldmap.detect_regime()` classifies each session as `fsl_prepare_fieldmap` (magnitude + phasediff, gradient-echo), `topup` (opposed-PE `epi`/pepolar), `direct` (a ready-made fieldmap), or `none`. It reports a **confidence** and **warnings**; low-confidence or mixed-regime datasets require `--force`. Metadata is read through **BIDS inheritance** (root-level `*_bold.json` / `phasediff.json`), so datasets without per-run sidecars (e.g. MSC) classify correctly. | `manifest.yaml` fieldmap fields; `PREPTOOL` in the `.cfg`. |
| **T1 selection** | The **latest session** that has a `T1w`, and within it the **latest run**, is chosen (rationale: earlier structurals are more likely to be low quality). Its session + series number become `T1_SESS` / `T1_SCAN_NO`. | `t1_selection` in `manifest.yaml` before `generate`; or `T1_SESS`/`T1_SCAN_NO` in the `.cfg` after the `setup` QC gate. |
| **Cross-session anat** | The selected T1's series number is **broadcast** to every session, so BOLD runs in sessions with no structural of their own still reference the chosen T1. | automatic. |
| **Midvol target** | The **first session, first BOLD run** provides the reference volume everything aligns to. | `MIDVOL_SESS` / `MIDVOL_BOLDNO` / `MIDVOL_VOLNO` in the `.cfg`. |
| **Single- vs multi-echo** | Per-task `NUMECHOS` (from the task CSV). Multi-echo changes ingestion (per-echo files), can insert `tedana`, and takes a reduced filtering path. | task CSV / `.cfg`. |
| **Output resolution** | `out_atlas.RESOLUTION` — `222` (2mm) or `111` (1mm) MNI grid. | `.cfg`. |

Global run-time flags (all stages): `--executor {local,slurm,pbsubmit}`,
`--bids <dir>` (only for `setup`), `--overwrite`, `--force`, `--skip-fail`.

---

## Stage 1 — `setup`

**Purpose:** get the raw data into iProc's working layout and reconstruct the
cortical surface from the T1.

`iproc -c <subject.cfg> -s setup --bids <bids_dir> --executor <...>`

Internal steps (`setup()` in `cli/iproc.py`):

1. **Ingest fieldmaps** — `steps.fmap_from_bids()` (or `xnat_to_nii_gz_fieldmap`
   for non-BIDS). Routed by regime:
   - *gradient-echo* (`fmap_from_bids.py` → `fmap_fsl_prepare_fieldmap_prep.sh`):
     brain-extract the magnitude, then build the radians/sec fieldmap. Siemens/
     Varian use upstream's exact `fsl_prepare_fieldmap SIEMENS <phase> <mag> <out>
     <ΔTE>` (byte-identical to upstream); GE/Philips take an added Hz→rad/s branch.
     MSC's ΔTE is 2.46 ms — the hardcoded Siemens value, so parity holds.
   - *topup* (`fmap_from_bids_topup.sh` / `fmap_topup_prep.sh`): estimate the
     off-resonance field from opposed phase-encode `epi` pairs.
   - Tolerant of a missing adjacent sidecar: a Siemens default is assumed when no
     `Manufacturer` is present (correct for MSC).
2. **Ingest anatomicals** — `steps.anat_from_bids()`: reorient the selected T1
   into working space.
3. **Ingest functionals** — `steps.func_from_bids()` → `func_from_bids.py` for
   each BOLD run: force to float (`fslmaths`), reorient to RADIOLOGICAL
   (`fslreorient2std`), drop dummy volumes (`fslroi`, `SKIP` frames), and write
   the per-run `echoTime`/`dwellTime` `.sec` files plus a preserved JSON. Echo /
   dwell / phase-encode metadata is resolved via **BIDS inheritance**
   (`commons.resolve_bids_metadata`), so runs without an adjacent sidecar still
   ingest.
4. **Fieldmap QC** — `QC_fmap()`: renders axial/sagittal QC PDFs pairing each
   fieldmap with a nearby BOLD.
5. **`recon-all`** — `steps.recon_all()` → `recon_all.sh`: full FreeSurfer
   surface reconstruction on the selected T1. **This is the multi-hour step.**

**Decision point / QC gate:** iProc prints `freeview` commands to (a) check the
fieldmap QC PDF and (b) inspect the pial/white surfaces against the T1 and the
spherical registration against `fsaverage`. **If multiple T1s were collected,
pick the best session now and set `T1_SESS` / `T1_SCAN_NO` in the `.cfg`.** Then
proceed to `bet`.

---

## Stage 2 — `bet`

**Purpose:** prepare the session-structural / brain-extraction inputs the warp
stages need.

Internal step (`check_bet()`):

1. **`steps.sesst_prep()`** → `sesst_prep.sh`: session-structural preparation and
   brain extraction feeding the later T1↔BOLD and T1→MNI registrations.

**Decision point / QC gate:** inspect the brain-extraction mask — too tight
cuts into cortex; too loose keeps skull/dura. Then proceed to
`unwarp_motioncorrect_align`.

---

## Stage 3 — `unwarp_motioncorrect_align`

**Purpose:** unwarp, motion-correct, and align every BOLD run to a common
per-subject midvolume template. This is where the BOLD time-series geometry is
fixed.

Internal steps (`unwarp_motioncorrect_align()`):

1. **`steps.fslroi_reorient_skip()`** — reorient + dummy-frame skip in working
   space (`fslroi_reorient_skip.sh`, or the `_ME` variant for multi-echo).
2. **`steps.fm_unwarp_midvol()`** — fieldmap-unwarp the midvol reference
   (`fm_unw.sh`).
3. **`steps.create_upsamped_midvol_target()`** — build the upsampled midvol
   target grid (`create_upsampled_midvol_target.sh`).
4. **`steps.fm_unwarp_and_mc_to_midvol()`** — for each run: motion-correct with
   `mcflirt`, apply fieldmap unwarp, and register to the midvol target, in one
   pass (`fm_unwarp_and_mc_to_midvol.sh`).
5. **`steps.fslmerge_meantime(...)`** → the mean of the per-run midvols
   (`midvols_mean`).
6. **`steps.align_to_midvol_mean()`** — align each run to that mean midvol
   (`align_to_midvol_mean.sh`).
7. **QC1 + QC2** — `QC_unwarp_motioncorrect_align()` renders PDFs of the mean
   midvol and the aligned output; a final `fslmerge` builds the `meanbold`
   template.

**Decision point / QC gate:** flip through the QC PDFs looking for major shifts
in the location of sulci/gyri, and review the **framewise-displacement / motion
parameters** to decide whether any high-motion run should be excluded before
continuing. Then proceed to `T1_warp_and_mask`.

---

## Stage 4 — `T1_warp_and_mask`

**Purpose:** register BOLD to the native T1, compute the T1→MNI warp, and build
the tissue masks used downstream.

Internal steps (`T1_warp_and_mask()`):

1. **`steps.bbreg()`** → `bbreg.sh`: FreeSurfer **`bbregister`** boundary-based
   registration of the mean BOLD to the native T1.
2. **compute T1→MNI warp** → `compute_T1_MNI_warp.sh`: FSL linear + nonlinear
   registration (FLIRT/FNIRT) of the T1 to the MNI template at the configured
   resolution.
3. **register tissue masks** → `reg_MNI_CSF_WM_to_T1.sh`: bring MNI CSF/WM masks
   into T1 space (used as nuisance regressors in stage 6).

**Decision point / QC gate:** iProc copies the recon-all brain mask into the
template folder and prints an `fslview`/`freeview` command. **A good brain mask
has minimal non-brain tissue and does not trim brain.** If it looks good,
proceed and *ignore* the manual steps. If not, iProc prints an **iterative
manual `bet` recipe** — run `bet`, read the centre-of-gravity, adjust `-f` and
the centre, re-check, and record your final command in
`<template>/logs/bet.txt`. Then proceed to `combine_and_apply_warp`.

---

## Stage 5 — `combine_and_apply_warp`

**Purpose:** concatenate every transform and apply it **once** per run, in both
native-T1 and MNI space (the single-interpolation principle).

Internal steps (`combine_and_apply_warp()`):

1. **`steps.size_brainmask()`** → `size_brainmask.sh`: dilate the brain mask to
   bound the output volume.
2. **project to T1 space** — `steps.combine_warps_parallel(anat_space='T1')`
   (`combine_warps_parallel.sbatch`, one job per run) then
   `steps.combine_warps_post()` (`combine_warps_post.sh`): combine motion +
   unwarp + BBR into one warp and resample each run into native T1 space.
3. **project to MNI space** — the same with `anat_space='MNI'`
   (`combine_warps_post_MNI.sh`): add the T1→MNI warp and resample into MNI.
4. **QC PDFs** — merge the projected runs and render QC.

**Decision point / QC gate:** check the single-interpolation QC PDFs, and
**verify the `fsaverage6` symlink exists** under the subject's recon-all output —
stage 6's surface projection requires it.

*Multi-echo note:* multi-echo datasets can insert an optional **`tedana`**
ICA-denoising pass here, between stages 5 and 6 (uses the `_ME` runscript
variants). See `bids_setup/README.md`.

---

## Stage 6 — `filter_and_project`

**Purpose:** denoise the time series and project to volume + surface. Terminal
stage.

Internal steps (`filter_and_project()`):

1. **`steps.calculate_nuisance_params()`** (`calculate_nuisance_params.py/.sh`):
   build nuisance regressors (motion, CSF/WM signals, etc.).
2. **MNI path** — `nuisance_regress` → `bandpass` → `wholebrain_only_regress`
   at `MNI{res}` (`nuisance_regress.sbatch`, `bandpass.sbatch`,
   `wholebrain_only_regress.sh`).
3. **Native-T1 path** — the same three at `NAT{res}`.
4. **`steps.fs6_project_to_surface()`** (`fs6_project_to_surf.sh`): project the
   cleaned volumes to the `fsaverage6` cortical surface (smoothed + unsmoothed).

*Multi-echo note:* the ME path runs only `calculate_nuisance` → `bandpass` →
project (no separate whole-brain-only regression), using the `_ME` runscripts.

**Outputs (per BOLD run):** `{BOLD}_anat.nii.gz` (native T1), `{BOLD}_mni.nii.gz`
(MNI), and `{lh,rh}.{BOLD}_fsaverage6[_sm{X}].nii.gz` (surface). **No further QC
gate** — this is the end of the pipeline.

---

## Worked example: how MSC (`ds000224`, sub-MSC01) exercises the decisions

The Midnight Scan Club dataset is the package's real-data validation target and
touches nearly every decision point above:

- **Fieldmap regime:** Siemens gradient-echo phasediff → `fsl_prepare_fieldmap`,
  ΔTE = 2.46 ms (matches upstream's hardcoded Siemens value → parity).
- **BIDS inheritance:** MSC has *no* per-run sidecars — all echo/dwell/manufacturer
  metadata lives in root-level `task-*_bold.json` / `phasediff.json`. Both fieldmap
  detection and func ingestion resolve it via inheritance.
- **Cross-session anat:** T1s live in `ses-struct01`/`ses-struct02`; BOLD/fmap live
  in `ses-func*`. Discovery picks the **latest** structural session, `struct02`,
  and its **latest** run (series `052`) as `T1_SESS`/`T1_SCAN_NO`, and broadcasts
  that series number so every func session references it. *(This is the "why are we
  using that structural image?" answer: latest-session, latest-run heuristic —
  editable in the manifest if a different T1 is preferred.)*
- **Many runs:** ~80 BOLD runs across sessions are ingested, unwarped, aligned,
  and projected — the deeply-sampled, single-subject case iProc is built for.

---

## Where the pieces live

| Layer | Location |
|---|---|
| Stage orchestration | `src/iproc/cli/iproc.py` (`setup`, `check_bet`, `unwarp_motioncorrect_align`, `T1_warp_and_mask`, `combine_and_apply_warp`, `filter_and_project`) |
| Per-step job construction | `src/iproc/steps.py` (`steps.<name>()`) |
| Runscripts (FSL/FS/AFNI/ANTs) | `src/iproc/runscript/*.{sh,sbatch,py}` |
| Config generation | `src/iproc/bids_app/discover.py`, `generate.py` |
| Fieldmap-regime detection | `src/iproc/fieldmap/__init__.py` (`detect_regime`) |
| BIDS ingestion matching / metadata | `src/iproc/bids/__init__.py`, `commons.resolve_bids_metadata` |
| Executors | `src/iproc/executors/` (`local`, `slurm`, `pbsubmit`) |

See also: [`usage.md`](usage.md) (install + commands),
[`generalization.md`](generalization.md) (how detection generalizes across
datasets), [`fork-audit.md`](fork-audit.md) (upstream-parity accounting), and
[`validation.md`](validation.md) (replication status).
