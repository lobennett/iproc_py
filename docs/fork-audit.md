# Fork Audit — classification of `lobennett/iProc@container-and-bids-tooling` vs upstream `v2.6.0-beta.4`

Every change is classified so the package can default to **upstream** science and apply
only numerics-neutral infrastructure fixes. "Decision" is what this package does.

## A. Numerics-neutral (env/portability) — APPLIED (Task 3)

| File | Change | Why neutral | Decision |
|------|--------|-------------|----------|
| runscript/recon_all.sh | `rsync --remove-source-files` → `mv` | file move, not computation; rsync absent in container | apply (copy fork file) |
| runscript/combine_warps_parallel.sbatch | rsync → mv | same | apply |
| runscript/combine_warps_parallel_ME.sbatch | rsync → mv | same | apply |
| runscript/fs6_project_to_surf.sh | collapse per-BOLD `parallel` heredocs to loop + serial fallback | same commands, `projfrac 0.5`/fsaverage6/trilinear unchanged; `parallel` absent in container | apply |
| runscript/calculate_nuisance_params.sh | srun/parallel → parallel-or-serial fallback | same `fslmeants` invocations | apply |
| iproc/steps.py (glob/acq- hunks) | exact-path → glob for anat/func to tolerate `acq-` | same target files resolved | apply (named hunks only) |
| iproc/steps.py (fmap list-coercion) | wrap fmap inputs in list; append→extend | passes same files | apply (named hunk) |
| iproc/steps.py (ME CODEDIR arg) | pass CODEDIR to ME nuisance calc | pairs with runscript; path only | apply (named hunk) |
| iproc/steps.py (`_resolve_unique_bids_file`) | **APPLIED (fix-wave):** replaced ad hoc `glob.glob(...)[0]` selection (arbitrary-order pick when multiple files match, no signal if zero match) with a helper that unions all candidate glob patterns, sorts them, and raises a clear `IOError` naming every candidate when the match count isn't exactly one. Used for T1w (anat) and functional BIDS-file resolution, including a plain canonical-name pattern (no interposed BIDS entity, e.g. no `acq-`) unioned with the with-entity pattern so a subject with a bare `..._T1w.nii.gz` still resolves. | same target file is always the one selected on an unambiguous dataset; the only behavior change is failing loudly (instead of silently picking an arbitrary file) when a dataset is genuinely ambiguous, and succeeding (instead of failing) on the previously-unmatched no-entity T1w case | apply |

## A2. Deliberate correctness deviation (DEFAULT-ON) — NOT numerics-neutral

These three files were originally logged in bucket A as "numerics-neutral" because they
are a no-op on fixed-length runs. That framing undersold what the change actually does:
on **variable-length runs** it changes the number of volumes iProc operates over, which
is a real, intentional divergence from upstream — not a neutral env/portability fix.
It is kept, **enabled by default**, because upstream's fixed `NUMVOL`/MAT-count assumption
mis-indexes (or crashes on) runs whose volume count isn't the config-declared length.

| File | Change | Behavior on fixed-length runs | Behavior on variable-length runs | Decision |
|------|--------|-------------------------------|-----------------------------------|----------|
| runscript/fm_unwarp_and_mc_to_midvol.sh | add `NUMVOL=$(fslnvols …)`, replacing the cfg-declared `NUMVOL` | no-op — `fslnvols` reports the same count already in the cfg | **diverges from upstream**: uses the BOLD file's actual volume count instead of the possibly-stale cfg value | apply, default-on (intentional deviation, kept) |
| iProc_p4_sbatch_combined.py | `volnums` derived from a count of `MAT_####` files instead of the cfg `NUMVOL` | no-op — MAT-file count equals cfg `NUMVOL` | **diverges from upstream**: `volnums` tracks the run's real MAT-file count, so upstream's fixed-`NUMVOL` loop (which would mis-index past the end of a shorter run or silently drop trailing volumes of a longer one) is avoided | apply, default-on (intentional deviation, kept) |
| iProc_p4_sbatch_combined_ME.py | same as above | same | same | apply, default-on (intentional deviation, kept) |

This is not a candidate for an opt-in/opt-out toggle: upstream's behavior on
variable-length runs is a correctness bug (index mismatch / crash), so there is no
"safe" upstream default to fall back to for that case. The fixed-length case is
provably identical either way, so there is no science cost to always applying it.

## B. Scientific / behavior-changing — DEFAULT TO UPSTREAM

