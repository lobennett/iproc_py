# iproc

Containerized, generalized repackaging of **upstream iProc** — individualized
(deeply-sampled, single-subject) fMRI preprocessing.

Scientific behavior replicates upstream iProc (`v2.6.0-beta.4`). This repo adds an
Apptainer container (exact deps), BIDS-dataset generalization (any fieldmap regime,
any #subjects/sessions/scanner), an HPC site-profile + wizard launcher, tests, and a
validation harness. See `docs/`.

> **Validation status:** **Phase A — done.** Replication-by-construction +
> command-verified vs the upstream-behavior baseline
> (`tests/test_golden_commands.py`, `docs/fork-audit.md`). **Phase B —
> pending.** Bit-identical numeric validation against an executed
> upstream-behavior baseline, plus a real-data (MSC, Siemens) methodological
> check, requires an interactive Sherlock session and has not yet been run —
> see `docs/validation.md` for the harness and what "validated" means here.
> The scientific reference is upstream iProc, not any fork.

## Install (local, for tests/dev)
    uv venv --seed --python 3.11 .venv && source .venv/bin/activate
    pip install -e '.[test]'
    iproc --help

(`--seed` ensures `pip` is present in the venv; `uv venv` alone does not install it.)

## Usage / Docs

- `docs/usage.md` — install, the six processing stages + manual QC
  checkpoints between them, running locally vs. via container vs. via
  `launch/iproc-run`, and the BIDS `discover → review → generate → run` flow.
- `docs/dependencies.md` — upstream's validated dependency versions, plus
  what the container provides and how it maps onto them.
- `docs/generalization.md` — the detect-and-preserve model, every fieldmap
  regime, orientation policy, session-optional/cross-session-anat handling,
  and the `--force`/`--allow-no-fieldmap` safety gates.
- `docs/validation.md` — what "validated" means for this package and the
  current Phase A/B status.
- `docs/fork-audit.md` — classification of every upstream-vs-fork
  difference this package had to decide on.
- `container/README.md`, `launch/README.md`, `bids_setup/README.md` —
  component-level references for the container build, the site-profile
  launcher, and the BIDS tooling CLI flags.
