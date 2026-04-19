#!/bin/bash
# docker-io — user installed Debian's legacy docker.io package.
#
# This was the pre-Task-4 bootstrap.sh path, and is also what many Pi
# users reach for instinctively ("sudo apt install docker") before
# finding the project's own bootstrap. On Trixie, docker.io pulls in
# docker-buildx + docker-compose as dependencies, so this pre-state
# is a superset of `debian-docker-buildx.sh` with extra packages
# (docker.io's own binary plus runc, containerd, etc.).
#
# If bootstrap only handled the narrow docker-buildx/docker-compose
# case and not docker.io itself, this pre-state would catch it.
set -e
echo "[pre-state docker-io] installing Debian's docker.io"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io
echo "[pre-state docker-io] preinstalled state:"
dpkg -l docker.io docker-buildx docker-compose 2>/dev/null | grep ^ii || true
