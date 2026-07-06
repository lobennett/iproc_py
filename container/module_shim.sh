#!/bin/bash
# module_shim.sh — Drop-in replacement for Lmod's `module` command inside
# the iProc Apptainer container.  Handles only `module load fsl/<version>*`
# patterns, which is all iProc needs.  Every other module command is a no-op.
#
# Delivery: this file defines `module` and does `export -f module` (see
# bottom). The EXPORTED FUNCTION is the mechanism that makes `module`
# available inside iProc's subprocess(shell=True) -> `/bin/sh -c "module load
# fsl/X && cmd"` calls: a parent `bash` that sources this shim exports the
# function into the environment, and child shells (/bin/sh is bash in this
# image) import it. This does NOT work via BASH_ENV — bash invoked as `sh`
# non-interactively does not read BASH_ENV. It is also placed in
# /etc/profile.d/ and referenced by BASH_ENV for interactive and non-interactive
# `bash -c` convenience, but shell=True delivery is the exported function only.
# Therefore a bare `apptainer exec CONTAINER <python>` with no parent bash that
# sourced this shim is unsupported (module would be undefined).

module() {
    local action="$1"
    shift

    if [[ "$action" != "load" ]]; then
        return 0
    fi

    local spec="$1"

    case "$spec" in
        fsl/4.0.3*)
            export FSLDIR=/opt/fsl-4.0.3
            ;;
        fsl/5.0.4*)
            export FSLDIR=/opt/fsl-5.0.4
            ;;
        fsl/5.0.10*)
            export FSLDIR=/opt/fsl-5.0.10
            ;;
        fsl/6.0.1*)
            export FSLDIR=/opt/fsl-6.0.1
            ;;
        *)
            # Unrecognized spec: unlike real Lmod this shim can't load it, so
            # surface it in logs instead of silently continuing under whatever
            # FSL is currently active (a typo'd version would otherwise run the
            # wrong FSL with no trace).
            echo "WARNING: module_shim: unrecognized module '$spec', leaving FSLDIR unchanged" >&2
            return 0
            ;;
    esac

    # Update PATH: remove any existing FSL bin dirs, prepend the new one
    local new_path=""
    local IFS_OLD="$IFS"
    IFS=":"
    for p in $PATH; do
        case "$p" in
            /opt/fsl-*/bin) ;;  # skip old FSL entries
            *) new_path="${new_path:+${new_path}:}${p}" ;;
        esac
    done
    IFS="$IFS_OLD"
    export PATH="${FSLDIR}/bin:${new_path}"

    # Source FSL setup if it exists
    if [[ -f "${FSLDIR}/etc/fslconf/fsl.sh" ]]; then
        source "${FSLDIR}/etc/fslconf/fsl.sh"
    fi
}

export -f module
