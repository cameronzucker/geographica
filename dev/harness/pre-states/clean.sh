#!/bin/bash
# clean — baseline pre-state. No Docker packages preinstalled.
#
# Purpose: confirm bootstrap.sh still succeeds on a fresh system. This
# is the happy-path green our LXD harness already exercises; we keep
# it in the matrix so the matrix itself is provably regression-free
# (if `clean` ever fails, the matrix runner is broken, not bootstrap).
set -e
echo "[pre-state clean] no-op"
