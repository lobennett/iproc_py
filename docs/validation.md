# Validation

`iproc` repackages **upstream** [harvard-nrg/iProc](https://github.com/harvard-nrg/iProc)
`v2.6.0-beta.4`. Upstream is the scientific reference — not
`lobennett/iProc@container-and-bids-tooling` (the "fork"), and not this
package's own prior output. This document defines what "validated" means
here, how to run the check, and what the current validation status is.

## The upstream-behavior baseline

We do not compare against upstream's own repository checkout directly,
because upstream's runscripts assume an environment (module system, `rsync`,
GNU `parallel`, a fixed-length-run assumption in a couple of places) that
doesn't exist inside the Apptainer container this package runs in. Instead
we define an **upstream-behavior baseline**:

> upstream's scientific core, unmodified, plus only the numerics-neutral
> environment/portability fixes classified in `docs/fork-audit.md` §A
> (e.g. `rsync --remove-source-files` → `mv`, `parallel` → serial fallback),
> with every one of this package's BIDS/fieldmap-regime **generalizations
> pinned back to upstream's original defaults** (Siemens/Varian phasediff
> fieldmaps via `fsl_prepare_fieldmap`, fixed-length-run NUMVOL from config,
> upstream's exact-path glob behavior, upstream's `_wbonly` output naming —
> see `docs/fork-audit.md` §B for the full list of things we deliberately
> did *not* adopt from the fork).

In other words: the baseline is "this package with every behavior-changing
knob turned to the upstream setting." Concretely, `tests/test_golden_commands.py`
locks down the dry-run command set this package emits for a config that only
exercises upstream-default codepaths (Siemens phasediff, fixed-length runs,
standard BIDS layout) — that golden output **is** the upstream-behavior
baseline's command sequence (Phase A, done today; see below). What Phase B
adds is running that command sequence for real, on real data, and diffing
actual output files bit-for-bit against upstream's own executed output on
the same input.

### Constructing the baseline on Sherlock

The baseline is not something we ship a container for; it's constructed by
hand, once, on Sherlock, alongside this package:

1. Check out upstream `v2.6.0-beta.4` (`third_party/iProc-upstream` is
   already a vendored, read-only copy of this tag — see `NOTICE.md`).
2. Apply *only* the numerics-neutral env fixes in `docs/fork-audit.md` §A
   directly on top of that checkout (not the fork's other changes). These
   are infrastructure-only: they change how a command is invoked (`mv`
   instead of `rsync`, a loop instead of `parallel`), never what is computed.
3. Run that baseline checkout against a reference subject's BIDS data and
   config on Sherlock, using upstream's own environment (modules, not the
   container) so there is no ambiguity about whether the container itself
   introduced a difference.
4. Keep the baseline's output tree (`$IPROC_BASE_OUT`) around for the diff
   in the next section.

This is a manual, interactive Sherlock activity (with Logan), not something
this task's scripts automate — see `docs/superpowers/plans/2026-07-04-iproc-python-package.md`
("Post-plan: interactive Sherlock validation").

## Running Phase B

Two separate comparisons, with different purposes:

### 1. Baseline vs. ours — pass/fail

This is the actual validation gate: does this package reproduce the
upstream-behavior baseline bit-for-bit on the same inputs?

```bash
export IPROC_NEW_OUT=/path/to/our/output
export IPROC_BASE_OUT=/path/to/baseline/output
scripts/validate_against_baseline.sh <cfg> <bids> <stage>
```

The script runs our package into `$IPROC_NEW_OUT`, then diffs every
`*.nii.gz` it produced against the matching path under `$IPROC_BASE_OUT`:

