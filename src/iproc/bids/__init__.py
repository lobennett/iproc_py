import re
import os
import glob
import logging
import json
import subprocess as sp
import collections as col
import iproc.commons as commons
logger = logging.getLogger(__name__)


# DEVIATION FROM UPSTREAM (documented in docs/fork-audit.md / NOTICE.md).
# Upstream's match_scan_no_to_bids matched scanlist rows to BIDS files by
# globbing per-run JSON sidecars and reading their `SeriesNumber`. That fails
# on datasets that use BIDS *inheritance* — no per-run sidecars, metadata in
# root-level task-*_bold.json / phasediff.json (e.g. MSC, many OpenNeuro
# datasets, and read-only trees where sidecars can't be patched in). This
# rewrite uses pybids: it enumerates BOLD/anat/fmap NIfTIs and their BIDS
# entities (inheritance-resolved), and maps each scanlist row to a BIDS `run`
# by (session, task, order) rather than by SeriesNumber. `run` is the canonical
# BIDS identifier, so for datasets that DO carry sidecars this produces the same
# BIDS_ID the SeriesNumber path did. Also handles cross-session anat (T1 in a
# different session than BOLD/fmap): each modality is resolved from its own
# session, and per-session modality handling is conditional (a session missing
# a modality is skipped, not an error).


def _get_layout(bids_base):
    """Build a BIDSLayout from the dataset root and return (layout, sub_label).

    `bids_base` is the SUBJECT directory (e.g. .../ds000224/sub-MSC01); pybids
    needs the dataset root (its parent, which holds dataset_description.json and
    the inherited root-level sidecars).
    """
    try:
        from bids import BIDSLayout
    except ImportError as e:  # pragma: no cover - env-dependent
        raise ImportError(
            "pybids is required for BIDS ingestion (`match_scan_no_to_bids`). "
            "Install the 'bids' extra (pip install -e '.[bids]') or run inside "
            "the container, which provides it."
        ) from e
    base = os.path.normpath(bids_base)
    root = os.path.dirname(base)
    sub = os.path.basename(base)
    if sub.startswith("sub-"):
        sub = sub[4:]
    return BIDSLayout(root, validate=False), sub


def _run_str(fpath):
    """Raw, zero-padding-preserving BIDS run token from the filename (e.g.
    '01', '001'), or None if the file carries no run entity. Downstream
    steps.py globs `_run-{BIDS_ID}_`, so the exact padding must be preserved
    (pybids' parsed run int would drop it)."""
    m = re.search(r'_run-([0-9]+)', os.path.basename(fpath))
    return m.group(1) if m else None


def _run_sortkey(fpath):
    s = _run_str(fpath)
    return int(s) if s is not None else 1


