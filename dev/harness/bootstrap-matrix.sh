#!/bin/bash
# dev/harness/bootstrap-matrix.sh — apt-level pre-state matrix for bootstrap.sh.
#
# Runs the bootstrap "[1/6] Installing system packages..." block against a
# matrix of realistic customer starting states — each in an ephemeral
# Debian 13 (trixie) Docker container. Catches regressions like the
# 2026-04-19 beta blocker where Debian-native docker-buildx + docker-compose
# file-conflict with Docker's official -plugin packages and abort bootstrap.
#
# Complements dev/harness/wizard-ci.sh: that harness exercises the FULL
# wizard flow against a clean LXD container (systemd, ports, Playwright);
# this one is apt-focused and fast (~2 min total across all pre-states)
# and runs inside Docker, so it's CI-cheap and doesn't depend on LXD
# bridge state.
#
# Usage:
#   ./bootstrap-matrix.sh                   # all pre-states
#   ./bootstrap-matrix.sh <pre-state-name>  # single pre-state (name or basename)
#
# Exit 0 iff every pre-state completes with docker-ce + docker-compose-plugin
# installed. Non-zero on first failure (fail-fast per `set -e`).
set -euo pipefail

HARNESS_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HARNESS_DIR/../.." && pwd)"
PRE_STATES_DIR="$HARNESS_DIR/pre-states"
BOOTSTRAP_SH="$REPO_ROOT/bootstrap.sh"

if ! command -v docker >/dev/null 2>&1; then
    echo "FAIL: docker is required on the host to run this matrix" >&2
    exit 2
fi
if [ ! -f "$BOOTSTRAP_SH" ]; then
    echo "FAIL: cannot find bootstrap.sh at $BOOTSTRAP_SH" >&2
    exit 2
fi

