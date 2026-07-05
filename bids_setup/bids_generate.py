# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "pyyaml>=5.0",
# ]
# ///
"""
bids_generate.py — Generate iProc configuration files from a BIDS manifest.

Usage:
    uv run bids_generate.py manifest.yaml \
        --iproc-dir /path/to/derivatives/iproc \
        --codedir /path/to/iProc

Reads the manifest produced by bids_discover.py and generates:
  1. configs/tasktype_consolidated.csv
  2. mri_data/{sub}/subject_lists/scanlist_{sub}.csv  (per subject)
  3. mri_data/{sub}/subject_lists/{sub}.cfg            (per subject)
  4. Patched JSON sidecars for fieldmaps and T1w missing metadata

The manifest should be reviewed/edited before running this script.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import yaml

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Generate tasktype_consolidated.csv
# ---------------------------------------------------------------------------

def generate_tasktype_csv(tasks: dict, output_path: Path) -> None:
    """Write configs/tasktype_consolidated.csv."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for task_name, params in sorted(tasks.items()):
        rows.append({
            "TYPE": task_name.upper(),
            "TR": params["tr"],
            "SKIP": params["skip"],
            "SMOOTHING": params["smoothing"],
            "NUMVOL": params["num_volumes"],
            "NUMECHOS": params["num_echos"],
        })

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["TYPE", "TR", "SKIP", "SMOOTHING", "NUMVOL", "NUMECHOS"])
        writer.writeheader()
        writer.writerows(rows)

    log.info("  Written: %s (%d task types)", output_path, len(rows))


# ---------------------------------------------------------------------------
# Patch JSON sidecars
# ---------------------------------------------------------------------------

def patch_json_sidecars(
    bids_root: Path,
    sub_data: dict,
    echo_time_diff: float,
    manufacturer: str | None = None,
) -> int:
    """Generate/patch JSON sidecars for files missing required iProc metadata.

    Writes patched JSONs alongside existing NIfTI files. Existing JSON content
    is preserved — only missing fields are added.

    Returns the number of files patched.
    """
    patched = 0

    for ses_label, ses_data in sub_data["sessions"].items():
        # Patch fieldmap magnitude JSONs
        for fmap in ses_data["fmap_mag"]:
            nii_path = bids_root / fmap["file"]
            json_path = nii_path.parent / nii_path.name.replace(".nii.gz", ".json")

            existing = {}
            if json_path.exists():
                with open(json_path) as f:
                    existing = json.load(f)

            needs_write = False
            if "SeriesNumber" not in existing:
                existing["SeriesNumber"] = fmap["series_number"]
                needs_write = True

            if needs_write:
                with open(json_path, "w") as f:
                    json.dump(existing, f, indent=4)
                    f.write("\n")
                patched += 1

        # Patch fieldmap phase/phasediff JSONs
        for fmap in ses_data["fmap_phase"]:
            nii_path = bids_root / fmap["file"]
            json_path = nii_path.parent / nii_path.name.replace(".nii.gz", ".json")

            existing = {}
            if json_path.exists():
                with open(json_path) as f:
                    existing = json.load(f)

            needs_write = False
            if "SeriesNumber" not in existing:
                existing["SeriesNumber"] = fmap["series_number"]
                needs_write = True
            if "EchoTimeDifference" not in existing:
                existing["EchoTimeDifference"] = echo_time_diff
                needs_write = True
            # Only write Manufacturer when detection actually determined it.
            # A blanket GE default silently mislabels Siemens/Philips data and
            # sends it down the wrong fieldmap path; leave it absent so
            # detect_regime warns instead.
            if manufacturer and "Manufacturer" not in existing:
                existing["Manufacturer"] = manufacturer
                needs_write = True

            if needs_write:
                with open(json_path, "w") as f:
                    json.dump(existing, f, indent=4)
                    f.write("\n")
                patched += 1

        # Patch T1w JSONs
        for anat in ses_data["anat"]:
            nii_path = bids_root / anat["file"]
            json_path = nii_path.parent / nii_path.name.replace(".nii.gz", ".json")

            existing = {}
            if json_path.exists():
                with open(json_path) as f:
                    existing = json.load(f)

            needs_write = False
            if "SeriesNumber" not in existing:
                existing["SeriesNumber"] = anat["series_number"]
                needs_write = True

            if needs_write:
                with open(json_path, "w") as f:
                    json.dump(existing, f, indent=4)
                    f.write("\n")
                patched += 1

    return patched


