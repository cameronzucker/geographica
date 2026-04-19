#!/bin/bash
# dev/harness/wizard-ci.sh — LXD+Playwright harness for the setup wizard.
#
# Usage: ./wizard-ci.sh [--smoke | --pipeline-start | --full] [--image=ALIAS] [--pre-state=NAME]
#
#   --smoke          walk through Steps 1-4 and exit clean (~3-5 min)
#   --pipeline-start smoke + click Start Pipeline + assert a step starts +
#                    WebSocket delivers real frames + no tracebacks (~4-6 min).
#                    Catches bugs that fire AFTER preflight — missing deps
#                    in pipeline scripts, broken /ws/progress, silent pipeline
#                    failures. Container teardown is the cancel.
#   --full           run the full pipeline + wait for stack healthy (~8 hr)
#   --image=X     LXD image alias to launch from (default: images:debian/trixie/cloud).
#                 Use `raspios-trixie-lite` to mirror the actual beta-tester
#                 environment. See dev/harness/import-raspios.sh to create that
#                 alias on a fresh host.
#   --pre-state=X name of a pre-state snippet in dev/harness/pre-states/X.sh to
#                 source inside the container before running bootstrap. Lets us
#                 simulate customer-realistic starting states (docker.io
#                 preinstalled, half-bootstrap state, etc.). Default: clean.
set -euo pipefail

MODE="smoke"
IMAGE="images:debian/trixie/cloud"
PRE_STATE="clean"
for arg in "$@"; do
    case "$arg" in
        --smoke)          MODE="smoke" ;;
        --pipeline-start) MODE="pipeline-start" ;;
        --full)           MODE="full"  ;;
        --image=*)        IMAGE="${arg#--image=}" ;;
        --pre-state=*)    PRE_STATE="${arg#--pre-state=}" ;;
        *)
            echo "unknown arg: $arg"
            echo "usage: $0 [--smoke|--pipeline-start|--full] [--image=ALIAS] [--pre-state=NAME]"
            exit 2
            ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PRE_STATE_FILE="$REPO_ROOT/dev/harness/pre-states/${PRE_STATE}.sh"
if [ ! -f "$PRE_STATE_FILE" ]; then
    echo "FAIL: pre-state '$PRE_STATE' not found at $PRE_STATE_FILE" >&2
    echo "available:" >&2
    ls -1 "$REPO_ROOT/dev/harness/pre-states/"*.sh 2>/dev/null | \
        xargs -I{} basename {} .sh | sed 's/^/  - /' >&2
    exit 2
fi
CONTAINER="geographica-wizard-ci-${PRE_STATE}-$(date +%s)"

cleanup() {
    echo "[cleanup] deleting $CONTAINER"
    lxc delete --force "$CONTAINER" 2>/dev/null || true
}
trap cleanup EXIT

echo "[$(date +%H:%M:%S)] Launching LXD container (mode=$MODE, image=$IMAGE, pre-state=$PRE_STATE)..."
lxc launch "$IMAGE" "$CONTAINER"

echo "[$(date +%H:%M:%S)] Bringing container network up..."
# Raspios LXD images don't auto-configure eth0 (raspios uses dhcpcd /
# NetworkManager, neither of which fires in a fresh LXD container with
# no cmdline.txt). Debian cloud images run cloud-init which does this
# for us. Unify by brute-forcing eth0 up with DHCP if it's not already.
if ! lxc exec "$CONTAINER" -- ip -4 addr show eth0 2>/dev/null | grep -q "inet "; then
    # Install systemd-networkd + enable + configure if not already.
    lxc exec "$CONTAINER" -- bash -c '
        set -e
        if ! command -v networkctl >/dev/null 2>&1; then
            apt-get update -qq >/dev/null 2>&1 || true
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq systemd \
                >/dev/null 2>&1 || true
        fi
        mkdir -p /etc/systemd/network
        cat > /etc/systemd/network/80-container-eth0.network <<EOF
[Match]
Name=eth0

[Network]
DHCP=yes
EOF
        systemctl enable --now systemd-networkd >/dev/null 2>&1 || true
    ' 2>/dev/null || true
fi

echo "[$(date +%H:%M:%S)] Waiting for container ready (cloud-init or plain)..."
# Poll for two signals of readiness:
#   1. cloud-init is done/disabled/absent (so it's not still racing us)
#   2. deb.debian.org is resolvable AND reachable on port 80
for i in {1..60}; do
    STATUS="$(lxc exec "$CONTAINER" -- cloud-init status 2>/dev/null \
        | awk -F': *' '/^status:/ {print $2}' | tr -d '[:space:]')"
    if [ "$STATUS" = "done" ] || [ "$STATUS" = "disabled" ] || [ -z "$STATUS" ]; then
        if lxc exec "$CONTAINER" -- getent hosts deb.debian.org >/dev/null 2>&1; then
            break
        fi
    fi
    sleep 2
done
if ! lxc exec "$CONTAINER" -- getent hosts deb.debian.org >/dev/null 2>&1; then
    echo "FAIL: container did not come online within 120s" >&2
    lxc exec "$CONTAINER" -- bash -c "ip -4 a; ip route; cat /etc/resolv.conf" 2>&1 | head -20 >&2
    exit 1
fi

