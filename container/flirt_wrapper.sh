#!/bin/bash
# Wrapper around FSL flirt that post-processes any -omat output written in
# C99 hex-float format (0x1.abcdp+0) into canonical decimal that the rest of
# FSL can parse.  Without this, downstream fnirt / convertwarp / convert_xfm
# / applywarp parse the hex floats as 0.0, producing all-zero matrices and
# NEWMAT::SingularException.
#
# Baked into the image at build time (see iproc.def %post "Activate hex-float
# wrappers"): the real binary is moved to /opt/.fsl_orig/flirt and this script
# is installed in its place, so the fix is ALWAYS active — no runtime
# bind-mount required.  It is a safe no-op when FSL already emits decimal
# matrices: only tokens that are *actually* C99 hex-float (contain both an
# 0x/0X prefix AND a p/P binary exponent) are converted; every other byte is
# left untouched, so decimal matrices pass through unchanged.

set -u

"/opt/.fsl_orig/flirt" "$@"
ret=$?

# If the real binary failed, do NOT touch the matrix — preserve its exit code
# and leave any (possibly partial/garbage) output exactly as flirt left it.
if [ "$ret" -ne 0 ]; then
    exit "$ret"
fi

# Find any -omat argument and convert its target file to decimal (only if it
# is genuinely hex-float; decimal files are left byte-for-byte unchanged).
prev=""
for arg in "$@"; do
    if [ "$prev" = "-omat" ] && [ -n "$arg" ] && [ -f "$arg" ]; then
        python3 - "$arg" <<'PY'
import sys

fn = sys.argv[1]


def is_c99_hexfloat(tok):
    # A C99 hex-float literal has BOTH an 0x/0X prefix and a p/P binary
    # exponent (e.g. 0x1.abcdp+0).  A decimal like 0.998765 has neither, so
    # float.fromhex() must never be applied to it (float.fromhex('0.998765')
    # succeeds as a *hex* mantissa and would silently corrupt the value).
    low = tok.lower()
    return "0x" in low and "p" in low


try:
    with open(fn) as f:
        lines = f.readlines()
except OSError:
    sys.exit(0)

if not any(is_c99_hexfloat(t) for line in lines for t in line.split()):
    # Already decimal (or empty) — leave the file byte-for-byte untouched.
    sys.exit(0)

out = []
for line in lines:
    toks = line.split()
    if not toks:
        out.append(line)
        continue
    # repr(float(...)) round-trips the full double precision (unlike %.10f).
    conv = [repr(float.fromhex(t)) if is_c99_hexfloat(t) else t for t in toks]
    out.append(" ".join(conv) + "\n")

with open(fn, "w") as f:
    f.writelines(out)
PY
    fi
    prev="$arg"
done

exit "$ret"