| File | Change | Decision | Where handled |
|------|--------|----------|---------------|
| iproc/steps.py | output rename `_wbonly`→`_wb_resid` (L1772/1780/1959 upstream) | keep upstream name `_wbonly` | Task 3 (do NOT port) |
| runscript/compute_T1_MNI_warp.sh | drop `fslswapdim`, FLIRT ±30, inline hex-fix | keep upstream verbatim; hex-float handled by container flirt wrapper | Task 6 (orientation, opt-in) |
| runscript/fm_unw.sh | dim-check hard-fail → warn | keep upstream hard check; expose warn as opt-in | Task 7 |
| runscript/fmap_from_bids.py | GE `×2π` branch, JSON delta_te/manufacturer | **APPLIED (T2):** added GE/Philips Hz→rad/s branch (`fslmaths <phase> -mul 2π -mas <eroded_mag> <out>`) — a capability upstream lacks; reads only `Manufacturer` from the phase JSON sidecar. Siemens/Varian (and unknown/absent manufacturer) path is **byte-behavior-identical to upstream** (`fsl_prepare_fieldmap SIEMENS … 2.46`). ΔTE is **NOT** read from JSON — kept hardcoded 2.46 ms for parity (the fork's JSON-ΔTE change is deliberately **not** ported). Decision routed through the pure, FSL-free helper `choose_fieldmap_cmd()`. File is on the source-identity test's `OURS` allowlist. | T2 (done) |
| iproc/bids/__init__.py | anat regex loosening, conditional anat-JSON | generalization (session/entity) | Task 7 |
| iproc/qc/__init__.py | treat convert OK if PDF exists | infra, verify neutrality | Task 3 (verify) or Task 9 |

## C. Infrastructure (adopted wholesale, ours to harden)

container/*, bids_setup/*, docs/* — adopted in Tasks 5–11.

## D. Uncertain — flag for Phase-B numeric comparison

The diffstat (`git -C third_party/iProc-fork diff --stat v2.6.0-beta.4..HEAD`) shows 48
changed files. The files below are the ones not already covered by buckets A/B/C above
(container/*, bids_setup/*, and docs/* files from the diffstat are covered by bucket C).
None of these were part of the original analysis, so none are pre-approved as neutral —
each needs a Phase-B numeric-comparison pass (or explicit sign-off) before Task 3 vendors
anything from it.

| File | Change | Note |
|------|--------|------|
| .gitignore | add ignore patterns for container build artifacts (`license.txt`, `manifest*.yaml`, `iproc.sif`, `flirt.real`, `convert_xfm.real`) | no code path touched, but not pre-classified — confirm no tracked artifact is being silently excluded |
| mkdocs.yml | drop `def_list`/`pymdownx.tasklist` markdown extensions; drop "Full Tutorial" and "Big List" nav entries | docs-site config only; matches the doc files removed under bucket C, but keep as D since the mapping wasn't pre-verified |
| modules_rocky8.sh | drop `miniconda3` module load; drop `_IPROC_CODEDIR`/`PYTHONPATH` exports | changes the module/env-loading path used outside the Python package; could affect which Python/tooling is on `PATH` at runtime — needs verification, not assumed neutral |
| modwrap.sh | `$prepcmd` / `$postcmd` now run as `$prepcmd \|\| true` / `$postcmd \|\| true` | changes error-handling semantics: a failing pre/post command no longer aborts the wrapped step — could mask real failures; needs explicit review |
| pyproject.toml | `version` field: `"v2.6.0-beta.4"` → `"v2.6.0-beta.2"` | looks like an accidental downgrade/merge artifact rather than an intentional change; flagged for Logan to confirm |
| runscript/anat_from_bids.py | add `sys.path.insert(...)` for package import when run as a subprocess; `os.path.expanduser(args.input)` → `os.path.realpath(os.path.expanduser(args.input))` | resolving symlinks before processing could change which underlying file FSL reads if `input` is a symlink (e.g. git-annex); needs numeric verification |
| runscript/fmap_from_bids_topup.sh | `ln -s` → `ln -sf` for AP/PA symlinks | overwrite-safe symlink creation; likely neutral (idempotent re-run) but feeds directly into topup input, so left for verification rather than assumed |
| runscript/func_from_bids.py | add `sys.path.insert(...)`; input resolved via `os.path.realpath` for processing while the original (`bids_input`) path is kept for the JSON-sidecar lookup | if `input` is a symlink (e.g. git-annex), processing now operates on the realpath target instead of the symlink — needs numeric verification that this doesn't change which data is read |
| tedana-requirements.txt | new file, pins `tedana==24.0.1`, `nilearn==0.10.4` | new dependency pin for the ME/tedana pathway; does not exist in upstream at all — scope/need to be decided when the ME path is packaged |