# ---------------------------------------------------------------------------
# Generate scanlist CSV
# ---------------------------------------------------------------------------

SCANLIST_COLUMNS = [
    "SUBJID", "SESSION_ID", "Analyze", "BLD", "TYPE", "ANAT",
    "FMAP_MAG", "FMAP_PHASE", "FMAP_AP", "FMAP_PA",
    "T2", "T2_SESSION_ID",
]


def session_fieldmap_type(ses_data: dict) -> str:
    """Return the fieldmap regime (preptool vocabulary) for a single session.

    Prefers the per-session value written by bids_discover.py; falls back to the
    session's detection block for manifests generated before that field existed.
    """
    ft = ses_data.get("fieldmap_type")
    if ft:
        return ft
    return (ses_data.get("detection") or {}).get("preptool") or "none"


def session_has_fieldmap(ses_data: dict) -> bool:
    """Whether THIS session has a usable fieldmap for its own regime."""
    fmap_type = session_fieldmap_type(ses_data)
    if fmap_type == "topup":
        return bool(ses_data.get("fmap_ap") and ses_data.get("fmap_pa"))
    if fmap_type in ("fsl_prepare_fieldmap", "direct"):
        return bool(ses_data.get("fmap_mag") and ses_data.get("fmap_phase"))
    return False


def bold_runs_without_fieldmap(sub_data: dict) -> list[tuple[str, dict]]:
    """List (session_label, bold) for BOLD runs whose own session lacks a fmap."""
    missing = []
    for ses_label in sorted(sub_data["sessions"].keys()):
        ses_data = sub_data["sessions"][ses_label]
        if session_has_fieldmap(ses_data):
            continue
        for bold in ses_data.get("bold", []):
            missing.append((ses_label, bold))
    return missing


