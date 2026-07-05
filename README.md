# iproc

Containerized, generalized repackaging of **upstream iProc** — individualized
(deeply-sampled, single-subject) fMRI preprocessing.

> **Upstream & attribution.** iProc is the work of the Harvard Neuroinformatics
> Research Group: **[harvard-nrg/iProc](https://github.com/harvard-nrg/iProc)**
> (`v2.6.0-beta.4`) is the scientific reference and is vendored here verbatim. This
> repository only *repackages* it — the science is theirs; please cite and defer to
> the upstream project. Container/Sherlock/BIDS infrastructure is adapted from
> [lobennett/iProc@container-and-bids-tooling](https://github.com/lobennett/iProc/tree/container-and-bids-tooling).
> See [`NOTICE.md`](NOTICE.md) and [`docs/fork-audit.md`](docs/fork-audit.md).

Scientific behavior replicates upstream iProc (`v2.6.0-beta.4`). This repo adds an
Apptainer container (pinned neuroimaging + core-Python deps; see caveat below),
BIDS-dataset generalization (any fieldmap regime, any #subjects/sessions/scanner),
an HPC site-profile + wizard launcher, tests, and a validation harness. See `docs/`.

> **Pinning caveat:** the core iProc Python deps (numpy, scipy, nibabel, PyYAML,
> etc.) and the neuroimaging toolchain (FSL, FreeSurfer, AFNI, ANTs, dcm2niix) are
> version-pinned in `container/iproc.def`. The multi-echo **tedana** stack
> (scikit-learn, nilearn, mapca, bokeh, robustica, seaborn, …) and the base apt
> packages are **not** fully pinned, so multi-echo/ICA output is not yet
> byte-reproducible across rebuilds — see `container/README.md`.

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
