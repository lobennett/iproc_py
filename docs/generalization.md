# Generalization

This package generalizes upstream iProc from a small set of hand-curated
lab datasets to arbitrary BIDS datasets (any fieldmap regime, any number of
subjects/sessions, any scanner manufacturer) — without changing what
upstream computes for the cases upstream already handled. This document
describes the model behind that, regime by regime, and the safety gates
that keep silent misprocessing from happening on data the detectors are
unsure about.

## The detect-and-preserve model

Every place this package had to generalize a upstream assumption follows
the same shape, established in `docs/fork-audit.md`'s classification of
upstream vs. fork behavior:

1. **Detect** the relevant property of the input data (fieldmap regime,
   T1 orientation, presence/absence of `ses-` directories, etc.) from the
   BIDS metadata itself — never from a hardcoded assumption about "the lab's
   usual dataset."
2. **Default to upstream's behavior** for whatever the detector recognizes
   as upstream's original case (Siemens/Varian phasediff fieldmaps,
   already-appropriately-oriented handling via `fslswapdim`, fixed-length
   runs), so datasets that look like what upstream was built for get
   bit-identical treatment.
3. **Extend, but flag, new capability** the detector identifies as *not*
   upstream's case (e.g. GE fieldmaps) — implemented because real datasets
   need it, but marked low-confidence or explicitly warned so nobody
   mistakes "this package processed it" for "upstream validated this."
4. **Refuse rather than guess** when detection itself is ambiguous
   (missing `Manufacturer`, no usable fieldmap for a BOLD run, etc.),
   surfaced as a warning plus an explicit `--force`/`--allow-no-fieldmap`
   opt-in gate rather than a silent default.

Concretely, this lives in two small modules plus the BIDS tooling that
consumes them:

- `src/iproc/fieldmap/` — `detect_regime()` / `plan_fieldmaps()`, fieldmap
  regime detection.
- `src/iproc/orientation/` — `registration_policy()`, T1 orientation policy.
- `bids_setup/bids_discover.py` / `bids_generate.py` — BIDS-to-`.cfg`
  generalization (session-optional, cross-session anat, the safety gates).

## Fieldmap regimes

`iproc.fieldmap.detect_regime(fmap_dir)` inspects a session's `fmap/`
directory and returns a `Decision` (`value`, `confidence`, `rationale`,
`evidence`, `warnings`). Priority order (checked in this sequence):

1. **Pepolar (opposite phase-encoding `_epi` pairs) → `topup`.** Detected
   from BIDS `dir-`-entity `_epi` files. High confidence requires at least
   two distinct `PhaseEncodingDirection` values across the EPIs; fewer than
   two is low-confidence ("pepolar detected but <2 distinct
   PhaseEncodingDirection values; VERIFY"). Routes to `FMAP_AP`/`FMAP_PA`
   columns and `PREPTOOL=topup` in the generated `.cfg`.

2. **Phasediff (magnitude + phase/phasediff pair) → `fsl_prepare_fieldmap`.**
   This is upstream's own regime (Siemens/Varian gradient-echo). Detection
   reads the phase JSON's `Manufacturer` and echo-time fields:
   - **Siemens/Varian, or unrecognized manufacturer** → `fsl_prepare_fieldmap`,
     matching upstream exactly. An unrecognized/missing `Manufacturer`
     still defaults here (not an error) but is flagged low-confidence
     ("Manufacturer missing in JSON; defaulting to SIEMENS — VERIFY"),
     because silently guessing SIEMENS is the upstream-compatible default,
     but it is still a guess.
   - **GE or Philips** → same `fsl_prepare_fieldmap` routing, but flagged
     `ge_special=True` with an explicit warning: **"using GE Hz-fieldmap
     path (new capability, not upstream) — VERIFY results."** This is new
     capability relative to upstream (which only ever saw Siemens/Varian in
     practice) — see `bids_setup/README.md`'s `×2π` handling in
     `fmap_from_bids.py` and `docs/fork-audit.md` bucket B. It is not
     scientifically validated the way the Siemens path is; treat any GE run
     as needing its own QC pass, not a rubber-stamp of the Siemens
     confidence level.
   - The echo-time delta (`delta_te_ms`) is read from `EchoTimeDifference`
     if present, else derived from `EchoTime1`/`EchoTime2`; missing both is
     also flagged low-confidence.

3. **Direct (`_fieldmap` file, no phase/magnitude pair) → `direct`.**
   Always low-confidence ("direct-fieldmap path is uncommon; VERIFY") —
   this regime is rare in practice and not exercised against real data by
   this package's test suite. Routed through the same `FMAP_MAG`/
   `FMAP_PHASE` columns as phasediff in the generated scanlist, but its
   files are not separately discovered the way phasediff's are (see
   Concerns in the task-7 fork-audit trail) — treat `direct` as
   functional-but-unaudited.

