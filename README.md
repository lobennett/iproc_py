# iproc

Containerized, generalized repackaging of **upstream iProc** — individualized
(deeply-sampled, single-subject) fMRI preprocessing.

Scientific behavior replicates upstream iProc (`v2.6.0-beta.4`). This repo adds an
Apptainer container (exact deps), BIDS-dataset generalization (any fieldmap regime,
any #subjects/sessions/scanner), an HPC site-profile + wizard launcher, tests, and a
validation harness. See `docs/`.

> **Validation status:** replication-by-construction + command-verified vs the
> upstream-behavior baseline (Phase A). Bit-identical numeric validation is confirmed
> interactively on Sherlock (Phase B) — see `docs/validation.md`. The scientific
> reference is upstream iProc, not any fork.

## Install (local, for tests/dev)
    uv venv --python 3.11 .venv && source .venv/bin/activate
    pip install -e '.[test]'
    iproc --help
