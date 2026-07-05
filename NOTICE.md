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
| (Task 3 neutral env fixes) | see docs/fork-audit.md §A | container portability; numerics-neutral |
