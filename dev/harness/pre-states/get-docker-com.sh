#!/bin/bash
# get-docker-com — user followed https://get.docker.com before finding us.
#
# Docker's official convenience script installs docker-ce + all plugins
# from Docker's own repo, and places the keyring at /etc/apt/keyrings/
# docker.asc (note .asc, not .gpg). Our bootstrap's keyring-setup guard
# must accept either filename (broadened in commit 8608b6d); otherwise
# bootstrap re-downloads the key and writes a duplicate sources.list
# entry.
#
# This pre-state asserts bootstrap is idempotent in that scenario:
# after our bootstrap runs on top of get.docker.com's output, there
# should still be exactly one /etc/apt/keyrings/docker.* and exactly
# one /etc/apt/sources.list.d/docker.list, and the docker-ce / plugin
# packages should already be at their latest versions (i.e. apt install
# is a no-op).
#
# Uses the pinned release URL rather than the bleeding-edge
# convenience script so the pre-state is deterministic across runs.
set -e
echo "[pre-state get-docker-com] running Docker's official get.docker.com script"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl ca-certificates
curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
# `sh /tmp/get-docker.sh` triggers the full Docker install including
# systemctl enable. Inside Docker-in-Docker that fails — but the
# apt/repo/package side of the script runs first and is what we're
# testing. Tolerate the systemctl failure at the tail.
sh /tmp/get-docker.sh 2>&1 | tail -8 || true
echo "[pre-state get-docker-com] preinstalled keyring + packages:"
ls -la /etc/apt/keyrings/docker.* 2>/dev/null || echo "(no keyring files)"
cat /etc/apt/sources.list.d/docker.list 2>/dev/null || true
dpkg -l docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-buildx-plugin 2>/dev/null | grep ^ii || true
