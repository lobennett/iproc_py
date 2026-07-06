"""iProc BIDS-App configuration singleton.

Mirrors MRIQC's config-as-module pattern (nipreps/mriqc's ``config.py``),
simplified for iProc since we do not depend on nipype. The module itself
*is* the singleton: configuration lives as class attributes on a handful of
section classes, not on instances, and callers import the module rather
than constructing anything::

    from iproc.app import config

    config.execution.bids_dir = Path("/data/bids")
    config.execution.output_dir = Path("/data/out")
    config.workflow.stage = "align"

    config.to_filename("/data/out/config.json")
    ...
    config.load("/data/out/config.json")

This is entirely additive and independent of the vendored, per-subject,
configparser-based ``iproc.config.Config`` -- the two must never be
conflated. It also does not touch iProc's science, ``bids_setup``,
``container``, or ``launch`` code; T7 (CLI) and T8 (derivatives output)
build on top of this module.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from iproc.__version__ import __version__ as _IPROC_VERSION

try:
    from bids import __version__ as _PYBIDS_VERSION
except Exception:  # pragma: no cover - pybids is an optional dependency
    _PYBIDS_VERSION = None


class _Config:
    """Base class for a configuration section.

    A section is declared as a subclass with plain class-body attributes
    acting as both the schema and the defaults. Two class-level tuples
    control (de)serialization:

    - ``_paths``: attribute names holding ``pathlib.Path`` values. These are
      converted to ``str`` on export (``get``/JSON) and back to ``Path`` on
      import (``load``), since JSON has no native Path type.
    - ``_hidden``: attribute names that are runtime-only handles (e.g. a
      live pybids ``BIDSLayout``). They are never exported by ``get()`` and
      are never set by ``load()`` -- they must be assigned directly on the
      section class by calling code.

    Sections are never instantiated: settings are read/written as class
    attributes directly (``config.execution.bids_dir``, not
    ``config.execution().bids_dir``), which is what makes this a singleton.
    """

    _paths: tuple[str, ...] = ()
    _hidden: tuple[str, ...] = ()

    @classmethod
    def load(cls, settings: dict) -> None:
        """Populate this section's class attributes in place from a dict.

        Unknown keys are accepted (set as new attributes) so that forward-
        compatible config files don't hard-fail; keys named in ``_hidden``
        are always skipped, since those are runtime-only handles that must
        never be reconstructed from a settings dict.
        """
        for key, value in settings.items():
            if key in cls._hidden:
                continue
            if key in cls._paths and value is not None:
                value = Path(value)
            setattr(cls, key, value)

    @classmethod
    def get(cls) -> dict:
        """Export this section as a plain, JSON-serializable dict.

        Excludes anything hidden, anything callable (methods), and anything
        whose name starts with an underscore (internal bookkeeping such as
        ``_paths``/``_hidden`` themselves).
        """
        out: dict[str, Any] = {}
        for key, value in vars(cls).items():
            if key.startswith("_"):
                continue
            if key in cls._hidden:
                continue
            if callable(value) or isinstance(value, (classmethod, staticmethod)):
                continue
            if key in cls._paths and value is not None:
                value = str(value)
            out[key] = value
        return out


class execution(_Config):
    """Where things are and top-level run controls."""

    bids_dir: Path | None = None
    output_dir: Path | None = None
    work_dir: Path | None = None
    participant_label: list[str] = []
    log_level: int = 25
    dry_run: bool = False

    #: Runtime-only pybids BIDSLayout handle. Populated by the CLI (T7)
    #: after BIDS discovery; never read from or written to a config file.
    layout: Any = None

    _paths = ("bids_dir", "output_dir", "work_dir")
    _hidden = ("layout",)


class workflow(_Config):
    """What to run."""

    analysis_level: str = "participant"
    #: Which iProc pipeline stage to run; None means "not yet selected".
    stage: str | None = None
    resolution: str = "222"
    skip: int = 7
    smoothing: float = 6.0


class environment(_Config):
    """Read-only run-environment facts, captured once at import time.

    Never populated from a config file: ``load()`` is a deliberate no-op so
    that loading someone else's config (e.g. to resume/inspect a prior run)
    can never overwrite facts about *this* environment.
    """

    version: str = _IPROC_VERSION
    python_version: str = sys.version
    cpu_count: int = os.cpu_count() or 1
    pybids_version: str | None = _PYBIDS_VERSION

    @classmethod
    def load(cls, settings: dict) -> None:  # noqa: ARG003 - intentional no-op
        """No-op: environment facts are read-only and set at import time."""
        return


_SECTIONS: dict[str, type[_Config]] = {
    "execution": execution,
    "workflow": workflow,
    "environment": environment,
}


def to_dict() -> dict:
    """Export the full singleton config as a nested ``{section: {...}}`` dict."""
    return {name: section.get() for name, section in _SECTIONS.items()}


def from_dict(sections: dict) -> None:
    """Load each named section from a nested ``{section: {...}}`` dict.

    Unknown section names are ignored.
    """
    for name, settings in sections.items():
        section = _SECTIONS.get(name)
        if section is None:
            continue
        section.load(settings)


def dumps() -> str:
    """Serialize the full config to a JSON string.

    JSON (stdlib), not TOML: this is a purely internal, machine-written/
    machine-read run-config snapshot (analogous to MRIQC's
    ``config.toml``), not a hand-authored user-facing file, so there's no
    benefit from TOML's comments/human-editing ergonomics -- and using
    ``json`` keeps this module dependency-free.
    """
    return json.dumps(to_dict(), indent=2, sort_keys=True)


def loads(payload: str) -> None:
    """Load config sections from a JSON string produced by ``dumps()``."""
    from_dict(json.loads(payload))


def to_filename(path: str | Path) -> None:
    """Write the full config to ``path`` as JSON."""
    Path(path).write_text(dumps())


def load(path: str | Path) -> None:
    """Load config sections from a JSON file written by ``to_filename()``."""
    loads(Path(path).read_text())
