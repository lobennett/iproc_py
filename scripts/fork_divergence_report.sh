#!/bin/bash
set -euo pipefail
# Dry-run our package vs the fork for the SAME config; report differing commands.
#
# Our core is "upstream + neutral fixes" (see NOTICE.md), so the dry-run
# command set produced by this repo's `iproc` IS the upstream-behavior
# baseline (see tests/test_golden_commands.py). Any lines that only appear
# in the fork's dry-run output represent the fork's own scientific/
# behavioral deviations from that baseline.
#
# Usage: fork_divergence_report.sh <config.cfg> <bids_dir> <stage>
cfg="${1:?cfg}"; bids="${2:?bids}"; stage="${3:?stage}"
here="$(cd "$(dirname "$0")" && pwd)"; repo="$(cd "$here/.." && pwd)"

ours=$(iproc -c "$cfg" -s "$stage" --executor local --dry-run --bids "$bids" 2>&1 | grep runscript || true)
fork=$(cd "$repo/third_party/iProc-fork" && python iProc.py -c "$cfg" -s "$stage" \
        --executor local --dry-run --bids "$bids" 2>&1 | grep runscript || true)

echo "=== commands only in FORK (fork's scientific/behavioral deviations) ==="
diff <(echo "$ours") <(echo "$fork") || true
