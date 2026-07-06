# NOTICE

`iproc` repackages **upstream** [harvard-nrg/iProc](https://github.com/harvard-nrg/iProc)
`v2.6.0-beta.4` (the scientific reference). Infrastructure (container, Sherlock
portability, BIDS tooling) is adapted from
[lobennett/iProc@container-and-bids-tooling](https://github.com/lobennett/iProc).
See `docs/fork-audit.md` for the full change classification.

Scientific behavior matches upstream. Deviations are limited to:

| File | Change | Reason |
|------|--------|--------|
| src/iproc/cli/iproc.py | CODEDIR fallback → package dir | assets vendored inside the package |
| src/iproc/runscript/fmap_from_bids.py | added GE/Philips Hz→rad/s branch (capability upstream lacks); Siemens/Varian path unchanged, byte-behavior-identical to upstream | GE fieldmaps are Hz maps needing `fslmaths -mul 2π -mas`, not `fsl_prepare_fieldmap` |
| src/iproc/bids/__init__.py (`match_scan_no_to_bids`) | cross-session-anat ingestion: visit every session and glob/require each modality's JSON sidecars only when the session has scans of that modality (behavior-preserving for same-session datasets) | supports datasets whose T1w lives in a different session than the BOLD/fmap (e.g. MSC: T1 in `ses-struct*`, BOLD/fmap in `ses-func*`), which upstream crashed on with `IOError` |
| (Task 3 neutral env fixes) | see docs/fork-audit.md §A | container portability; numerics-neutral |