- If `niftidiff` (a Sherlock/FreeSurfer tool) is on `PATH`, it invokes
  `iproc ... --dry-run --autodiff "$IPROC_NEW_OUT" "$IPROC_BASE_OUT"`, which
  uses this package's own `--autodiff` machinery (`src/iproc/cli/iproc.py`,
  `autodiff()`/`nifti_diff()`) to compare each job's output files under the
  two directories via `niftidiff`, without re-running anything (`--dry-run`
  still walks the job graph and computes each job's expected output paths).
- Otherwise it falls back to `scripts/diff_tools/diff-nifti.py` (this
  package's own nibabel-based tool — see below), run pairwise over every
  `.nii.gz` under `$IPROC_NEW_OUT` against its counterpart in `$IPROC_BASE_OUT`.

Expected result for a passing validation: no diffs reported (or only the
informational header diffs described below).

### 2. Fork vs. baseline — diagnostic only

This does **not** gate anything. It measures how far the fork's own
scientific/behavioral choices (bucket B/D in `docs/fork-audit.md`) drift
from the upstream-behavior baseline, purely so those choices can be reviewed
— it is not evidence that this package is correct or incorrect.

```bash
scripts/fork_divergence_report.sh <cfg> <bids> <stage>
```

This diffs the *dry-run command sets* (not executed output) of our package
vs. the fork, since our core's dry-run output already **is** the baseline's
command sequence (see the script's header comment and `test_golden_commands.py`).
Any line only in the fork's output is a fork deviation to review, not a
failure of this package.

## Reading `niftidiff` / `diff-nifti.py` output

- **`niftidiff`** (external, Sherlock-provided): reports differences
  between two NIfTI volumes; a clean run prints nothing and exits 0. Any
  output (voxel-value or header differences) or nonzero exit means the
  files differ — treat every such line as a real discrepancy to chase down,
  since Phase B's whole point is a bit-identical match.
- **`scripts/diff_tools/diff-nifti.py`** (this package's fallback, no FSL
  dependency): prints `File 1` / `File 2`, then either `IDENTICAL (within
  tolerance).` with exit 0, or an `Informational header differences (not
  fatal):` block (see below) followed by a `DIFFERENT:` block with exit 1
  listing exactly which of shape / affine / header field / voxel data
  differed, including the count of differing voxels and the max absolute
  difference for data mismatches.
- **`scripts/diff_tools/diff-nifti-fsl.py`** (vendored upstream original,
  requires FSL's `fslmaths`/`fslstats` on `PATH`): subtracts two volumes and
  reports the mean/min/max of the difference image. Useful for manual
  investigation on Sherlock (where FSL is already a hard dependency of the
  pipeline itself) but not what the harness calls automatically, because its
  argument shape is `(file, containing-directory)` rather than two file
  paths. `scripts/diff_tools/diff-dat.py` (nuisance `.dat` matrices,
  `np.allclose`-based) and `diff-pdf.py` / `summary_compare.py` (QC PDFs /
  directory-wide YAML summaries) are also vendored verbatim from upstream
  for manual use during Phase B triage; none of them are invoked by
  `validate_against_baseline.sh`.

## Acceptable header nondeterminism

A bit-identical *data* match is the bar. A small set of NIfTI header fields
are allowed to differ without failing validation, because they carry
free-text or provenance metadata rather than anything that affects
downstream analysis:

- `descrip`, `aux_file` — free-text fields some tools stamp with a
  version string or timestamp.
- NIfTI header extensions carrying tool-invocation/timestamp provenance
  (e.g. some FSL tools embed a command-line or run date in an extension).

`scripts/diff_tools/diff-nifti.py` encodes exactly this: it reports
`descrip`/`aux_file` differences under "Informational header differences"
and does not fail the run for them, but it does fail on any difference in
shape, affine, any other header field, or voxel data. Everything else in
the header — `pixdim`, `qform`/`sform`, `datatype`, `cal_min`/`cal_max`,
`scl_slope`/`scl_inter`, etc. — is expected to match exactly; a difference
there is a real discrepancy, not tolerable nondeterminism, and should be
investigated rather than waved through.

## Methodological check: MSC (Siemens)

Beyond the bit-identical baseline comparison, Phase B includes one
methodological sanity check unrelated to numeric equality: an end-to-end
run on a real Siemens gradient-echo phasediff dataset —
[MSC (Midnight Scan Club), `ds000224`](https://openneuro.org/datasets/ds000224)
— to confirm the Siemens/phasediff fieldmap regime (this package's default,
matching upstream) works correctly on real multi-session BIDS data, not
just the synthetic fixtures used in unit tests. This is the "real second
regime" check referenced in
`docs/superpowers/specs/2026-07-04-iproc-python-package-design.md`. GE
(Logan's own data) is a *new* capability relative to upstream — which only
ever saw Siemens/Varian in practice — and is **itself not yet validated**:
its own end-to-end check on real data is also pending Phase B, not something
already exercised. MSC's role is narrower: it confirms the *upstream-default*
Siemens/phasediff path still works end-to-end once wired through this
package's generalized BIDS layer, not only through hand-built config
fixtures. Validating the GE path is a separate Phase-B item (see
`docs/generalization.md` on GE being flagged new-capability, VERIFY-only).

## Where results are recorded

Phase B is run once per validated baseline construction and its result
(pass/fail, dataset/subject used, any header-only diffs observed, MSC
methodological check outcome) is recorded in `CHANGELOG.md` under
`## Unreleased` (or a dated release section once cut), and the
validation-status line in `README.md` is updated from "Phase B pending" to
"output-verified vs upstream" once a passing run is on record.

## Current validation status

- **Phase A — done.** Command-level verification: `tests/test_golden_commands.py`
  locks the dry-run command sequence this package emits for an
  upstream-default config, and `docs/fork-audit.md` classifies every change
  relative to upstream so only numerics-neutral infrastructure fixes are
  applied by default (see NOTICE.md).
- **Phase B — pending.** Bit-identical numeric validation against an
  executed upstream-behavior baseline, plus the MSC methodological check,
  requires Sherlock (container build, real BIDS data, upstream's module
  environment for constructing the baseline) and has not yet been run. This
  task (`scripts/validate_against_baseline.sh`, `scripts/diff_tools/`, this
  document) provides the harness; running it is a separate, later,
  interactive Sherlock activity.

Until Phase B is recorded as passing in `CHANGELOG.md`, treat this
package's scientific output as **unverified against executed upstream
output** — the code paths are audited and command-verified (Phase A), but
not yet numerically confirmed bit-identical.
