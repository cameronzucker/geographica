#!/bin/bash
# dev/harness/wizard-matrix.sh — end-to-end wizard harness, one full run per pre-state.
#
# Pairs with `bootstrap-matrix.sh` (apt-level, Docker-based, ~10 min) but
# goes further: each run actually launches the wizard in an LXD container
# and walks Playwright through Steps 1-4, asserting preflight green,
# no tracebacks, no error banners. This is the regression gate that
# would have caught the 2026-04-19 beta-tester reports.
#
# Usage:
#   ./wizard-matrix.sh                                # all pre-states on Debian cloud
#   ./wizard-matrix.sh --image=raspios-trixie-lite    # all pre-states on raspios
#   ./wizard-matrix.sh <pre-state>                    # single pre-state
#
# Run-time budget: ~5 min per pre-state * N pre-states. Debian cloud +
# 4 pre-states = ~20 min total. Run nightly in CI; on-demand locally.
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")" && pwd)"
WIZARD_CI="$HARNESS_DIR/wizard-ci.sh"
PRE_STATES_DIR="$HARNESS_DIR/pre-states"

IMAGE_ARG=""
ONE_PRE_STATE=""
for arg in "$@"; do
    case "$arg" in
        --image=*) IMAGE_ARG="$arg" ;;
        --help|-h)
            echo "usage: $0 [--image=ALIAS] [<pre-state-name>]"
            echo ""
            echo "available pre-states:"
            for p in "$PRE_STATES_DIR"/*.sh; do
                echo "  - $(basename "$p" .sh)"
            done
            exit 0
            ;;
        -*)
            echo "unknown arg: $arg" >&2
            exit 2
            ;;
        *) ONE_PRE_STATE="$arg" ;;
    esac
done

declare -a PRE_STATES=()
if [ -n "$ONE_PRE_STATE" ]; then
    if [ ! -f "$PRE_STATES_DIR/${ONE_PRE_STATE}.sh" ]; then
        echo "FAIL: unknown pre-state: $ONE_PRE_STATE" >&2
        exit 2
    fi
    PRE_STATES=("$ONE_PRE_STATE")
else
    while IFS= read -r p; do
        PRE_STATES+=("$(basename "$p" .sh)")
    done < <(find "$PRE_STATES_DIR" -maxdepth 1 -name "*.sh" -type f | sort)
fi

echo "========================================================================"
echo "  wizard-matrix: ${#PRE_STATES[@]} pre-state(s), image=${IMAGE_ARG:-debian/trixie/cloud (default)}"
echo "========================================================================"
declare -a RESULTS=()
OVERALL_RC=0
for ps in "${PRE_STATES[@]}"; do
    echo ""
    echo "================================================================"
    echo "  pre-state: $ps"
    echo "================================================================"
    rc=0
    # shellcheck disable=SC2086
    if [ -n "$IMAGE_ARG" ]; then
        "$WIZARD_CI" --smoke "$IMAGE_ARG" "--pre-state=$ps" || rc=$?
    else
        "$WIZARD_CI" --smoke "--pre-state=$ps" || rc=$?
    fi
    if [ "$rc" -eq 0 ]; then
        RESULTS+=("PASS: $ps")
    else
        RESULTS+=("FAIL: $ps (exit $rc)")
        OVERALL_RC=1
        # Continue to surface every failure in one run (don't fail-fast).
    fi
done

echo ""
echo "========================================================================"
echo "  matrix summary"
echo "========================================================================"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
if [ "$OVERALL_RC" -eq 0 ]; then
    echo "wizard-matrix: all pre-states PASS"
else
    echo "wizard-matrix: at least one pre-state FAILED" >&2
fi
exit "$OVERALL_RC"
