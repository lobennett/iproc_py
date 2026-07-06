# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "nibabel>=5.0",
#     "pyyaml>=5.0",
#     "pybids<0.19",
# ]
# ///
"""
bids_discover.py — Scan a BIDS dataset and produce an editable YAML manifest
for iProc configuration generation.

Usage:
    uv run bids_discover.py /path/to/bids_root \
        --output manifest.yaml \
        --skip 7 \
        --smoothing 0 \
        --resolution 111 \
        --echo-time-diff 0.002272

The manifest is the checkpoint between discovery and generation.
Review it, edit T1 selections or exclude sessions, then pass to bids_generate.py.

File discovery uses pybids' BIDSLayout so that BIDS entities we do not model
explicitly (acq-, dir-, part-, rec-, ce-, ...) and uncompressed .nii files are
found and grouped correctly, instead of being silently dropped by hand-rolled
filename regexes.
"""
from __future__ import annotations

import argparse
import fnmatch
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import nibabel as nib
import yaml

from bids import BIDSLayout

from iproc.fieldmap import detect_regime

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# NIfTI extensions we accept everywhere (both compressed and uncompressed).
NII_EXT = [".nii", ".nii.gz"]

# Map fieldmap regime preptool -> iProc PREPTOOL / manifest fieldmap_type.
# detect_regime already reports evidence["preptool"] in iProc's vocabulary
# (fsl_prepare_fieldmap / topup / direct); "none" has no preptool.


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------

def _num_key(value: Any):
    """Sort key that orders numeric-looking labels numerically, others lexically.

    Ensures run-10 sorts after run-2 and ses-10 after ses-2 instead of lexically.
    Numeric labels sort before non-numeric ones; both groups are stable.
    """
    if value is None:
        return (0, 0.0, "")
    s = str(value)
    m = re.fullmatch(r"0*(\d+)", s)
    if m:
        return (0, float(m.group(1)), "")
    return (1, 0.0, s)


# ---------------------------------------------------------------------------
# NIfTI header inspection
# ---------------------------------------------------------------------------

def get_nvols(nii_path: Path) -> int:
    """Get number of volumes from NIfTI header without loading data."""
    try:
        img = nib.load(str(nii_path))
        shape = img.shape
        return shape[3] if len(shape) > 3 else 1
    except Exception as e:
        log.warning("Could not read %s: %s", nii_path.name, e)
        return 0


# ---------------------------------------------------------------------------
# .bidsignore filtering
# ---------------------------------------------------------------------------

