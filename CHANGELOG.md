# Changelog
## Unreleased
- Repackage upstream iProc v2.6.0-beta.4 as `iproc`; vendor scientific core verbatim.
- Add `iproc.fieldmap` regime detection (Siemens/Varian & unrecognized-manufacturer
  phasediff, GE/Philips phasediff flagged as new capability, pepolar/topup, direct,
  none), each with confidence + warnings.
- Add `iproc.orientation` registration policy, defaulting to upstream's
  `fslswapdim` + wide FLIRT search; the fork's already-RAS/no-swap assumption
  is opt-in only (`orientation_mode=fork_no_swap`).
- Generalize `bids_setup/bids_discover.py` and `bids_setup/bids_generate.py`:
  regime-aware, session-optional BIDS discovery (datasets without `ses-`
  directories supported), cross-session anatomical broadcast (a subject's
  chosen T1 is referenced by every session's BOLD rows), and two safety
  gates — low-confidence detection requires `--force`; BOLD runs with no
  usable fieldmap in their own session require `--allow-no-fieldmap`
  (evaluated per session, not subject-wide).
- Vendor and harden an Apptainer container (`container/`) with pinned
  dependency versions (FSL mapped 4.1.9/5.0.8/6.0.7+, FreeSurfer 6.0.0,
  ANTs 2.4.4, dcm2niix v1.0.20230411, AFNI latest-stable with build-time
  provenance capture) and an FSL `module_shim.sh` for runtime version
  switching.
- Add a site-profile system (`src/iproc/data/site_profiles/`,
  `generic-slurm.yaml` + `sherlock.yaml`) and a profile-driven launcher
  (`launch/iproc-run`) that submits one `sbatch`/`apptainer` job per subject
  with container path, binds, storage roots, partitions, and per-stage
  resources all coming from the profile.
- Add `launch/iproc-init`, an interactive/non-interactive wizard for
  generating a new site profile without hand-writing YAML.
- Add a Phase-B validation harness (`scripts/validate_against_baseline.sh`,
  `scripts/diff_tools/`, `docs/validation.md`) for diffing this package's
  output against a hand-constructed upstream-behavior baseline
  (`niftidiff` if available, else a new nibabel-based `diff-nifti.py`
  fallback), plus `scripts/fork_divergence_report.sh` as a diagnostic-only
  comparison of this package's dry-run command set against the fork's.
- Add `docs/dependencies.md` (upstream deps + container/Sherlock mapping),
  `docs/usage.md` (stages, QC checkpoints, local/container/cluster
  execution, BIDS discover→generate→run flow), and `docs/generalization.md`
  (the detect-and-preserve model and its limitations, including the
  single subject-wide `.cfg` `PREPTOOL` limitation for mixed-regime,
  multi-session subjects).
- Validation status: **Phase A done** (`tests/test_golden_commands.py` +
  `docs/fork-audit.md` classification); **Phase B pending** (bit-identical
  numeric validation + MSC methodological check, requires an interactive
  Sherlock session — not yet run).
