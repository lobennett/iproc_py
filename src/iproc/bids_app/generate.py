"""generate — Generate iProc configuration files from a BIDS manifest.

Usage:
    bids_generate manifest.yaml \
        --iproc-dir /path/to/derivatives/iproc \
        --codedir /path/to/iProc

Reads the manifest produced by discover and generates:
  1. configs/tasktype_consolidated.csv
  2. mri_data/{sub}/subject_lists/scanlist_{sub}.csv  (per subject)
  3. mri_data/{sub}/subject_lists/{sub}.cfg            (per subject)
  4. Patched JSON sidecars for fieldmaps and T1w missing metadata

The manifest should be reviewed/edited before running this.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

import yaml

from iproc.bids_app import _num_key

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Braga mode constants and resolver
# ---------------------------------------------------------------------------

FS6_HOME = "/opt/freesurfer-6.0.0"
FS7_HOME = "/opt/freesurfer-7.1.1"

# Non-braga defaults reproduce upstream harvard-nrg behavior.
NONBRAGA_DEFAULTS = {
    "resolution": None,          # None -> use manifest["study"]["resolution"]
    "brain_extract": "bet",
    "fs_version": 6,
    "native_surface": False,
    "slice_timing": False,
    "nordic": False,
    "marss": False,
    "mbfactor": 1,
}
# --braga preset = a DEFAULT Braga run. NORDIC/MARSS/slice-timing are opt-in
# even in Braga, so they stay False here.
BRAGA_DEFAULTS = {
    "resolution": 111,
    "brain_extract": "synthstrip",
    "fs_version": 7,
    "native_surface": True,
    "slice_timing": False,
    "nordic": False,
    "marss": False,
    "mbfactor": 1,
}


def resolve_braga_options(args) -> dict:
    """Resolve --braga preset + granular flag overrides into final option
    values. Precedence: an explicitly-passed granular flag beats the preset.
    Granular flags default to None in argparse so 'not passed' is detectable.
    """
    braga = bool(getattr(args, "braga", False))
    base = dict(BRAGA_DEFAULTS if braga else NONBRAGA_DEFAULTS)

    for key in NONBRAGA_DEFAULTS:
        val = getattr(args, key, None)
        if val is not None:
            base[key] = val

    # freesurfer_home: explicit flag wins; else derive from fs_version.
    if getattr(args, "freesurfer_home", None) is not None:
        base["freesurfer_home"] = args.freesurfer_home
    else:
        base["freesurfer_home"] = FS7_HOME if base["fs_version"] == 7 else FS6_HOME

    base["braga_mode"] = braga
    return base


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

_SKIP_SIDECAR = object()  # sentinel: sidecar exists but is unreadable/malformed


def _load_sidecar(json_path: Path):
    """Load an existing JSON sidecar.

    Returns ``{}`` if the sidecar doesn't exist yet (nothing to preserve).
    Returns the sentinel ``_SKIP_SIDECAR`` if the sidecar exists but is not
    valid JSON (or can't be read) — the caller must skip patching THAT one
    sidecar rather than let a single corrupt file abort the whole generation
    run partway through (after some other files have already been written).
    """
    if not json_path.exists():
        return {}
    try:
        with open(json_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Malformed JSON sidecar, skipping patch for this file: %s (%s)",
            json_path, exc,
        )
        return _SKIP_SIDECAR


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

            existing = _load_sidecar(json_path)
            if existing is _SKIP_SIDECAR:
                continue

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

            existing = _load_sidecar(json_path)
            if existing is _SKIP_SIDECAR:
                continue

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

            existing = _load_sidecar(json_path)
            if existing is _SKIP_SIDECAR:
                continue

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

    Prefers the per-session value written by discover; falls back to the
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
    for ses_label in sorted(sub_data["sessions"].keys(), key=_num_key):
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
    average_t1: bool = False,
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

    for ses_label in sorted(sessions.keys(), key=_num_key):
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
                Analyze=1 if (is_selected or average_t1) else 0,
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
T1_AVERAGE={t1_average}

[out_atlas]
# 111 for 1mm isotropic, 222 for 2mm isotropic
# 111 recommended for surface analysis with coarse native resolution
RESOLUTION={resolution}
MNI_RESAMP={fsldir}/data/standard/MNI152_T1_{res_mm}mm.nii.gz
MNI_RESAMP_BRAIN={fsldir}/data/standard/MNI152_T1_{res_mm}mm_brain.nii.gz
MNI_RESAMP_BRAINMASK={fsldir}/data/standard/MNI152_T1_{res_mm}mm_brain_mask.nii.gz
FS6={freesurfer_home}/subjects/fsaverage6

[BRAGA]
BRAGA_MODE={braga_mode}
BRAIN_EXTRACT={brain_extract}
FS_VERSION={fs_version}
NATIVE_SURFACE={native_surface}
SLICE_TIMING={slice_timing}
NORDIC={nordic}
MARSS={marss}
MBFACTOR={mbfactor}
"""


def generate_subject_config(
    sub_data: dict,
    iproc_dir: Path,
    codedir: str,
    output_path: Path,
    resolution: int,
    fsldir: str,
    freesurfer_home: str,
    average_t1: bool = False,
    braga: dict | None = None,
) -> None:
    """Write {sub}.cfg for one subject."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    braga = braga or NONBRAGA_DEFAULTS | {"braga_mode": False, "freesurfer_home": freesurfer_home}

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
        t1_average=str(average_t1).lower(),
        braga_mode=str(braga["braga_mode"]).lower(),
        brain_extract=braga["brain_extract"],
        fs_version=braga["fs_version"],
        native_surface=str(braga["native_surface"]).lower(),
        slice_timing=str(braga["slice_timing"]).lower(),
        nordic=str(braga["nordic"]).lower(),
        marss=str(braga["marss"]).lower(),
        mbfactor=braga["mbfactor"],
    )

    with open(output_path, "w") as f:
        f.write(cfg)

    log.info("  Written: %s", output_path)


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

def subject_fieldmap_regimes(sub_data: dict) -> set[str]:
    """Distinct usable fieldmap regimes across a subject's sessions.

    Only counts sessions that actually have the files for their regime, so a
    fmap-less session does not contribute a spurious 'none'.
    """
    regimes = set()
    for ses_data in sub_data["sessions"].values():
        if session_has_fieldmap(ses_data):
            regimes.add(session_fieldmap_type(ses_data))
    return regimes


def generate_all(
    manifest: dict,
    iproc_dir: Path,
    codedir: str,
    fsldir: str,
    freesurfer_home: str,
    manufacturer: str | None = None,
    force: bool = False,
    allow_no_fieldmap: bool = False,
    allow_missing_anat: bool = False,
    average_t1: bool = False,
    braga: dict | None = None,
) -> None:
    """Generate all iProc config files from the manifest."""
    iproc_dir = iproc_dir.resolve()
    braga = braga or (NONBRAGA_DEFAULTS | {"braga_mode": False, "freesurfer_home": freesurfer_home})
    # --resolution / --braga override the manifest resolution when set.
    resolution = braga["resolution"] if braga.get("resolution") is not None else manifest["study"]["resolution"]
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

    # 1b. Refuse missing anatomy (no selected T1 or no midvol target) rather
    #     than silently emitting T1_SESS=UNKNOWN / MIDVOL_SESS=UNKNOWN, which
    #     produces a config that fails opaquely deep in iProc.
    missing_anat = []
    for name, sd in sorted(manifest["subjects"].items()):
        reasons = []
        if sd.get("t1_selection") is None:
            reasons.append("no T1w selected")
        if sd.get("midvol") is None:
            reasons.append("no midvol/BOLD target")
        if reasons:
            missing_anat.append((name, ", ".join(reasons)))
    if missing_anat and not allow_missing_anat:
        log.error("Missing anatomy for subject(s):")
        for name, reason in missing_anat:
            log.error("  sub-%s: %s", name, reason)
        log.error("Fix the manifest (t1_selection / midvol), or re-run with "
                  "--allow-missing-anat to proceed anyway.")
        sys.exit(4)

    # 1c. Refuse mixed fieldmap regimes within a subject. The cfg carries a
    #     single global PREPTOOL, so a subject whose sessions mix e.g. phasediff
    #     and topup cannot be expressed correctly. Block unless --force.
    mixed = []
    for name, sd in sorted(manifest["subjects"].items()):
        regimes = subject_fieldmap_regimes(sd)
        if len(regimes) > 1:
            mixed.append((name, sorted(regimes)))
    if mixed and not force:
        log.error("Mixed fieldmap regimes within subject(s) "
                  "(cfg has a single PREPTOOL):")
        for name, regimes in mixed:
            log.error("  sub-%s: %s", name, ", ".join(regimes))
        log.error("Split the subject or standardise the fieldmaps, or re-run "
                  "with --force to proceed anyway.")
        sys.exit(5)

    # 1d. Refuse the 'direct' fieldmap regime outright: iProc has no 'direct'
    #     preptool, so PREPTOOL=direct would be an invalid config. --force does
    #     not override this because there is no valid downstream path.
    direct_subs = sorted(
        name for name, sd in manifest["subjects"].items()
        if sd.get("fieldmap_type") == "direct"
        or "direct" in subject_fieldmap_regimes(sd)
    )
    if direct_subs:
        log.error(
            "Unsupported 'direct' fieldmap regime for subject(s): %s",
            ", ".join(direct_subs),
        )
        log.error("iProc has no 'direct' preptool (only fsl_prepare_fieldmap / "
                  "topup). Convert the fieldmap or exclude these sessions.")
        sys.exit(6)

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

    # 3. Warn loudly for any task missing a RepetitionTime, rather than writing
    #    a blank TR into tasktype_consolidated.csv where it would be missed.
    for task_name, params in sorted(manifest["tasks"].items()):
        if not params.get("tr"):
            log.warning(
                "Task '%s' has no RepetitionTime — TR will be BLANK in "
                "tasktype_consolidated.csv. Set it in the manifest before "
                "running iProc.", task_name,
            )

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
            average_t1=average_t1,
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
            average_t1=average_t1,
            braga=braga,
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

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate iProc configs from a BIDS manifest.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path, help="Path to manifest.yaml from bids_discover.py")
    parser.add_argument("--iproc-dir", type=Path, required=True,
                        help="Path to iProc output/derivatives directory")
    parser.add_argument("--codedir", type=str, default=None,
                        help="Path to iProc code directory (default: $SCRATCH/iProc or same as --iproc-dir)")
    parser.add_argument("--fsldir", type=str, default="/opt/fsl-6.0.7",
                        help="FSLDIR path (default: /opt/fsl-6.0.7 for container)")
    parser.add_argument("--freesurfer-home", type=str, default=None,
                        help="FREESURFER_HOME path (default: /opt/freesurfer-6.0.0, "
                             "or /opt/freesurfer-7.1.1 under --braga/--fs-version 7)")
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
    parser.add_argument("--allow-missing-anat", action="store_true",
                        help="Proceed even if a subject has no selected T1w or no "
                             "midvol/BOLD target (otherwise blocks instead of "
                             "emitting T1_SESS=UNKNOWN)")
    parser.add_argument("--average-t1", action="store_true",
                        help="Run FreeSurfer recon-all on the motion-corrected "
                             "average of ALL of each subject's T1w scans (sets "
                             "T1_AVERAGE=true and marks every T1w Analyze=1). "
                             "Default: single selected T1 (upstream iProc "
                             "behavior).")
    # --- Braga mode ---
    parser.add_argument("--braga", action="store_true",
                        help="Preset: process data the Braga Lab way (1.2mm "
                             "template, SynthStrip skull-strip, FreeSurfer 7, "
                             "native surface). Granular flags below override it. "
                             "Does NOT enable NORDIC/MARSS/slice-timing (opt-in).")
    parser.add_argument("--resolution", type=int, choices=[111, 222], default=None,
                        help="Individualized template resolution: 111=1.2mm, "
                             "222=2mm. Overrides the manifest value.")
    parser.add_argument("--brain-extract", choices=["bet", "synthstrip"], default=None,
                        help="Brain extraction method (default bet; braga=synthstrip)")
    parser.add_argument("--fs-version", type=int, choices=[6, 7], default=None,
                        help="FreeSurfer version for recon-all (default 6; braga=7)")
    parser.add_argument("--native-surface", action=argparse.BooleanOptionalAction,
                        default=None,
                        help="Also project to the subject's native ~40k surface "
                             "(default off; braga on). Use --no-native-surface to "
                             "disable under --braga.")
    parser.add_argument("--slice-timing", action=argparse.BooleanOptionalAction,
                        default=None, help="Slice-timing correction (opt-in)")
    parser.add_argument("--nordic", action=argparse.BooleanOptionalAction,
                        default=None, help="NORDIC denoising (opt-in)")
    parser.add_argument("--marss", action=argparse.BooleanOptionalAction,
                        default=None, help="MARSS multiband artifact removal (opt-in)")
    parser.add_argument("--mbfactor", type=int, default=None,
                        help="Multiband acceleration factor (for MARSS/NORDIC)")
    return parser


def run_generate(args: argparse.Namespace) -> None:
    """Run generation from parsed args: load manifest and emit iProc configs."""
    if not args.manifest.exists():
        log.error("Manifest not found: %s", args.manifest)
        sys.exit(1)

    codedir = args.codedir or str(Path(__file__).parent.parent.resolve())

    with open(args.manifest) as f:
        manifest = yaml.safe_load(f)

    braga = resolve_braga_options(args)

    generate_all(
        manifest,
        args.iproc_dir,
        codedir=codedir,
        fsldir=args.fsldir,
        freesurfer_home=braga["freesurfer_home"],
        manufacturer=args.manufacturer,
        force=args.force,
        allow_no_fieldmap=args.allow_no_fieldmap,
        allow_missing_anat=args.allow_missing_anat,
        average_t1=args.average_t1,
        braga=braga,
    )


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    run_generate(args)


if __name__ == "__main__":
    main()