echo "[$(date +%H:%M:%S)] Copying repo into container..."
# Use `git ls-files` + tar rather than `lxc file push -r` or `git archive`:
#   - `git archive HEAD` would NOT include uncommitted working-tree changes,
#     which means the harness couldn't be used to test a fix-in-progress.
#     `git ls-files` + tar captures the working tree, matching the state
#     the developer is actually iterating on.
#   - only tracked files → no .env / .claude/settings.local.json / node_modules
#     leak into the test container.
#   - LXD versions differ on whether `file push -r` wants a pre-created
#     destination and on trailing-slash semantics; piping a tarball via
#     `lxc exec -- tar -x` is version-stable.
lxc exec "$CONTAINER" -- mkdir -p /root/geographica
( cd "$REPO_ROOT" && git ls-files -z | tar --null -T - -cf - ) \
    | lxc exec "$CONTAINER" -- tar -x -C /root/geographica

echo "[$(date +%H:%M:%S)] Applying pre-state '$PRE_STATE'..."
# Seed curl+gpg+ca-certs so the pre-state snippet has tooling to work
# with (matches what a real Pi user would have). Idempotent on raspios.
lxc exec "$CONTAINER" -- bash -c \
    "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl gpg ca-certificates" \
    >/dev/null
lxc file push "$PRE_STATE_FILE" "$CONTAINER/tmp/pre-state.sh"
lxc exec "$CONTAINER" -- bash /tmp/pre-state.sh

echo "[$(date +%H:%M:%S)] Running bootstrap.sh..."
lxc exec "$CONTAINER" -- bash -c "cd /root/geographica && ./bootstrap.sh"

echo "[$(date +%H:%M:%S)] Starting setup.sh via systemd-run (detached) ..."
# lxc exec holds the session open even with `&`, nohup, or setsid — it
# waits on the child's file descriptors. The reliable way to start a
# long-running process inside an LXD container without blocking is
# `systemd-run`, which spawns a transient service unit and returns
# immediately. The service keeps the wizard alive after lxc exec exits.
lxc exec "$CONTAINER" -- systemd-run \
    --unit=geographica-wizard-setup \
    --description="Geographica setup wizard (CI)" \
    --working-directory=/root/geographica \
    --setenv=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    bash -c "./setup.sh >/tmp/setup.log 2>&1"

# Set up a host-reachable proxy to the wizard. setup.sh binds 127.0.0.1:8099
# inside the container (correct for production — don't expose the wizard on
# the LAN). For CI, we need host reachability, so add an LXD proxy device
# that listens on host 127.0.0.1:8099 (or a free alternative) and forwards
# to the container's 127.0.0.1:8099.
WIZARD_HOST_PORT="${WIZARD_HOST_PORT:-18099}"
lxc config device add "$CONTAINER" wizard-proxy proxy \
    "listen=tcp:127.0.0.1:$WIZARD_HOST_PORT" \
    "connect=tcp:127.0.0.1:8099" >/dev/null
WIZARD_URL="http://127.0.0.1:$WIZARD_HOST_PORT"
echo "[$(date +%H:%M:%S)] Proxy: $WIZARD_URL → container 127.0.0.1:8099"

echo "[$(date +%H:%M:%S)] Waiting for wizard (up to 120s)..."
# Poll every 2s, up to 120s.
WIZARD_UP=0
for i in {1..60}; do
    if curl -fs -m 2 "$WIZARD_URL/" >/dev/null 2>&1; then
        echo "[$(date +%H:%M:%S)] Wizard up."
        WIZARD_UP=1
        break
    fi
    sleep 2
done
if [ "$WIZARD_UP" -eq 0 ]; then
    echo "FAIL: wizard did not open port 8099 within 120s"
    echo "--- setup.log tail ---"
    lxc exec "$CONTAINER" -- cat /tmp/setup.log 2>/dev/null | tail -40 || true
    echo "--- container listening ports ---"
    lxc exec "$CONTAINER" -- ss -tlnp 2>/dev/null | head -10 || true
    exit 1
fi

# Verify every critical runtime Python package is installed in the venv
# that setup.sh runs uvicorn in. setup/requirements.txt can miss a dep
# without any visible failure at wizard-load (the failure only fires
# later — e.g. the 2026-04-19 beta report where `websockets` was
# missing so /ws/progress handshakes silently failed and the frontend
# retried forever with no UI feedback). This probe executes inside the
# wizard's own venv python so it catches exactly the runtime state
# uvicorn will hit when serving requests.
echo "[$(date +%H:%M:%S)] Verifying wizard venv has critical runtime deps..."
WIZARD_VENV_PY=/root/geographica/setup/.venv/bin/python3
MISSING_DEPS=""
for dep in websockets fastapi uvicorn httpx; do
    if ! lxc exec "$CONTAINER" -- "$WIZARD_VENV_PY" -c "import $dep" 2>/dev/null; then
        MISSING_DEPS="$MISSING_DEPS $dep"
    fi
done
if [ -n "$MISSING_DEPS" ]; then
    echo "FAIL: wizard venv is missing critical runtime deps:$MISSING_DEPS" >&2
    echo "--- setup/requirements.txt in container ---" >&2
    lxc exec "$CONTAINER" -- cat /root/geographica/setup/requirements.txt 2>&1 | head -10 >&2
    echo "--- pip list in venv ---" >&2
    lxc exec "$CONTAINER" -- "$WIZARD_VENV_PY" -m pip list 2>/dev/null | head -30 >&2
    exit 1
fi
echo "[$(date +%H:%M:%S)]   all critical deps importable in venv"

echo "[$(date +%H:%M:%S)] Driving wizard (mode=$MODE)..."
RC=0
MODE_FLAG="--$MODE"
node "$(dirname "$0")/drive-wizard.mjs" "$MODE_FLAG" --url="$WIZARD_URL" || RC=$?

if [ "$RC" -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] Wizard walkthrough OK."
else
    echo "FAIL: drive-wizard.mjs exited $RC"
    lxc exec "$CONTAINER" -- cat /tmp/setup.log 2>/dev/null | tail -60 || true
fi

exit $RC
