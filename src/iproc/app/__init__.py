"""iProc BIDS-App interface layer.

Additive package: the standard BIDS-App CLI/config surface (nipreps-style,
modeled on MRIQC/fMRIPrep), independent of the vendored per-subject
`iproc.config.Config`/science/bids_setup/container/launch machinery.

Tier-2 status: T6 provides the config-as-module singleton (`iproc.app.config`).
T7 (CLI) and T8 (derivatives output) build on top of it.
"""
