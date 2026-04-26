#!/usr/bin/env bash
# Walk every relative markdown link in the doc set and verify each target exists.
# Exits non-zero if any broken link is found.
#
# Scope: the 5-doc README set (README.md + docs/SETUP.md, MANUAL_SETUP.md,
# PROCESS.md, COST_METHODOLOGY.md). Out-of-band docs like
# docs/CROSS_MODEL_REVIEW_VALUE.md and docs/CACHE_OPTIMIZATION.md are
# intentionally NOT walked.
#
# What "broken" means: the resolved file path does not exist on disk.
# Anchor fragments (#section) are stripped before the existence check —
# the script does NOT validate that an #anchor resolves to a heading.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DOCS=(
  "README.md"
  "docs/SETUP.md"
  "docs/MANUAL_SETUP.md"
  "docs/PROCESS.md"
  "docs/COST_METHODOLOGY.md"
)

broken=0
for src in "${DOCS[@]}"; do
  if [ ! -f "$src" ]; then
    echo "BROKEN: $src does not exist"
    broken=$((broken + 1))
    continue
  fi
  src_dir="$(dirname "$src")"
  # Use process substitution so the inner `while` runs in the parent
  # shell and `broken` increments propagate. Pipe-based `grep | while`
  # would put the loop in a subshell and lose the counter.
  # `|| true` guards against grep's exit-1-on-no-match tripping pipefail.
  while read -r link; do
    [ -z "$link" ] && continue
    target="${link%%#*}"
    [ -z "$target" ] && continue
    # Resolve relative to the source file's directory (or repo root for /-rooted)
    if [ "${target:0:1}" = "/" ]; then
      full="$ROOT$target"
    else
      full="$src_dir/$target"
    fi
    if [ ! -e "$full" ]; then
      echo "BROKEN: $src -> $link (resolves to $full)"
      broken=$((broken + 1))
    fi
  done < <(
    grep -oE '\]\(([a-zA-Z0-9_./#-]+)\)' "$src" 2>/dev/null \
      | sed -E 's/\]\(([^)]+)\)/\1/' \
      | grep -vE '^https?://' \
      | grep -vE '^mailto:' \
      || true
  )
done

if [ "$broken" -gt 0 ]; then
  echo ""
  echo "Found $broken broken link(s)."
  exit 1
fi
echo "All links resolve."
