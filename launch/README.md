# iproc-run — site-profile-driven launcher

`iproc-run` submits one `sbatch` job per subject that runs iProc inside the
`iproc.sif` apptainer container. All site-specific detail — container path,
bind mounts, storage roots, SLURM partitions, and per-stage resource
requests — lives in a **site profile** YAML file, so the same launcher works
unchanged on a laptop-with-SLURM, a lab cluster, or Sherlock.

## Usage

```bash
launch/iproc-run <profile.yaml> <subjects.txt> <stage> [options]
```

- `profile.yaml` — a site profile (see `src/iproc/data/site_profiles/`).
- `subjects.txt` — one subject label per line (e.g. `s01`). Blank lines and
  lines starting with `#` are ignored.
- `stage` — an iProc stage (`setup`, `bet`, `unwarp_motioncorrect_align`,
  `T1_warp_and_mask`, `combine_and_apply_warp`, `filter_and_project`, ...).
  Not validated by the launcher — `iProc.py -s` rejects unknown stages
  itself, so the launcher never has a stage list to keep in sync.

Options:
- `--bids-root PATH` — BIDS dataset root; required for the `setup` stage.
- `--dry-run` — print the `sbatch` command for every subject instead of
  submitting.

Environment:
- `IPROC_PYTHON` — path to a `python3` with PyYAML, used only to parse the
  profile (this parsing step runs on the submitting host, not in the
  container). If unset, `iproc-run` tries this repo's `.venv/bin/python3`,
  then falls back to `python3`/`python` on `PATH`.

Examples:

```bash
launch/iproc-run src/iproc/data/site_profiles/sherlock.yaml subjects.txt setup \
    --bids-root $OAK/data/my_bids_dataset

launch/iproc-run src/iproc/data/site_profiles/sherlock.yaml subjects.txt bet

launch/iproc-run src/iproc/data/site_profiles/sherlock.yaml subjects.txt setup \
    --bids-root $OAK/data/my_bids_dataset --dry-run
```

## Site profile schema

```yaml
name: <string>                 # profile identifier, printed in banners/logs
scheduler: slurm               # reserved for future non-SLURM backends
container: <path>              # path to iproc.sif; may use $ENV_VARS
binds: ["<host>:<container>"]  # apptainer --bind entries
storage:
  code_root: <path>            # iProc checkout used inside the container
  output_root: <path>          # where per-subject configs/logs/derivatives live
partitions:
  default: <slurm partition>   # partition used unless a stage says otherwise
  long: <slurm partition>      # optional: a second partition for long stages
resources:
  default: { time: "HH:MM:SS", mem: <size>, cpus: <n> }
  <stage>: { time: ..., mem: ..., cpus: ..., partition: <partitions key> }
fsl: { mode: mapped }          # reserved for future FSL output-type handling
modules: []                    # reserved for module-based (non-container) sites
```

- **Resource resolution**: for a given stage, `iproc-run` merges
  `resources.<stage>` over `resources.default` (stage keys win). Any field
  a stage doesn't override — `time`, `mem`, `cpus`, or `partition` — is
  inherited from `default`.
- **Partition selection**: a stage's merged resource block may set
  `partition: <key>`, where `<key>` names an entry under top-level
  `partitions:`. If a stage doesn't set `partition`, `iproc-run` uses the
  `default` partition. This is how long-running stages (e.g. `setup`) get
  routed to a different partition/QOS without hardcoding partition names
  into the launcher itself.
- **Shell-variable expansion**: `container`, `storage.*_root`, and `binds`
  may contain literal shell variable references (e.g. `$SCRATCH`, `$OAK`).
  `iproc-run` does not resolve these itself — it lets the shell that
  *invokes* `iproc-run` expand them at submission time, so the same profile
  works for every user on a shared cluster without hardcoding a path.

### Shipped profiles

- `generic-slurm.yaml` — a portable default for any vanilla SLURM cluster;
  paths are relative to the current directory and there's no `long`
  partition (long stages just use `default`).
- `sherlock.yaml` — Stanford Sherlock. Uses `$SCRATCH` for the code
  checkout and job output (fast, but purged — copy finished derivatives to
  `$OAK` yourself), binds `/oak` and `/scratch` into the container, and
  routes the `setup` stage to the `russpold` partition (`long`) while
  everything else uses `normal` (`default`).

Task 11 adds `iproc-init`, an interactive wizard for generating a new site
profile without hand-writing YAML.

## What each `sbatch` submission runs

For each subject, `iproc-run` builds:

```
sbatch --job-name=iproc_<stage>_<subject> \
    --partition <resolved> --time <resolved> --mem <resolved> --cpus-per-task <resolved> \
    --output=<output_root>/mri_data/<subject>/logs/slurm_<stage>_%j.log \
    --error=<output_root>/mri_data/<subject>/logs/slurm_<stage>_%j.err \
    --wrap="apptainer exec --bind <binds> <container> \
        bash -c 'source /opt/iproc-venv/bin/activate && \
                 cd <code_root> && pip install -e . && \
                 python iProc.py -c <output_root>/mri_data/<subject>/subject_lists/<subject>.cfg \
                     -s <stage> [--bids <bids_root>/sub-<subject>] --executor local'"
```

This mirrors the fork's `bids_setup/run_subjects.sh`, generalized so the
partition/time/mem/cpus/container/binds/paths all come from the profile
instead of being hardcoded per site.

## Known limitations / not yet wired up

- `fsl.mode` and `modules` are parsed from the profile but not yet used by
  the launcher — they're placeholders for sites that need FSL output-type
  handling or `module load`-based (non-container) execution.
- The FSL 5.0.10 hex-float `flirt`/`convert_xfm` wrapper-binary workaround
  used by the original `run_subjects.sh` is not replicated here; sites that
  need it should add the extra binds to their profile's `binds:` list.
