"""iproc-app — nipreps-style BIDS-App console entry point for iProc.

This is an ADDITIVE second entrypoint modeled on MRIQC's ``cli/parser`` +
``cli/run`` split. It wraps the discover -> generate -> (optional) stage flow
behind the standard BIDS-App calling convention::

    iproc-app <bids_dir> <output_dir> participant \
        [--participant-label LABEL ...] [-w WORKDIR] [--stage STAGE] [--dry-run]

It never replaces the existing config-based per-stage engine (the ``iproc`` /
``iProc.py`` console script, ``iproc -c <cfg> -s <stage> ...``). That engine
stays the single source of truth for actually running a pipeline stage; this
CLI only *prepares* iProc configs from a BIDS tree and, when asked, hands a
single stage off to that engine by subprocess.

Design decisions
----------------
- **analysis_level**: iProc is a single-subject / individualized pipeline, so
  only ``participant`` is supported. ``group`` is a valid argparse choice (for a
  clear, BIDS-App-conventional error) but is rejected in validation.
- **Manual-QC staging**: iProc requires human QC checkpoints between stages, so
  participant-level runs never blindly run all six stages. With ``--stage`` we
  run exactly that one stage via the existing engine; without it we prepare the
  configs and print ordered next-step guidance.
- **--dry-run**: prints the resolved participants and the exact discovery /
  generation / stage commands that WOULD run, and writes NOTHING (no manifest,
  no derivatives, no stage execution). It exits 0.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from argparse import Namespace
from importlib import metadata
from pathlib import Path

from iproc.app import config
from iproc.app.derivatives import write_dataset_description
from iproc.bids_app import discover, generate
from iproc.__version__ import __version__ as IPROC_VERSION


def _dist_version() -> str:
    """The installed ``iproc`` distribution version.

    Falls back to the vendored ``iproc.__version__`` (e.g. ``v1.1.1``) only
    when the package metadata isn't available, such as running from a raw
    checkout that was never ``pip install``-ed.
    """
    try:
        return metadata.version("iproc")
    except metadata.PackageNotFoundError:
        return IPROC_VERSION


# The six iProc pipeline stages, in run order. Kept in lockstep with
# ``iproc.cli.iproc.phraseList`` but hardcoded here so building the parser does
# not import the heavy science module at load time.
STAGES: tuple[str, ...] = (
    "setup",
    "bet",
    "unwarp_motioncorrect_align",
    "T1_warp_and_mask",
    "combine_and_apply_warp",
    "filter_and_project",
)

# Discovery defaults mirror iproc.bids_app.discover.build_parser().
_DEFAULT_SKIP = 7
_DEFAULT_SMOOTHING = 6.0
_DEFAULT_RESOLUTION = 222
_DEFAULT_ECHO_TIME_DIFF = 0.002272


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iproc-app",
        description="Run iProc as a BIDS-App: prepare configs from a BIDS tree "
                    "and optionally run a single (QC-gated) pipeline stage.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("bids_dir", type=Path,
                        help="Root of the input BIDS dataset")
    parser.add_argument("output_dir", type=Path,
                        help="Output/derivatives directory (must differ from bids_dir)")
    parser.add_argument("analysis_level", choices=("participant", "group"),
                        help="Analysis level. Only 'participant' is supported "
                             "(iProc is an individualized, single-subject pipeline).")

    parser.add_argument("--participant-label", "--participant_label", nargs="+",
                        default=None, dest="participant_label",
                        help="One or more participant labels to process (a leading "
                             "'sub-' is stripped). Default: all subjects in bids_dir.")
    parser.add_argument("-w", "--work-dir", type=Path, default=None,
                        dest="work_dir",
                        help="Working directory for intermediate files "
                             "(e.g. the discovery manifest). Default: output_dir.")
    parser.add_argument("--stage", choices=STAGES, default=None,
                        help="Run this single iProc stage via the existing engine "
                             "after preparing configs. Default: prepare configs "
                             "and print next-step guidance (QC is manual).")
    parser.add_argument("--nprocs", "--n_procs", type=int, default=None,
                        dest="nprocs", help="Number of processes (informational).")
    parser.add_argument("--bids-filter-file", type=Path, default=None,
                        dest="bids_filter_file",
                        help="Path to a JSON BIDS filter file (informational).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan (participants + commands) without "
                             "writing outputs or running any stage.")
    parser.add_argument("--version", action="version",
                        version=f"iproc {_dist_version()}")

    # Discovery parameters (mirror bids_discover defaults).
    parser.add_argument("--skip", type=int, default=_DEFAULT_SKIP,
                        help="Number of dummy volumes to skip.")
    parser.add_argument("--smoothing", type=float, default=_DEFAULT_SMOOTHING,
                        help="Smoothing kernel FWHM in mm.")
    parser.add_argument("--resolution", type=int, choices=(111, 222),
                        default=_DEFAULT_RESOLUTION,
                        help="Output resolution: 111=1mm, 222=2mm.")
    parser.add_argument("--echo-time-diff", type=float,
                        default=_DEFAULT_ECHO_TIME_DIFF, dest="echo_time_diff",
                        help="Fieldmap echo time difference in seconds.")

    return parser


# ---------------------------------------------------------------------------
# Validation + participant resolution
# ---------------------------------------------------------------------------

def validate_args(args: Namespace, parser: argparse.ArgumentParser) -> None:
    """Validate paths and analysis level; exit via ``parser.error`` on failure."""
    if not args.bids_dir.exists():
        parser.error(f"bids_dir does not exist: {args.bids_dir}")
    if not args.bids_dir.is_dir():
        parser.error(f"bids_dir is not a directory: {args.bids_dir}")

    if args.output_dir.resolve() == args.bids_dir.resolve():
        parser.error(
            "output_dir must not equal bids_dir "
            f"(both resolve to {args.bids_dir.resolve()})"
        )

    if args.analysis_level != "participant":
        parser.error(
            f"analysis_level '{args.analysis_level}' is not supported: iProc is an "
            "individualized, single-subject pipeline — use 'participant'."
        )


def resolve_participants(
    bids_dir: Path, participant_label: list[str] | None
) -> list[str]:
    """Enumerate ``sub-*`` in ``bids_dir`` via pybids and intersect requests.

    A leading ``sub-`` is stripped from each requested label. Any requested
    label not present in the dataset raises ``SystemExit`` naming the missing
    label(s). Returns a sorted list of participant labels (no ``sub-`` prefix).
    """
    from bids import BIDSLayout

    layout = BIDSLayout(str(bids_dir), validate=False)
    available = set(layout.get_subjects())

    if not participant_label:
        return sorted(available)

    requested = [lbl[4:] if lbl.startswith("sub-") else lbl
                 for lbl in participant_label]
    missing = [lbl for lbl in requested if lbl not in available]
    if missing:
        raise SystemExit(
            "Requested participant label(s) not found in "
            f"{bids_dir}: {', '.join(sorted(missing))}. "
            f"Available: {', '.join(sorted(available)) or '(none)'}"
        )
    return sorted(set(requested))


# ---------------------------------------------------------------------------
# Config population
# ---------------------------------------------------------------------------

def populate_config(args: Namespace, participants: list[str]) -> None:
    """Populate the T6 config singleton from parsed args (reassign, don't mutate).

    ``bids_dir``/``output_dir`` are required positional ``Path`` args (never
    ``None`` by the time we get here) and ``main`` already calls
    ``parser.error`` if no participants resolve, so there is nothing left to
    strictly validate from known argparse args alone. Strict config-file
    validation belongs here once ``iproc-app`` gains config-file or
    ``--bids-filter-file`` ingestion (arbitrary user-supplied keys that
    argparse can't already guarantee) — reintroduce it then.
    """
    config.execution.bids_dir = args.bids_dir.resolve()
    config.execution.output_dir = args.output_dir.resolve()
    config.execution.work_dir = (
        args.work_dir.resolve() if args.work_dir is not None else None
    )
    config.execution.participant_label = list(participants)
    config.execution.dry_run = bool(args.dry_run)

    config.workflow.analysis_level = args.analysis_level
    config.workflow.stage = args.stage
    config.workflow.resolution = str(args.resolution)
    config.workflow.skip = args.skip
    config.workflow.smoothing = args.smoothing


# ---------------------------------------------------------------------------
# Command construction (for both dry-run printing and real execution)
# ---------------------------------------------------------------------------

def _manifest_path(work_dir: Path, label: str) -> Path:
    return work_dir / f"sub-{label}_manifest.yaml"


def _stage_command(bids_dir: Path, output_dir: Path, label: str, stage: str) -> list[str]:
    """The exact ``iproc`` console invocation for one participant + stage."""
    cfg = output_dir / "mri_data" / label / "subject_lists" / f"{label}.cfg"
    return [
        "iproc",
        "-c", str(cfg),
        "-s", stage,
        "--bids", str(bids_dir / f"sub-{label}"),
        "--executor", "local",
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _print_next_step_guidance() -> None:
    print("\nNext steps (iProc requires MANUAL QC between stages — do NOT run "
          "all stages blindly):")
    for i, stage in enumerate(STAGES, 1):
        print(f"  {i}. iproc-app <bids_dir> <output_dir> participant "
              f"--stage {stage}")
    print("\nRun one stage, QC its output, then run the next. Re-run this "
          "command with --stage <name> to run a single stage via the iProc "
          "engine.")


def _run_participant(args: Namespace, label: str, work_dir: Path) -> None:
    """Discovery + generation for one participant, then optional stage."""
    manifest_out = _manifest_path(work_dir, label)

    # 1. Discovery -> manifest (scoped to this one subject).
    discover_ns = Namespace(
        bids_root=args.bids_dir,
        output=manifest_out,
        skip=args.skip,
        smoothing=args.smoothing,
        resolution=args.resolution,
        echo_time_diff=args.echo_time_diff,
        subjects=[label],
    )
    discover.run_discover(discover_ns)

    # 2. Generation -> iProc .cfg + scanlist under output_dir.
    generate_ns = Namespace(
        manifest=manifest_out,
        iproc_dir=args.output_dir,
        codedir=None,
        fsldir="/opt/fsl-5.0.10",
        freesurfer_home="/opt/freesurfer-6.0.0",
        manufacturer=None,
        force=False,
        allow_no_fieldmap=False,
        allow_missing_anat=False,
    )
    generate.run_generate(generate_ns)

    # 3. Optional single stage via the existing iProc engine.
    if args.stage:
        cmd = _stage_command(args.bids_dir, args.output_dir, label, args.stage)
        print(f"\nRunning stage '{args.stage}' for sub-{label}:")
        print("  " + " ".join(cmd))
        subprocess.run(cmd, check=True)


def _print_dry_run(args: Namespace, participants: list[str], work_dir: Path) -> None:
    print("=== DRY RUN — the following WOULD run (no outputs written) ===")
    print(f"bids_dir:   {args.bids_dir}")
    print(f"output_dir: {args.output_dir}")
    print(f"resolved participants: {', '.join(participants) or '(none)'}")
    print(f"would write BIDS-Derivatives {args.output_dir}/dataset_description.json")
    for label in participants:
        manifest_out = _manifest_path(work_dir, label)
        print(f"\n--- sub-{label} ---")
        print("  would run discovery:")
        print(f"    bids_discover {args.bids_dir} --output {manifest_out} "
              f"--subjects sub-{label} --skip {args.skip} "
              f"--smoothing {args.smoothing} --resolution {args.resolution} "
              f"--echo-time-diff {args.echo_time_diff}")
        print("  would run generation:")
        print(f"    bids_generate {manifest_out} --iproc-dir {args.output_dir}")
        if args.stage:
            cmd = _stage_command(args.bids_dir, args.output_dir, label, args.stage)
            print(f"  would run stage '{args.stage}':")
            print("    " + " ".join(cmd))
    if not args.stage:
        _print_next_step_guidance()


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    validate_args(args, parser)
    participants = resolve_participants(args.bids_dir, args.participant_label)
    if not participants:
        parser.error(f"no participants found in {args.bids_dir}")

    populate_config(args, participants)

    work_dir = (args.work_dir or args.output_dir).resolve()

    if args.dry_run:
        _print_dry_run(args, participants, work_dir)
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Mark output_dir as a BIDS-Derivatives dataset (dataset_description.json).
    desc = write_dataset_description(args.output_dir)
    print(f"wrote {desc}")

    for label in participants:
        print(f"\n=== Preparing iProc config for sub-{label} ===")
        _run_participant(args, label, work_dir)

    if not args.stage:
        _print_next_step_guidance()

    return 0


if __name__ == "__main__":
    sys.exit(main())