def load_bidsignore_patterns(bids_root: Path) -> list[str]:
    """Read .bidsignore from the BIDS root; one glob pattern per non-empty line."""
    ignore_path = bids_root / ".bidsignore"
    if not ignore_path.exists():
        return []
    return [
        line.strip()
        for line in ignore_path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def is_bidsignored(relative_path: str, patterns: list[str]) -> bool:
    """Match a BIDS-relative path (e.g. 'sub-s10/ses-01/func/...') against patterns."""
    return any(fnmatch.fnmatch(relative_path, p) for p in patterns)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _fmap_dir_for(bids_root: Path, sub_label: str, ses_query: str | None) -> Path:
    """Filesystem path to the fmap/ directory (for regime detection)."""
    base = bids_root / f"sub-{sub_label}"
    if ses_query is not None:
        base = base / f"ses-{ses_query}"
    return base / "fmap"


def discover_subject(
    layout: BIDSLayout,
    bids_root: Path,
    sub_label: str,
    skip: int,
    smoothing: float,
    echo_time_diff: float,
    bidsignore: list[str],
) -> dict:
    """Discover all sessions, tasks, fieldmaps, and anatomicals for one subject.

    File discovery is delegated to pybids' BIDSLayout so entities we do not model
    (acq-, dir-, part-, rec-, ce-, ...) and uncompressed .nii files are found and
    grouped correctly instead of being silently dropped.
    """
    sub_id = f"sub-{sub_label}"

    sessions: dict[str, dict] = {}
    task_params: dict[str, dict] = {}

    def _keep(fpath: str) -> bool:
        """Honour .bidsignore against the BIDS-relative path."""
        try:
            rel = str(Path(fpath).relative_to(bids_root))
        except ValueError:
            rel = fpath
        if is_bidsignored(rel, bidsignore):
            log.debug("Skipping .bidsignored file: %s", rel)
            return False
        return True

    def _rel(fpath: str) -> str:
        try:
            return str(Path(fpath).relative_to(bids_root))
        except ValueError:
            return fpath

    # Discover sessions via pybids. Fall back to a no-`ses-` layout: if the
    # subject has no sessions, treat the subject as a single session whose id is
    # the subject label (query with session=None to match the flat layout).
    ses_ids = sorted(layout.get_sessions(subject=sub_label), key=_num_key)
    if ses_ids:
        session_items = [(s, s) for s in ses_ids]  # (ses_label, ses_query)
    else:
        session_items = [(sub_label, None)]

    for ses_label, ses_query in session_items:
        ses_data: dict[str, Any] = {
            "anat": [],
            "bold": [],
            "fmap_mag": [],
            "fmap_phase": [],
            "fmap_ap": [],
            "fmap_pa": [],
        }

        # We assign synthetic SeriesNumbers based on scan order within each
        # session. iProc uses these as identifiers in the CSV — the actual
        # values don't matter as long as they're consistent and unique per
        # session. We use: fmap_mag=2, fmap_phase=3, anat=50+run,
        # bold=series_number_from_json OR sequential assignment starting at 4.
        sn_counter = 4  # start after fmap slots

        # --- Fieldmaps ---
        fmap_dir = _fmap_dir_for(bids_root, sub_label, ses_query)

        # Regime-aware detection (phasediff / pepolar / direct / none) via the
        # shared iproc.fieldmap module. Emits warnings to stderr for every
        # auto-decision and records confidence/rationale into the manifest.
        decision = detect_regime(fmap_dir)
        ses_data["detection"] = {
            "regime": decision.value,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "preptool": decision.evidence.get("preptool"),
            "warnings": list(decision.warnings),
        }
        # Per-session fieldmap regime (preptool vocabulary), so bids_generate.py
        # can route and gate each session independently instead of relying on
        # the subject-wide rollup. A subject where one session has a fieldmap
        # and another does not must NOT have the fmap-less session's BOLD runs
        # silently deselected via the rollup.
        ses_data["fieldmap_type"] = decision.evidence.get("preptool") or "none"

        # Synthetic series numbers for pepolar AP/PA EPIs when JSON lacks them.
        epi_sn = 20
        fmap_files = layout.get(
            subject=sub_label, session=ses_query, datatype="fmap",
            extension=NII_EXT, return_type="file",
        )
        for f in sorted(fmap_files):
            if not _keep(f):
                continue
            ent = layout.parse_file_entities(f)
            suffix = ent.get("suffix", "")
            meta = layout.get_metadata(f)
            run = int(ent["run"]) if ent.get("run") is not None else 1

            if suffix == "epi":
                sn = meta.get("SeriesNumber", epi_sn)
                epi_sn += 1
                pe = meta.get("PhaseEncodingDirection", "")
                direction = str(ent.get("direction") or "").upper()
                entry = {
                    "file": _rel(f),
                    "run": run,
                    "series_number": sn,
                    "phase_encoding_direction": pe,
                    "dir": direction,
                }
                # Classify AP vs PA: prefer the BIDS `dir-` entity, fall back to
                # PhaseEncodingDirection (j == PA, j- == AP).
                if direction == "AP" or (not direction and pe.endswith("-")):
                    ses_data["fmap_ap"].append(entry)
                elif direction == "PA" or (not direction and pe and not pe.endswith("-")):
                    ses_data["fmap_pa"].append(entry)
                else:
                    # Unknown direction — keep as AP so it is not silently dropped.
                    ses_data["fmap_ap"].append(entry)

            elif suffix in ("magnitude", "magnitude1", "magnitude2"):
                sn = meta.get("SeriesNumber", 2)
                ses_data["fmap_mag"].append({
                    "file": _rel(f),
                    "run": run,
                    "series_number": sn,
                })

            elif suffix in ("phasediff", "phase1", "phase2", "fieldmap"):
                sn = meta.get("SeriesNumber", 3)
                te_diff = meta.get("EchoTimeDifference", echo_time_diff)
                ses_data["fmap_phase"].append({
                    "file": _rel(f),
                    "run": run,
                    "series_number": sn,
                    "echo_time_diff": te_diff,
                })

        # Ensure mag and phase SeriesNumbers are consistent
        # (phase must be mag+1 for iProc's fsl_prepare_fieldmap constraint)
        if ses_data["fmap_mag"] and ses_data["fmap_phase"]:
            mag_sn = ses_data["fmap_mag"][0]["series_number"]
            phase_sn = ses_data["fmap_phase"][0]["series_number"]
            if phase_sn - mag_sn not in (1, 2):
                ses_data["fmap_mag"][0]["series_number"] = 2
                ses_data["fmap_phase"][0]["series_number"] = 3

        # --- Anatomicals ---
        anat_files = layout.get(
            subject=sub_label, session=ses_query, suffix="T1w",
            extension=NII_EXT, return_type="file",
        )
        for f in sorted(anat_files):
            if not _keep(f):
                continue
            ent = layout.parse_file_entities(f)
            meta = layout.get_metadata(f)
            run = int(ent["run"]) if ent.get("run") is not None else 1
            sn = meta.get("SeriesNumber", 50 + run)
            ses_data["anat"].append({
                "file": _rel(f),
                "run": run,
                "series_number": sn,
            })

        # --- Functional ---
        bold_files = layout.get(
            subject=sub_label, session=ses_query, suffix="bold",
            extension=NII_EXT, return_type="file",
        )
        # Group multi-echo acquisitions by (task, run); collect their echoes.
        task_run_echoes: dict[tuple[str, int], list] = defaultdict(list)
        for f in sorted(bold_files):
            if not _keep(f):
                continue
            ent = layout.parse_file_entities(f)
            task = ent.get("task")
            if task is None:
                continue
            run = int(ent["run"]) if ent.get("run") is not None else 1
            echo = int(ent["echo"]) if ent.get("echo") is not None else 1
            task_run_echoes[(task, run)].append({
                "file": _rel(f),
                "task": task,
                "run": run,
                "echo": echo,
                "nii_path": Path(f),
            })

        # Numeric ordering: (task, run) with run-10 after run-2.
        for (task, run), echoes in sorted(
            task_run_echoes.items(), key=lambda kv: (kv[0][0], _num_key(kv[0][1]))
        ):
            echoes = sorted(echoes, key=lambda e: e["echo"])
            first = echoes[0]
            nii_path = first["nii_path"]

            meta = layout.get_metadata(str(nii_path))
            nvols_total = get_nvols(nii_path)
            nvols = max(0, nvols_total - skip)
            nechos = len(echoes)

            series_number = meta.get("SeriesNumber", sn_counter)
            sn_counter = max(sn_counter, series_number) + 1
            tr = meta.get("RepetitionTime", 0)
            echo_time = meta.get("EchoTime", 0)
            eff_echo_spacing = meta.get("EffectiveEchoSpacing", 0)
            phase_dir = meta.get("PhaseEncodingDirection", "")

            ses_data["bold"].append({
                "task": task,
                "run": run,
                "series_number": series_number,
                "num_volumes_total": nvols_total,
                "num_volumes": nvols,
                "num_echos": nechos,
                "tr": round(tr, 4) if tr else None,
                "echo_time": round(echo_time, 6) if echo_time else None,
                "effective_echo_spacing": round(eff_echo_spacing, 8) if eff_echo_spacing else None,
                "phase_encoding_direction": phase_dir,
            })

            task_upper = task.upper()
            if task_upper not in task_params:
                task_params[task_upper] = {
                    "task_bids_name": task,
                    "tr": round(tr, 4) if tr else None,
                    "skip": skip,
                    "smoothing": smoothing,
                    "num_volumes": nvols,
                    "num_echos": nechos,
                }

        sessions[ses_label] = ses_data

    # --- T1 selection: pick the LATEST session with a T1w ---
    t1_selection = None
    for ses_label in sorted(sessions.keys(), key=_num_key, reverse=True):
        anats = sessions[ses_label]["anat"]
        if anats:
            best = sorted(anats, key=lambda a: a["run"])[-1]
            t1_selection = {
                "session": ses_label,
                "run": best["run"],
                "series_number": best["series_number"],
                "file": best["file"],
            }
            break

    if t1_selection is None:
        log.warning("No T1w found for %s", sub_id)

    # --- MIDVOL target: first session, first BOLD run ---
    midvol = None
    for ses_label in sorted(sessions.keys(), key=_num_key):
        bolds = sessions[ses_label]["bold"]
        if bolds:
            first_bold = bolds[0]
            midvol_vol = first_bold["num_volumes"] // 2
            midvol = {
                "session": ses_label,
                "task": first_bold["task"],
                "run": first_bold["run"],
                "bold_series_number": first_bold["series_number"],
                "volume": midvol_vol,
            }
            break

    if midvol is None:
        log.warning("No BOLD data found for %s", sub_id)

    # --- Detect fieldmap type (regime-aware, via iproc.fieldmap) ---
    # fieldmap_type = the preptool of the first session with a usable regime.
    # Record every session's decision for human review, and roll up the lowest
    # confidence so bids_generate.py can gate low-confidence input behind --force.
    detections = []
    fmap_type = None
    confidence = "high"
    for ses_label in sorted(sessions.keys(), key=_num_key):
        det = sessions[ses_label].get("detection")
        if not det:
            continue
        detections.append({
            "session": ses_label,
            "regime": det["regime"],
            "confidence": det["confidence"],
            "rationale": det["rationale"],
            "preptool": det["preptool"],
            "warnings": det["warnings"],
        })
        if det["confidence"] == "low":
            confidence = "low"
        if fmap_type is None and det["preptool"]:
            fmap_type = det["preptool"]

    if fmap_type is None:
        log.warning("No usable fieldmap regime detected for %s", sub_id)

    return {
        "sub_label": sub_label,
        "sessions": sessions,
        "task_params": task_params,
        "t1_selection": t1_selection,
        "midvol": midvol,
        "fieldmap_type": fmap_type or "none",
        "fieldmap_confidence": confidence,
        "detections": detections,
        "echo_time_diff": echo_time_diff,
    }


def discover_dataset(
    bids_root: Path,
    skip: int,
    smoothing: float,
    resolution: int,
    echo_time_diff: float,
    subjects: list[str] | None = None,
) -> dict:
    """Discover the entire BIDS dataset."""
    bids_root = bids_root.resolve()

    if not bids_root.is_dir():
        log.error("BIDS root does not exist: %s", bids_root)
        sys.exit(1)

    bidsignore = load_bidsignore_patterns(bids_root)

    # Index the dataset once with pybids. validate=False so partially-BIDS or
    # in-progress datasets still index; discovery is tolerant by design.
    layout = BIDSLayout(str(bids_root), validate=False)

    all_labels = sorted(layout.get_subjects(), key=_num_key)

    if subjects:
        # Accept both "sub-01" and "01" forms in --subjects.
        wanted = {s.replace("sub-", "") for s in subjects}
        sub_labels = [lbl for lbl in all_labels if lbl in wanted]
    else:
        sub_labels = all_labels

    if not sub_labels:
        log.error("No subjects found in %s", bids_root)
        sys.exit(1)

    log.info("Found %d subject(s) in %s", len(sub_labels), bids_root)

    all_subjects = {}
    all_tasks: dict[str, dict] = {}

    for sub_label in sub_labels:
        log.info("Discovering sub-%s ...", sub_label)
        sub_data = discover_subject(
            layout, bids_root, sub_label, skip, smoothing, echo_time_diff, bidsignore,
        )
        # Key by subject label (e.g. "01"), not the "sub-01" directory name, so
        # the manifest matches iProc's SUBJID convention.
        all_subjects[sub_data["sub_label"]] = sub_data

        for task_name, params in sub_data["task_params"].items():
            if task_name not in all_tasks:
                all_tasks[task_name] = params

    manifest = {
        "_notes": {
            "generated_by": "bids_discover.py",
            "description": (
                "Review this manifest before running bids_generate.py. "
                "You can edit t1_selection, midvol, skip, smoothing, "
                "resolution, or set Analyze=false on specific sessions/runs."
            ),
            "design_decisions": {
                "t1_selection": "Uses the LATEST session with a T1w (rationale: earlier T1s may be low quality)",
                "midvol_target": "First session, first BOLD run, middle volume",
                "skip_volumes": f"{skip} dummy scans discarded from start of each functional run",
                "smoothing": f"{smoothing}mm FWHM (use 0 for surface-only analysis)",
                "resolution": f"{'1mm' if resolution == 111 else '2mm'} isotropic output template",
                "echo_time_diff": f"{echo_time_diff}s ({echo_time_diff * 1000:.3f}ms) for fsl_prepare_fieldmap",
                "series_numbers": "Synthetic SeriesNumbers assigned when JSON sidecars lack them (fmap_mag=2, fmap_phase=3, anat=50+run, bold=from JSON or sequential)",
            },
        },
        "study": {
            "bids_root": str(bids_root),
            "resolution": resolution,
            "default_smoothing": smoothing,
            "default_skip": skip,
            "echo_time_diff": echo_time_diff,
        },
        "tasks": all_tasks,
        "subjects": all_subjects,
    }

    return manifest


# ---------------------------------------------------------------------------
# Validation warnings
# ---------------------------------------------------------------------------

def validate_manifest(manifest: dict) -> list[str]:
    """Run basic sanity checks on the discovered manifest."""
    warnings = []

    for sub_name, sub_data in manifest["subjects"].items():
        if sub_data["t1_selection"] is None:
            warnings.append(f"{sub_name}: No T1w anatomical found in any session")

        if sub_data["midvol"] is None:
            warnings.append(f"{sub_name}: No BOLD data found")

        for det in sub_data.get("detections", []):
            if det["confidence"] == "low":
                warnings.append(
                    f"{sub_name}/ses-{det['session']}: LOW-confidence fieldmap "
                    f"decision ({det['regime']}): {det['rationale']} "
                    f"— bids_generate.py will require --force"
                )
            for w in det.get("warnings", []):
                warnings.append(f"{sub_name}/ses-{det['session']}: {w}")

        sessions = sub_data["sessions"]
        for ses_label, ses_data in sessions.items():
            bolds = ses_data["bold"]
            regime = (ses_data.get("detection") or {}).get("regime", "none")
            has_fmap = (
                (ses_data["fmap_mag"] and ses_data["fmap_phase"])
                or (ses_data["fmap_ap"] and ses_data["fmap_pa"])
            )
            if bolds and not has_fmap:
                warnings.append(
                    f"{sub_name}/ses-{ses_label}: Has {len(bolds)} BOLD run(s) "
                    f"but no usable fieldmap (regime={regime})"
                )

            for bold in bolds:
                task_upper = bold["task"].upper()
                if task_upper not in manifest["tasks"]:
                    warnings.append(
                        f"{sub_name}/ses-{ses_label}: Task '{bold['task']}' not in task list"
                    )
                else:
                    expected = manifest["tasks"][task_upper]
                    if bold["num_echos"] != expected["num_echos"]:
                        warnings.append(
                            f"{sub_name}/ses-{ses_label}/{bold['task']}_run-{bold['run']}: "
                            f"echo count {bold['num_echos']} != expected {expected['num_echos']}"
                        )

    return warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Discover a BIDS dataset and produce an iProc manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("bids_root", type=Path, help="Path to BIDS dataset root")
    parser.add_argument("-o", "--output", type=Path, default=Path("manifest.yaml"),
                        help="Output manifest YAML (default: manifest.yaml)")
    parser.add_argument("--skip", type=int, default=7,
                        help="Number of dummy volumes to skip (default: 7)")
    parser.add_argument("--smoothing", type=float, default=6.0,
                        help="Smoothing kernel FWHM in mm (default: 6.0)")
    parser.add_argument("--resolution", type=int, choices=[111, 222], default=222,
                        help="Output resolution: 111=1mm, 222=2mm (default: 222)")
    parser.add_argument("--echo-time-diff", type=float, default=0.002272,
                        help="Fieldmap echo time difference in seconds (default: 0.002272 = 2.272ms, GE CNI standard)")
    parser.add_argument("--subjects", nargs="+", default=None,
                        help="Process only these subjects (e.g. sub-s03 sub-s04)")

    args = parser.parse_args()

    manifest = discover_dataset(
        args.bids_root,
        skip=args.skip,
        smoothing=args.smoothing,
        resolution=args.resolution,
        echo_time_diff=args.echo_time_diff,
        subjects=args.subjects,
    )

    warnings = validate_manifest(manifest)
    if warnings:
        log.warning("=== Validation Warnings ===")
        for w in warnings:
            log.warning("  %s", w)

    with open(args.output, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False, width=120)

    log.info("Manifest written to %s", args.output)
    log.info("Subjects: %d, Tasks: %d, Warnings: %d",
             len(manifest["subjects"]),
             len(manifest["tasks"]),
             len(warnings))
    log.info("")
    log.info("Next step: review the manifest, then run:")
    log.info("  uv run bids_generate.py %s --iproc-dir /path/to/iProc", args.output)


if __name__ == "__main__":
    main()