# Which pre-states to run? Either a single name from $1 or the full set.
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "usage: $0 [<pre-state-name>]"
    echo ""
    echo "available pre-states:"
    for p in "$PRE_STATES_DIR"/*.sh; do
        echo "  - $(basename "$p" .sh)"
    done
    exit 0
fi
if [ -n "${1:-}" ]; then
    NAME="${1%.sh}"
    if [ ! -f "$PRE_STATES_DIR/$NAME.sh" ]; then
        echo "FAIL: unknown pre-state: $NAME" >&2
        echo "available:" >&2
        for p in "$PRE_STATES_DIR"/*.sh; do
            echo "  - $(basename "$p" .sh)" >&2
        done
        exit 2
    fi
    PRE_STATES=("$NAME.sh")
else
    PRE_STATES=()
    while IFS= read -r p; do
        PRE_STATES+=("$(basename "$p")")
    done < <(find "$PRE_STATES_DIR" -maxdepth 1 -name "*.sh" -type f | sort)
fi

# Extract bootstrap.sh's apt-install block (everything from "[1/6]" up to
# but not including "[2/6]") into a temp file. We run just this slice
# inside the container — the remaining bootstrap steps (systemd, pip,
# tippecanoe download, keyring agent) are out of scope for an apt-level
# pre-state test and would require systemd-in-Docker which is fragile.
BOOTSTRAP_SLICE="$(mktemp -t bootstrap-apt-slice.XXXXXX.sh)"
trap 'rm -f "$BOOTSTRAP_SLICE"' EXIT
{
    echo '#!/bin/bash'
    echo 'set -e'
    echo 'ACTUAL_USER=root  # runtime stub; bootstrap checks this but the slice does not use it'
    # awk is more deterministic than sed for extracting a delimited range.
    awk '
        /^echo "\[1\/6\] Installing system packages\.\.\."/ { printing=1 }
        /^echo "\[2\/6\] Installing keyring dependencies\.\.\."/ { printing=0 }
        printing { print }
    ' "$BOOTSTRAP_SH"
} > "$BOOTSTRAP_SLICE"

if ! grep -q "Installing system packages" "$BOOTSTRAP_SLICE"; then
    echo "FAIL: could not extract bootstrap.sh [1/6] slice — section banner changed?" >&2
    exit 2
fi
if ! grep -q "apt install -y" "$BOOTSTRAP_SLICE"; then
    echo "FAIL: extracted slice missing apt install — check slice delimiters" >&2
    exit 2
fi

run_pre_state() {
    local pre_state_file="$1"
    local pre_state_name
    pre_state_name="$(basename "$pre_state_file" .sh)"
    local container="geographica-bootstrap-matrix-${pre_state_name}-$$"

    echo ""
    echo "================================================================"
    echo "  pre-state: $pre_state_name"
    echo "================================================================"

    # Copy pre-state + bootstrap slice into a cidfile-tracked ephemeral
    # container, then exec both in order.
    local workdir
    workdir="$(mktemp -d -t bootstrap-matrix-XXXXXX)"
    cp "$PRE_STATES_DIR/$pre_state_file" "$workdir/pre-state.sh"
    cp "$BOOTSTRAP_SLICE" "$workdir/bootstrap-slice.sh"

    local rc=0
    docker run --rm \
        --name "$container" \
        --platform linux/arm64 \
        -v "$workdir":/matrix:ro \
        debian:trixie \
        bash -c '
            set -e
            # Seed the container with the baseline tooling every real
            # Raspberry Pi OS install ships with (curl, gpg, CA certs).
            # The minimal debian:trixie Docker image ships a stripped
            # userland that lacks these; seeding here keeps the pre-
            # state scripts focused on Docker-package state and
            # makes the Docker container match a real Pi.
            echo "[$(date +%H:%M:%S)] baseline: installing curl, gpg, ca-certificates..."
            apt-get update -qq >/dev/null
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                curl gpg ca-certificates >/dev/null
            echo "[$(date +%H:%M:%S)] pre-state: applying..."
            bash /matrix/pre-state.sh
            echo "[$(date +%H:%M:%S)] bootstrap slice: executing apt block..."
            bash /matrix/bootstrap-slice.sh
            echo "[$(date +%H:%M:%S)] verifying docker-ce + plugins installed..."
            dpkg -s docker-ce >/dev/null
            dpkg -s docker-ce-cli >/dev/null
            dpkg -s containerd.io >/dev/null
            dpkg -s docker-compose-plugin >/dev/null
            # The Debian-conflicting packages must be FUNCTIONALLY GONE.
            # `dpkg -s` returns 0 both for "install ok installed" and
            # "deinstall ok config-files" — the latter means apt removed
            # the binary but left config files behind, which is the
            # normal result of `apt remove` (as opposed to `apt purge`).
            # Bootstrap deliberately uses `remove` so we do not wipe any
            # user config; config-files state is a PASS here, only
            # "install ok installed" is a regression.
            leftovers=""
            for pkg in docker-buildx docker-compose docker.io; do
                status="$(dpkg-query -W -f="\${Status}" "$pkg" 2>/dev/null || true)"
                if [ "$status" = "install ok installed" ]; then
                    leftovers="$leftovers $pkg"
                fi
            done
            if [ -n "$leftovers" ]; then
                echo "FAIL: conflicting Debian package(s) still fully installed after bootstrap:$leftovers"
                for pkg in $leftovers; do
                    dpkg -l "$pkg" 2>/dev/null | grep ^ii || true
                done
                exit 1
            fi
            docker_ce_ver="$(dpkg-query -W -f="\${Version}" docker-ce)"
            compose_ver="$(dpkg-query -W -f="\${Version}" docker-compose-plugin)"
            echo "PASS: docker-ce=$docker_ce_ver docker-compose-plugin=$compose_ver"
        ' || rc=$?

    rm -rf "$workdir"

    if [ "$rc" -ne 0 ]; then
        echo "FAIL: pre-state '$pre_state_name' returned exit $rc" >&2
        return "$rc"
    fi
    echo "OK: pre-state '$pre_state_name' passed"
}

# Track results so we can print a summary.
declare -a RESULTS=()
OVERALL_RC=0
for pre_state_file in "${PRE_STATES[@]}"; do
    if run_pre_state "$pre_state_file"; then
        RESULTS+=("PASS: $pre_state_file")
    else
        RESULTS+=("FAIL: $pre_state_file")
        OVERALL_RC=1
        # fail-fast per `set -e` on the outer script if desired:
        # but we want to see ALL failures in one run, so continue.
    fi
done

echo ""
echo "================================================================"
echo "  matrix summary"
echo "================================================================"
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
if [ "$OVERALL_RC" -eq 0 ]; then
    echo "bootstrap-matrix: all pre-states PASS"
else
    echo "bootstrap-matrix: at least one pre-state FAILED" >&2
fi
exit "$OVERALL_RC"