def generate_scanlist_csv(
    sub_data: dict,
    output_path: Path,
    allow_no_fieldmap: bool = False,
) -> None:
    """Write scanlist_{sub}.csv for one subject, routed by fieldmap regime."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sub_label = sub_data["sub_label"]
    t1_sel = sub_data["t1_selection"]
    sessions = sub_data["sessions"]

    # Broadcast the selected T1's series number across every session so BOLD
    # runs in sessions that lack their own anat still reference the chosen T1
    # (fixes ANAT=0 for multi-session subjects with a single structural scan).
    t1_sn = t1_sel["series_number"] if t1_sel else 0

    rows = []

    def _row(**kw):
        base = {c: 0 for c in SCANLIST_COLUMNS}
        base.update(SUBJID=sub_label)
        base.update(kw)
        return base

    for ses_label in sorted(sessions.keys()):
        ses_data = sessions[ses_label]
        bolds = ses_data["bold"]
        anats = ses_data["anat"]

        fmaps_mag = ses_data["fmap_mag"]
        fmaps_phase = ses_data["fmap_phase"]
        fmaps_ap = ses_data.get("fmap_ap", [])
        fmaps_pa = ses_data.get("fmap_pa", [])

        fmap_mag_sn = fmaps_mag[0]["series_number"] if fmaps_mag else 0
        fmap_phase_sn = fmaps_phase[0]["series_number"] if fmaps_phase else 0
        fmap_ap_sn = fmaps_ap[0]["series_number"] if fmaps_ap else 0
        fmap_pa_sn = fmaps_pa[0]["series_number"] if fmaps_pa else 0

        # Fieldmap availability and routing are PER SESSION — never inherit
        # another session's regime. A session with its own phasediff emits
        # FMAP_MAG/FMAP_PHASE; a topup session emits FMAP_AP/FMAP_PA; a session
        # with no usable fieldmap is handled by the gate below.
        has_fmap = session_has_fieldmap(ses_data)

        # A BOLD run is analyzed only if THIS session has a usable fieldmap.
        # Never silently deselect: generate_all() already blocked with a non-zero
        # exit unless --allow-no-fieldmap was passed. Under that flag we still
        # deselect fmap-less runs (Analyze=0) but emit a per-run WARNING below.
        analyze_bold = 1 if has_fmap else 0

        # ANAT rows
        for anat in anats:
            is_selected = (t1_sel and t1_sel["session"] == ses_label
                           and anat["run"] == t1_sel["run"])
            rows.append(_row(
                SESSION_ID=ses_label,
                Analyze=1 if is_selected else 0,
                TYPE="ANAT",
                ANAT=anat["series_number"],
            ))

        # BOLD rows
        for bold in bolds:
            if not has_fmap and allow_no_fieldmap:
                log.warning(
                    "sub-%s/ses-%s %s run-%s: no usable fieldmap — "
                    "deselected (Analyze=0) under --allow-no-fieldmap",
                    sub_label, ses_label, bold["task"], bold["run"],
                )
            rows.append(_row(
                SESSION_ID=ses_label,
                Analyze=analyze_bold,
                BLD=bold["series_number"],
                TYPE=bold["task"].upper(),
                ANAT=t1_sn,
                FMAP_MAG=fmap_mag_sn,
                FMAP_PHASE=fmap_phase_sn,
                FMAP_AP=fmap_ap_sn,
                FMAP_PA=fmap_pa_sn,
            ))

        # FMAP row — one per session that has a usable fieldmap for the regime.
        if has_fmap:
            rows.append(_row(
                SESSION_ID=ses_label,
                Analyze=1,
                TYPE="FMAP",
                FMAP_MAG=fmap_mag_sn,
                FMAP_PHASE=fmap_phase_sn,
                FMAP_AP=fmap_ap_sn,
                FMAP_PA=fmap_pa_sn,
            ))

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SCANLIST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    log.info("  Written: %s (%d rows)", output_path, len(rows))


# ---------------------------------------------------------------------------
# Generate subject config (.cfg)
# ---------------------------------------------------------------------------

CFG_TEMPLATE = """\
[iproc]
SUB={sub}
BASEDIR={basedir}
OUTDIR=${{basedir}}/mri_data
LOGDIR=${{outdir}}/${{sub}}/logs
SCRATCHDIR=${{basedir}}/scratch/
MASKSDIR=${{iproc:codedir}}/mni_masks
FONT=DejaVu-Sans
CODEDIR={codedir}

[template]
MIDVOL_SESS={midvol_sess}
MIDVOL_BOLDNO={midvol_boldno:03d}
MIDVOL_VOLNO={midvol_volno}
FD_THRESH=0.4
FD_LABEL=0p4

[fmap]
# fsl_prepare_fieldmap for double-echo gradient fieldmaps
# topup for opposite-encoded spin echo fieldmaps
PREPTOOL={fmap_type}

[csv]
TASKTYPELIST=${{iproc:basedir}}/configs/tasktype_consolidated.csv
SCANLIST=${{iproc:outdir}}/${{iproc:sub}}/subject_lists/scanlist_${{iproc:sub}}.csv
CLUSTER_REQUESTS=${{iproc:basedir}}/configs/cluster_requests.csv

[fs]
# FreeSurfer subjects directory
SUBJECTS_DIR=${{iproc:basedir}}/fs/${{iproc:sub}}

[T1]
T1_SESS={t1_sess}
T1_SCAN_NO={t1_scan_no:03d}

