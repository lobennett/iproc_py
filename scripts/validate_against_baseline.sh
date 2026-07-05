#!/bin/bash
set -euo pipefail
# Phase B (Sherlock, interactive): bit-identical check vs the upstream-behavior baseline.
# The baseline = upstream core + neutral env fixes = this package with generalizations at
# upstream defaults. We compare OUR outputs against a baseline run on the SAME inputs.
# Usage: validate_against_baseline.sh <cfg> <bids> <stage>
cfg="${1:?cfg}"; bids="${2:?bids}"; stage="${3:?stage}"
here="$(cd "$(dirname "$0")" && pwd)"; repo="$(cd "$here/.." && pwd)"
NEW="${IPROC_NEW_OUT:?set IPROC_NEW_OUT}"; BASE="${IPROC_BASE_OUT:?set IPROC_BASE_OUT}"
echo "== our package (NEW) =="
iproc -c "$cfg" -s "$stage" --bids "$bids" --executor local
echo "== diff NEW vs BASELINE =="
if command -v niftidiff >/dev/null 2>&1; then
  iproc -c "$cfg" -s "$stage" --executor local --dry-run --autodiff "$NEW" "$BASE" || true
else
  find "$NEW" -name '*.nii.gz' | while read -r f; do
    b="${f/$NEW/$BASE}"; [ -f "$b" ] && python "$here/diff_tools/diff-nifti.py" "$b" "$f" || true
  done
fi
echo "Also run scripts/fork_divergence_report.sh to measure fork vs baseline (diagnostic)."