def match_scan_no_to_bids(bids_base, scans):
    """Populate BIDS_ID (BIDS run) on bold/anat scans and the fmap NIfTI paths
    on fmap scans, via pybids. Contract consumed by steps.py:
      bold_scan['BIDS_ID'] = <run>, bold_scan['FMAP_DIR'] = 'FMAP'
      anat_scan['BIDS_ID'] = <run>
      fmap_scan['FIRST_BIDS_FNAME'] = magnitude NIfTI(s) (or AP epi for topup)
      fmap_scan['SECOND_BIDS_FNAME'] = phasediff NIfTI (or PA epi for topup)
      fmap_scan['DIR'] = 'FMAP'
    """
    layout, sub = _get_layout(bids_base)

    for sessionid, sess in scans.scan_by_session.items():
        bids_ses = sanitize(sessionid)

        # --- BOLD: map scanlist rows -> BIDS runs by (task, order) ---
        if sess.bold_scans:
            rows_by_task = col.defaultdict(list)
            for bs in sess.bold_scans.values():
                rows_by_task[bs['TYPE'].upper()].append(bs)

            bolds = layout.get(subject=sub, session=bids_ses, suffix='bold',
                               extension=['.nii', '.nii.gz'], return_type='file')
            runs_by_task = col.defaultdict(set)
            for f in bolds:
                ent = layout.parse_file_entities(f)
                task = (ent.get('task') or '').upper()
                rs = _run_str(f)
                if rs is not None:
                    runs_by_task[task].add(rs)

            for task_up, rows in rows_by_task.items():
                rows = sorted(rows, key=lambda s: int(s['BLD']))
                runs = sorted(runs_by_task.get(task_up, ()), key=int)
                if len(runs) != len(rows):
                    logger.warning(
                        "[bids] %s/ses-%s task=%s: %d scanlist row(s) vs %d BIDS "
                        "run(s); pairing in order", sub, bids_ses, task_up,
                        len(rows), len(runs))
                for bs, run in zip(rows, runs):
                    bs['BIDS_ID'] = str(run)
                    bs['FMAP_DIR'] = 'FMAP'
                if len(rows) > len(runs):
                    leftover = rows[len(runs):]
                    raise IOError(
                        f"no BIDS bold run for scanlist row(s) task={task_up} "
                        f"BLD={[r['BLD'] for r in leftover]} in ses-{bids_ses} "
                        f"(sub-{sub}); found runs {runs}")

        # --- ANAT: resolve from THIS session's own anat (cross-session-safe) ---
        if sess.anat_scans:
            anats = layout.get(subject=sub, session=bids_ses,
                               suffix=['T1w', 'T2w'],
                               extension=['.nii', '.nii.gz'], return_type='file')
            anats = sorted(anats, key=_run_sortkey)
            if not anats:
                raise IOError(
                    f"no BIDS T1w/T2w found in ses-{bids_ses} for sub-{sub}")
            arows = sorted(sess.anat_scans.values(), key=lambda s: int(s['ANAT']))
            for a, f in zip(arows, anats):
                a['BIDS_ID'] = _run_str(f) or "1"
            # more scanlist anat rows than files: reuse the last (defensive)
            for a in arows[len(anats):]:
                a['BIDS_ID'] = _run_str(anats[-1]) or "1"

        # --- FMAP ---
        if sess.fmap_scans:
            mags = sorted(layout.get(
                subject=sub, session=bids_ses,
                suffix=['magnitude1', 'magnitude2', 'magnitude'],
                extension=['.nii', '.nii.gz'], return_type='file'))
            phase = layout.get(
                subject=sub, session=bids_ses,
                suffix=['phasediff', 'phase1', 'phase2'],
                extension=['.nii', '.nii.gz'], return_type='file')
            epis = layout.get(subject=sub, session=bids_ses, suffix='epi',
                              extension=['.nii', '.nii.gz'], return_type='file')

            for fm in sess.fmap_scans.values():
                if phase:  # phasediff / gradient-echo regime
                    if not mags:
                        raise IOError(
                            f"phasediff fmap but no magnitude in ses-{bids_ses} "
                            f"(sub-{sub})")
                    fm['FIRST_BIDS_FNAME'] = mags if len(mags) != 1 else mags[0]
                    fm['SECOND_BIDS_FNAME'] = phase[0]
                elif epis:  # pepolar / topup regime
                    def _pe(e):
                        ent = layout.parse_file_entities(e)
                        return (ent.get('direction') or '')
                    ap = sorted(e for e in epis if _pe(e).upper().startswith('AP')
                                or 'dir-AP' in e)
                    pa = sorted(e for e in epis if e not in ap)
                    fm['FIRST_BIDS_FNAME'] = (ap if len(ap) != 1 else ap[0]) if ap else None
                    fm['SECOND_BIDS_FNAME'] = (pa if len(pa) != 1 else pa[0]) if pa else None
                else:
                    raise IOError(
                        f"no recognizable fieldmap files in ses-{bids_ses} "
                        f"(sub-{sub})")
                fm['DIR'] = 'FMAP'


def get_json_entity(json, entity):
    return str(commons.get_json_entity(json, entity))


class SplitTaskError(Exception):
    pass


def sanitize(s):
    regex = re.compile('[^a-zA-Z0-9]')
    return regex.sub('', s)


def split_task(s):
    regex = re.compile('([a-zA-Z]+)_?(\d+)?')
    match = regex.match(s)
    if not match:
        raise SplitTaskError(f'failed to split task "{s}"')
    task, run = match.groups('1')
    return task, run