[out_atlas]
# 111 for 1mm isotropic, 222 for 2mm isotropic
# 111 recommended for surface analysis with coarse native resolution
RESOLUTION={resolution}
MNI_RESAMP={fsldir}/data/standard/MNI152_T1_{res_mm}mm.nii.gz
MNI_RESAMP_BRAIN={fsldir}/data/standard/MNI152_T1_{res_mm}mm_brain.nii.gz
MNI_RESAMP_BRAINMASK={fsldir}/data/standard/MNI152_T1_{res_mm}mm_brain_mask.nii.gz
FS6={freesurfer_home}/subjects/fsaverage6
"""


def generate_subject_config(
    sub_data: dict,
    iproc_dir: Path,
    codedir: str,
    output_path: Path,
    resolution: int,
    fsldir: str,
    freesurfer_home: str,
) -> None:
    """Write {sub}.cfg for one subject."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    sub_label = sub_data["sub_label"]
    t1_sel = sub_data["t1_selection"]
    midvol = sub_data["midvol"]
    fmap_type = sub_data["fieldmap_type"]

    res_mm = 1 if resolution == 111 else 2

    cfg = CFG_TEMPLATE.format(
        sub=sub_label,
        basedir=str(iproc_dir),
        codedir=codedir,
        midvol_sess=midvol["session"] if midvol else "UNKNOWN",
        midvol_boldno=midvol["bold_series_number"] if midvol else 0,
        midvol_volno=midvol["volume"] if midvol else 100,
        fmap_type=fmap_type,
        t1_sess=t1_sel["session"] if t1_sel else "UNKNOWN",
        t1_scan_no=t1_sel["series_number"] if t1_sel else 0,
        resolution=resolution,
        res_mm=res_mm,
        fsldir=fsldir,
        freesurfer_home=freesurfer_home,
    )

    with open(output_path, "w") as f:
        f.write(cfg)

    log.info("  Written: %s", output_path)


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def generate_all(
    manifest: dict,
    iproc_dir: Path,
    codedir: str,
    fsldir: str,
    freesurfer_home: str,
    manufacturer: str | None = None,
    force: bool = False,
    allow_no_fieldmap: bool = False,
) -> None:
    """Generate all iProc config files from the manifest."""
    iproc_dir = iproc_dir.resolve()
    resolution = manifest["study"]["resolution"]
    echo_time_diff = manifest["study"].get("echo_time_diff", 0.002272)
    bids_root = Path(manifest["study"]["bids_root"])

    # --- Safety gates (before writing anything) ---
    # 1. Refuse low-confidence auto-detections unless the user forces it.
    low_conf = sorted(
        name for name, sd in manifest["subjects"].items()
        if sd.get("fieldmap_confidence") == "low"
    )
    if low_conf and not force:
        log.error(
            "Low-confidence fieldmap detection for subject(s): %s",
            ", ".join(low_conf),
        )
        log.error("Review the manifest 'detections' section, then re-run with "
                  "--force to proceed anyway.")
        sys.exit(2)

    # 2. Refuse to silently deselect BOLD runs when their OWN session has no
    #    usable fieldmap. This is per session (per BOLD run), NOT the subject-
    #    wide rollup: a subject where one session has a fieldmap but another
    #    session's BOLD runs do not must still block here — otherwise those runs
    #    would be silently set to Analyze=0.
    missing = []  # (subject, session, bold)
    for name, sd in sorted(manifest["subjects"].items()):
        for ses_label, bold in bold_runs_without_fieldmap(sd):
            missing.append((name, ses_label, bold))
    if missing and not allow_no_fieldmap:
        log.error("BOLD run(s) have no usable fieldmap in their own session:")
        for name, ses_label, bold in missing:
            log.error(
                "  sub-%s/ses-%s %s run-%s",
                name, ses_label, bold["task"], bold["run"],
            )
        log.error("Re-run with --allow-no-fieldmap to deselect these runs "
                  "(they will be written with Analyze=0).")
        sys.exit(3)

    # 1. tasktype_consolidated.csv
    log.info("=== Generating tasktype_consolidated.csv ===")
    generate_tasktype_csv(
        manifest["tasks"],
        iproc_dir / "configs" / "tasktype_consolidated.csv",
    )

    # 1b. Copy cluster_requests.csv from iProc code repo if not already present
    cluster_req_dst = iproc_dir / "configs" / "cluster_requests.csv"
    if not cluster_req_dst.exists():
        cluster_req_src = Path(codedir) / "configs" / "cluster_requests.csv"
        if cluster_req_src.exists():
            import shutil
            shutil.copy2(cluster_req_src, cluster_req_dst)
            log.info("  Copied: %s", cluster_req_dst)
        else:
            log.warning("  cluster_requests.csv not found at %s — iProc will fail without it", cluster_req_src)

    # 2. Per-subject files
    for sub_name, sub_data in sorted(manifest["subjects"].items()):
        sub_label = sub_data["sub_label"]
        log.info("=== Generating config for %s ===", sub_name)

        # 2a. Patch JSON sidecars in the BIDS directory
        n_patched = patch_json_sidecars(bids_root, sub_data, echo_time_diff, manufacturer)
        if n_patched:
            log.info("  Patched %d JSON sidecar(s) in BIDS directory", n_patched)

        sub_lists_dir = iproc_dir / "mri_data" / sub_label / "subject_lists"

        # 2b. Scanlist CSV
        generate_scanlist_csv(
            sub_data,
            sub_lists_dir / f"scanlist_{sub_label}.csv",
            allow_no_fieldmap=allow_no_fieldmap,
        )

        # 2c. Subject config
        generate_subject_config(
            sub_data,
            iproc_dir,
            codedir,
            sub_lists_dir / f"{sub_label}.cfg",
            resolution=resolution,
            fsldir=fsldir,
            freesurfer_home=freesurfer_home,
        )

    log.info("")
    log.info("=== Generation complete ===")
    log.info("Next steps:")
    log.info("  1. Review generated files in %s/mri_data/", iproc_dir)
    log.info("  2. Run iProc setup stage for each subject:")
    log.info("     iProc.py -c <config.cfg> -s setup --bids /path/to/bids/sub-XXX --executor local")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate iProc configs from a BIDS manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path, help="Path to manifest.yaml from bids_discover.py")
    parser.add_argument("--iproc-dir", type=Path, required=True,
                        help="Path to iProc output/derivatives directory")
    parser.add_argument("--codedir", type=str, default=None,
                        help="Path to iProc code directory (default: $SCRATCH/iProc or same as --iproc-dir)")
    parser.add_argument("--fsldir", type=str, default="/opt/fsl-5.0.10",
                        help="FSLDIR path (default: /opt/fsl-5.0.10 for container)")
    parser.add_argument("--freesurfer-home", type=str, default="/opt/freesurfer-6.0.0",
                        help="FREESURFER_HOME path (default: /opt/freesurfer-6.0.0 for container)")
    parser.add_argument("--manufacturer", type=str, default=None,
                        help="Force a scanner Manufacturer into patched fieldmap "
                             "JSON sidecars (default: none — let detect_regime read "
                             "and warn instead of writing a wrong default)")
    parser.add_argument("--force", action="store_true",
                        help="Proceed even if any subject has a low-confidence "
                             "fieldmap detection")
    parser.add_argument("--allow-no-fieldmap", action="store_true",
                        help="Deselect (Analyze=0) BOLD runs whose own session has "
                             "no usable fieldmap, emitting a per-run warning, "
                             "instead of erroring out")

    args = parser.parse_args()

    if not args.manifest.exists():
        log.error("Manifest not found: %s", args.manifest)
        sys.exit(1)

    codedir = args.codedir or str(Path(__file__).parent.parent.resolve())

    with open(args.manifest) as f:
        manifest = yaml.safe_load(f)

    generate_all(
        manifest,
        args.iproc_dir,
        codedir=codedir,
        fsldir=args.fsldir,
        freesurfer_home=args.freesurfer_home,
        manufacturer=args.manufacturer,
        force=args.force,
        allow_no_fieldmap=args.allow_no_fieldmap,
    )


if __name__ == "__main__":
    main()
