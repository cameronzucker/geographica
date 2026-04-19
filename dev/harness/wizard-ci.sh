#!/bin/bash
# dev/harness/wizard-ci.sh — LXD+Playwright harness for the setup wizard.
# Usage: ./wizard-ci.sh [--smoke | --full]
#   --smoke : walk through Steps 1-4 and exit clean (~3 min)
#   --full  : run the full pipeline + wait for stack healthy (~8 hr)
set -euo pipefail

MODE="smoke"
for arg in "$@"; do
    case "$arg" in
        --smoke) MODE="smoke" ;;
        --full)  MODE="full"  ;;
        *) echo "unknown arg: $arg"; echo "usage: $0 [--smoke|--full]"; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONTAINER="geographica-wizard-ci-$(date +%s)"

cleanup() {
    echo "[cleanup] deleting $CONTAINER"
    lxc delete --force "$CONTAINER" 2>/dev/null || true
}
trap cleanup EXIT

echo "[$(date +%H:%M:%S)] Launching LXD container ($MODE mode)..."
lxc launch images:debian/trixie/cloud "$CONTAINER"

echo "[$(date +%H:%M:%S)] Waiting for cloud-init..."
# Wait up to 60s for cloud-init to finish
for i in {1..30}; do
    if lxc exec "$CONTAINER" -- cloud-init status --wait 2>/dev/null | grep -q done; then
        break
    fi
    sleep 2
done

echo "[$(date +%H:%M:%S)] Copying repo into container..."
lxc file push -r -q "$REPO_ROOT/" "$CONTAINER/root/geographica/"

echo "[$(date +%H:%M:%S)] Running bootstrap.sh..."
lxc exec "$CONTAINER" -- bash -c "cd /root/geographica && ./bootstrap.sh"

echo "[$(date +%H:%M:%S)] Starting setup.sh..."
lxc exec "$CONTAINER" -- bash -c "cd /root/geographica && nohup ./setup.sh >/tmp/setup.log 2>&1 &"

# Get container IP
CONTAINER_IP=""
for i in {1..30}; do
    CONTAINER_IP="$(lxc list "$CONTAINER" --format csv -c 4 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)"
    if [ -n "$CONTAINER_IP" ]; then break; fi
    sleep 1
done
if [ -z "$CONTAINER_IP" ]; then
    echo "FAIL: could not resolve container IP"
    exit 1
fi
echo "[$(date +%H:%M:%S)] Container IP: $CONTAINER_IP"

echo "[$(date +%H:%M:%S)] Waiting for wizard on port 8099..."
# Poll every 2s, up to 120s
for i in {1..60}; do
    if curl -fs -m 2 "http://$CONTAINER_IP:8099/" >/dev/null 2>&1; then
        echo "[$(date +%H:%M:%S)] Wizard up."
        break
    fi
    sleep 2
done
if ! curl -fs -m 5 "http://$CONTAINER_IP:8099/" >/dev/null 2>&1; then
    echo "FAIL: wizard did not open port 8099 within 120s"
    lxc exec "$CONTAINER" -- cat /tmp/setup.log 2>/dev/null | tail -40 || true
    exit 1
fi

echo "[$(date +%H:%M:%S)] Driving wizard (mode=$MODE)..."
RC=0
node "$(dirname "$0")/drive-wizard.mjs" --"$MODE" --url="http://$CONTAINER_IP:8099" || RC=$?

if [ "$RC" -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] Wizard walkthrough OK."
else
    echo "FAIL: drive-wizard.mjs exited $RC"
    lxc exec "$CONTAINER" -- cat /tmp/setup.log 2>/dev/null | tail -60 || true
fi

exit $RC
