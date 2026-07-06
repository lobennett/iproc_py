"""Fieldmap regime detection for BIDS subjects.

Scientific default = upstream iProc (Siemens/Varian gradient-echo via
fsl_prepare_fieldmap). GE is a new capability upstream lacks, flagged for
verification. Detection is conservative and returns confidence + warnings.
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    value: str                       # phasediff | pepolar | direct | none
    confidence: str                  # high | low
    rationale: str
    evidence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def warn(self):
        for w in self.warnings:
            logger.warning("[fieldmap] %s", w)


@dataclass
class FieldmapPlan:
    regime: str
    preptool: str
    files: dict
    evidence: dict


def _load_json(nii: Path) -> dict:
    js = nii.with_suffix("").with_suffix(".json")
    if js.exists():
        try:
            return json.loads(js.read_text())
        except Exception as e:  # noqa: BLE001
            logger.warning("[fieldmap] bad JSON %s: %s", js, e)
    return {}


def _manufacturer(js: dict) -> str:
    m = (js.get("Manufacturer") or "").upper()
    if "SIEMENS" in m: return "SIEMENS"
    if "VARIAN" in m: return "VARIAN"
    if "GE" in m: return "GE"
    if "PHILIPS" in m: return "PHILIPS"
    return ""


def _delta_te_ms(js: dict) -> float | None:
    if "EchoTimeDifference" in js:
        return js["EchoTimeDifference"] * 1000.0
    if "EchoTime1" in js and "EchoTime2" in js:
        return abs(js["EchoTime2"] - js["EchoTime1"]) * 1000.0
    return None


def detect_regime(fmap_dir: Path, metadata_lookup=None) -> Decision:
    """Classify the fieldmap regime in ``fmap_dir``.

    ``metadata_lookup`` (optional): a callable ``path -> dict`` returning the
    sidecar metadata for a file. Pass ``layout.get_metadata`` (via a wrapper)
    so BIDS *inheritance* is resolved — many real datasets (e.g. MSC) put
    ``Manufacturer``/``EchoTime1``/``EchoTime2`` in a root-level
    ``phasediff.json``/``magnitude1.json`` and carry NO per-session sidecar.
    When not provided, falls back to reading the file's own ``.json`` sidecar
    (``_load_json``), which is correct only for datasets without inheritance.
    """
    fmap_dir = Path(fmap_dir)

    def _meta(p: Path) -> dict:
        if metadata_lookup is not None:
            try:
                return metadata_lookup(p) or {}
            except Exception as e:  # noqa: BLE001
                logger.warning("[fieldmap] metadata_lookup failed for %s: %s", p, e)
                return {}
        return _load_json(p)

    if not fmap_dir.is_dir():
        return Decision("none", "high", "no fmap/ directory present")
    files = sorted(p for p in fmap_dir.iterdir()
                   if p.name.endswith(".nii.gz") or p.name.endswith(".nii"))
    names = [p.name for p in files]
    has_phase = any(re.search(r"_phasediff\.nii", n) or re.search(r"_phase[12]?\.nii", n) for n in names)
    has_mag = any(re.search(r"_magnitude[12]?\.nii", n) for n in names)
    has_epi = any(re.search(r"_epi\.nii", n) for n in names)
    has_dir = any("dir-" in n for n in names)
    has_direct = any(re.search(r"_fieldmap\.nii", n) for n in names)

    warnings = []

    if has_epi and has_dir:
        epis = [p for p in files if "_epi.nii" in p.name]
        pe = [ _meta(p).get("PhaseEncodingDirection", "") for p in epis ]
        conf = "high" if len(set(d for d in pe if d)) >= 2 else "low"
        if conf == "low":
            warnings.append("pepolar detected but <2 distinct PhaseEncodingDirection values; VERIFY")
        d = Decision("pepolar", conf, "AP/PA _epi files present (topup)",
                     {"preptool": "topup", "pe_dirs": pe,
                      "files": [p.name for p in epis]}, warnings)
        d.warn(); return d

    if has_phase and has_mag:
        phase = next(p for p in files if "phase" in p.name)
        js = _meta(phase)
        # Siemens gre fieldmaps split the two echo times across the phase and
        # magnitude sidecars; merge the magnitude metadata so delta_te resolves.
        mag = next((p for p in files if re.search(r"_magnitude[12]?\.nii", p.name)), None)
        if mag is not None:
            mjs = _meta(mag)
            for k in ("Manufacturer", "EchoTime1", "EchoTime2", "EchoTimeDifference"):
                if k not in js and k in mjs:
                    js[k] = mjs[k]
        mfr = _manufacturer(js)
        dte = _delta_te_ms(js)
        ge = mfr in ("GE", "PHILIPS")
        conf = "high"
        if not mfr:
            conf = "low"; warnings.append("phasediff: Manufacturer missing in JSON; defaulting to SIEMENS — VERIFY")
            mfr = "SIEMENS"
        if dte is None:
            conf = "low"; warnings.append("phasediff: EchoTimeDifference/EchoTime1&2 missing; VERIFY")
        if ge:
            warnings.append(f"GE/Philips fieldmap (manufacturer={mfr}): using Hz→rad/s conversion (new capability, not upstream) — VERIFY results")
        d = Decision("phasediff", conf, "magnitude + phase(diff) present (fsl_prepare_fieldmap)",
                     {"preptool": "fsl_prepare_fieldmap", "manufacturer": mfr,
                      "delta_te_ms": dte, "ge_special": ge}, warnings)
        d.warn(); return d

    if has_direct:
        d = Decision("direct", "low", "_fieldmap present; direct-fieldmap path",
                     {"preptool": "direct"}, ["direct-fieldmap path is uncommon; VERIFY"])
        d.warn(); return d

    d = Decision("none", "high" if not files else "low",
                 "no recognizable fieldmap files",
                 {"files": names},
                 [] if not files else ["fmap/ has files but no recognized regime; VERIFY"])
    d.warn(); return d


def plan_fieldmaps(subject_dir: Path) -> list[FieldmapPlan]:
    subject_dir = Path(subject_dir)
    fmap_dirs = sorted(subject_dir.glob("ses-*/fmap")) or (
        [subject_dir / "fmap"] if (subject_dir / "fmap").is_dir() else [])
    plans = []
    for fd in fmap_dirs:
        d = detect_regime(fd)
        if d.value == "none":
            continue
        plans.append(FieldmapPlan(d.value, d.evidence.get("preptool", ""),
                                  {"dir": str(fd)}, d.evidence))
    return plans
