#!/bin/bash
# debian-docker-buildx — the 2026-04-19 beta-blocker pre-state.
#
# Reproduces the exact state of every beta tester who had ever run
# `apt install docker.io` or `apt full-upgrade` with docker.io
# preinstalled on Raspberry Pi OS Trixie: Debian's native
# docker-buildx (0.13.1+ds1-3) and docker-compose (2.26.1-4)
# packages already unpacked, with their file list claiming
# /usr/libexec/docker/cli-plugins/docker-{buildx,compose} — the
# exact paths Docker's docker-buildx-plugin + docker-compose-plugin
# will try to claim later. Neither side declares Replaces, so
# without the purge step added in fix(setup) 59f00b5, the
# downstream `apt install docker-ce` aborts mid-unpack with
#
#   dpkg: error processing archive .../docker-buildx-plugin_0.33.0-...deb (--unpack):
#    trying to overwrite '/usr/libexec/docker/cli-plugins/docker-buildx',
#    which is also in package docker-buildx 0.13.1+ds1-3
#
# If this pre-state fails the matrix, bootstrap regressed on the
# conflict-purge behavior and beta testers on Trixie will be blocked
# again.
set -e
echo "[pre-state debian-docker-buildx] installing Debian's docker-buildx + docker-compose"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    docker-buildx \
    docker-compose
echo "[pre-state debian-docker-buildx] preinstalled state:"
dpkg -l docker-buildx docker-compose 2>/dev/null | grep ^ii
