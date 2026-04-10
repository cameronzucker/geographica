#!/bin/bash
set -e
cd "$(dirname "$0")"

# Check Docker is accessible
if ! docker info > /dev/null 2>&1; then
  echo "Docker is not accessible. You may need to:"
  echo "  1. Run: sudo ./bootstrap.sh"
  echo "  2. Log out and back in (for docker group to take effect)"
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