4. **None (no `fmap/` directory, or one with unrecognized contents).**
   A missing `fmap/` directory is high-confidence "none." A `fmap/`
   directory that exists but contains files matching none of the patterns
   above is low-confidence "none" ("fmap/ has files but no recognized
   regime; VERIFY") rather than erroring — the ambiguity is surfaced for a
   human, not silently dropped or crashed on.

## Orientation

`iproc.orientation.registration_policy(t1_path, config)` governs whether
the T1→MNI registration step applies `fslswapdim` and how wide FLIRT's
search range is:

- **Default (`orientation_mode` unset, or anything other than
  `"fork_no_swap"`)**: `swapdim=True`, FLIRT search `(-180, 180)` —
  upstream's exact behavior, `source="upstream"`.
- **Opt-in fork variant (`config={"orientation_mode": "fork_no_swap"}`)**:
  `swapdim=False`, FLIRT search `(-30, 30)`, `source="fork"` — the fork's
  assumption that its T1s are already RAS-oriented, which narrows the
  search and skips the swap. This is **never** the default; it must be
  requested explicitly per the same detect-and-preserve principle (a
  narrower search + no swap is a different numeric answer than upstream on
  data that isn't actually pre-oriented the way the fork's data was).
- If the T1 is detected as already RAS-oriented (`nib.aff2axcodes ==
  ("R","A","S")`) but `orientation_mode` was left at its default, the
  policy still returns the **upstream** settings — it only logs a warning
  ("already RAS+... if T1->MNI misregisters, retry with
  orientation_mode=fork_no_swap. VERIFY registration QC.") rather than
  silently switching behavior. Detection informs the warning; it never
  overrides the explicit/default choice.
- If the affine can't be read at all, the policy assumes non-RAS and falls
  through to the upstream default — the conservative failure mode either
  way is "behave like upstream," not "behave like the fork."

## Session-optional BIDS layouts

Upstream (and the fork) assumed every subject has `ses-*` subdirectories.
`bids_discover.py` supports datasets with no session structure at all: if a
subject directory has no `ses-*` children, the subject directory itself is
treated as a single session whose session id equals the subject label. This
is transparent to everything downstream — the manifest, `.cfg`, and scanlist
generation all operate on "sessions" whether or not the BIDS tree actually
nests by session.

## Cross-session anatomical broadcast

A subject's T1 selection (upstream's rule: latest session with a T1w) is
made once, subject-wide, and its series number is written into **every**
session's BOLD `ANAT` column in the generated scanlist — not just the
session the T1 itself lives in. Without this, a session that legitimately
has BOLD runs but no anatomical of its own would get `ANAT=0` and fail
downstream registration; instead it correctly references the subject's one
chosen T1 regardless of which session the T1 was actually acquired in.

## Warnings and the `--force` / `--allow-no-fieldmap` gates

`bids_generate.py` refuses to write any config files (nonzero exit, no
partial output) in two independent situations, each requiring an explicit
opt-in flag to proceed:

- **Low-confidence detection anywhere** (any subject/session with
  `confidence == "low"` — missing manufacturer, ambiguous pepolar
  direction, an unparsed `fmap/`, etc.) → exit 2, "re-run with `--force`
  once you've reviewed the manifest's `detections`." This is a
  human-review gate, not a correctness fix — `--force` does not change any
  processing, it only asserts "I looked at the low-confidence warnings and
  I'm proceeding anyway."

- **BOLD runs with no usable fieldmap in their own session** → exit 3
  unless `--allow-no-fieldmap`. This gate is evaluated **per session**, not
  subject-wide: a subject where session 1 has a fieldmap but session 2's
  BOLD runs have none is still blocked (naming exactly which
  subject/session/run is missing a fieldmap) even though the subject as a
  whole has *a* fieldmap somewhere. This was a real bug found and fixed
  during development (Task 7 follow-up) — an earlier subject-wide rollup
  let session-2-only BOLD runs silently get `Analyze=0` with no warning and
  no error; it's now impossible to lose a fieldmap-less BOLD run without an
  explicit, per-run WARNING and the `--allow-no-fieldmap` flag.

> **`--allow-no-fieldmap` does not mean "process without distortion
> correction."** It means: **deselect** (write `Analyze=0` in the
> scanlist for) BOLD runs whose session has no usable fieldmap, with a
> per-run warning, so the rest of the subject's data still processes. Those
> deselected runs are **not run through `unwarp_motioncorrect_align`** —
> they are excluded from processing entirely, not processed unwarped. True
> SDC-less processing (running fieldmap-less BOLD through the pipeline
> *without* susceptibility distortion correction, rather than excluding it)
> is **not implemented** and is a documented future follow-up, not
> something you should assume `--allow-no-fieldmap` gives you today. If you
> need those runs processed rather than dropped, you currently have to
> either provide a fieldmap for them or accept upstream's own no-SDC
> limitation is unaddressed here.

