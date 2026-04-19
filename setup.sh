#!/bin/bash
set -e
cd "$(dirname "$0")"

# Check Docker is accessible. Two distinct failure modes — diagnose which
# and give the user a specific fix, not a vague suggestion list.
if ! command -v docker >/dev/null 2>&1; then
    echo "============================================"
    echo "ERROR: Docker is not installed on this system."
    echo "============================================"
    echo ""
    echo "You haven't run bootstrap.sh yet. Run this first:"
    echo "    sudo ./bootstrap.sh"
    echo ""
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    # docker is installed but the current user can't talk to the daemon.
    # Overwhelmingly this is because the user is NOT in the 'docker' group
    # for this login session (they ran bootstrap.sh but didn't fully log
    # out and back in — or they think re-opening a screen session counts,
    # which it doesn't).
    echo "============================================"
    echo "ERROR: Docker is installed but not accessible to you."
    echo "============================================"
    echo ""
    if id -nG "$USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
        echo "Your user '$USER' IS in the docker group already, so this is"
        echo "NOT a group-membership issue. The Docker daemon itself may not"
        echo "be running. Try:"
        echo "    sudo systemctl status docker"
        echo "    sudo systemctl start docker"
    else
        echo "Your user '$USER' is NOT in the docker group in this shell."
        echo ""
        echo "That means bootstrap.sh added you to the group, BUT you haven't"
        echo "fully logged out and back in since — so your current shell still"
        echo "runs without docker group membership."
        echo ""
        echo "IMPORTANT: exiting a screen/tmux session is NOT enough."
        echo "Opening a new terminal tab is NOT enough."
        echo "You must FULLY disconnect from the Pi and reconnect, OR reboot."
        echo ""
        echo "FIX — pick one:"
        echo "  A. sudo reboot   then log back in after ~1 minute"
        echo "  B. Type 'exit' to close your SSH session, then SSH back in"
        echo "  C. Log out of the desktop/console, then log back in"
        echo ""
        echo "Verify it worked by running:  groups"
        echo "You should see 'docker' in the output."
    fi
    echo ""
    exit 1
fi

# Create/reuse Python venv (separate from project .venv)
if [ ! -d setup/.venv ]; then
  python3 -m venv setup/.venv
fi
source setup/.venv/bin/activate
pip install -q -r setup/requirements.txt

echo ""
echo "Starting Geographica Setup Wizard..."
echo "Open http://localhost:8099 in your browser."
echo ""
echo "If accessing remotely via SSH, use:"
echo "  ssh -L 8099:localhost:8099 $(whoami)@$(ip route get 1 | awk '{print $7; exit}')"
echo ""

python3 -m uvicorn setup.main:app --host 127.0.0.1 --port 8099