## A known `.cfg` limitation: one `PREPTOOL` per subject

The generated `.cfg` format (upstream's own format, unchanged) carries a
single, subject-wide `PREPTOOL` value (`fsl_prepare_fieldmap` / `topup` /
etc.) — there is no per-session `PREPTOOL` field. `bids_discover.py` still
records the fieldmap regime **per session** in the manifest (each session
gets its own `detection`/`fieldmap_type`), and `bids_generate.py`'s
scanlist-generation and the two safety gates above operate per session
correctly. But the one `.cfg` PREPTOOL that upstream's runscripts read is
set from "the preptool of the first session with a usable regime" — so a
subject whose sessions use genuinely *different* fieldmap regimes (e.g.
session 1 Siemens phasediff, session 2 pepolar) will have per-session
scanlist routing that's correct, but a single subject-level `.cfg` value
that only reflects one of those regimes. This is a real limitation
inherited from upstream's config format, not a bug in this package's
detection or scanlist logic — it only matters for subjects with genuinely
mixed regimes across sessions, which is uncommon but not impossible in
multi-session/multi-visit studies. Flagged here rather than fixed because
changing the `.cfg` format itself is out of scope for a repackaging effort
that otherwise preserves upstream's config schema verbatim.

## See also

- `docs/fork-audit.md` — the full upstream-vs-fork classification (buckets
  A: numerics-neutral infra fixes applied; B: scientific/behavior-changing,
  defaulted to upstream; C: infrastructure adopted wholesale; D: uncertain,
  pending Phase-B numeric review).
- `docs/validation.md` — how generalized behavior is pinned back to
  upstream defaults to construct the "upstream-behavior baseline" used for
  Phase A/B validation.
- `bids_setup/README.md` — the manifest fields (`detections`,
  `fieldmap_confidence`) and generation flags (`--force`,
  `--allow-no-fieldmap`, `--manufacturer`) in full CLI-reference form.
