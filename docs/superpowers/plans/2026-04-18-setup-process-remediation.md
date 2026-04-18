# Setup Process Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 48 confirmed bugs + 8 design-decision resolutions in the Geographica setup wizard (post v1.1.0), so a fresh beta tester can go from `git clone` to a working stack without manual intervention.

**Architecture:** 10 phases. Phase 0 is docs-only and can merge immediately to unblock the beta tester. Phases 1-8 fix the wizard/bootstrap/docker-compose code paths. Phase 9 adds an LXD+Playwright CI harness to prevent regressions. Phase 10 finalizes the implementation log.

**Tech Stack:** FastAPI (setup/main.py), Python 3.12 (setup/*), vanilla JS (setup/static/), bash (bootstrap.sh), Docker Compose v2, nginx, SystemD (keyring agent), LXD + Playwright (Phase 9 harness).

---

## Baseline test expectation

Before starting: run the test suite and record the baseline. Expect 2 pre-existing M2M failures + 9 pre-existing OSM POI errors. Every task's completion check compares against this baseline.

Baseline command: `python -m pytest tests/ services/search/tests/ -v`

---

(Plan body continues — see follow-up appended sections.)

> **Note on setup.js line numbers:** Tasks 14, 20, 22, 23, 29, 34, 35, 38, 39, 40 all modify `setup/static/setup.js`. Line numbers in task descriptions are pre-refactor. When dispatched, subagents should locate edit sites by SYMBOL NAME (function, variable, event handler) rather than line range. Each task's Files section lists symbols where possible.

## Phase 0 — Unblock beta tester (docs only)

### Task 1: Fix `cdzucker` clone-URL typos + dev-Pi path reference

**Files:**
- Modify: `README.md:111` (Quick Start clone)
- Modify: `README.md:185` (Manual clone)
- Modify: `README.md:576` (Companion utility URL)
- Modify: `README.md:588` (replace `~/Code/geographica` with `~/geographica`)
- Modify: `bootstrap.sh:24` (world-writable warning)
- Test: `tests/test_docs_urls.py` (NEW)

**TDD preamble:** Read `/home/administrator/.claude/plugins/cache/claude-plugins-official/superpowers/5.0.7/skills/test-driven-development/SKILL.md`. Review testing-pitfalls entry "Multi-layer enum values diverge silently" — cross-file string drift is the same class.

- [ ] **Step 1: Write failing test**

Create `tests/test_docs_urls.py`:

```python
"""Verify no cdzucker typos in docs or scripts."""
from pathlib import Path

REPO = Path(__file__).parent.parent


def test_readme_has_no_cdzucker():
    text = (REPO / "README.md").read_text()
    assert "cdzucker" not in text


def test_bootstrap_has_no_cdzucker():
    text = (REPO / "bootstrap.sh").read_text()
    assert "cdzucker" not in text


def test_readme_has_no_code_geographica_devpath():
    text = (REPO / "README.md").read_text()
    assert "~/Code/geographica" not in text


def test_correct_clone_url_appears():
    text = (REPO / "README.md").read_text()
    assert "github.com/cameronzucker/geographica" in text
```

- [ ] **Step 2: Run test to verify FAIL**

Run: `python -m pytest tests/test_docs_urls.py -v`
Expected: 3 FAIL (readme/bootstrap/devpath) + 1 PASS.

- [ ] **Step 3: Fix the typos**

In README.md replace all `github.com/cdzucker/geographica` with `github.com/cameronzucker/geographica`. Replace `~/Code/geographica` with `~/geographica` at line 588. In bootstrap.sh:24 change the clone URL in the world-writable warning accordingly.

- [ ] **Step 4: Run test to verify PASS**

Run: `python -m pytest tests/test_docs_urls.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add README.md bootstrap.sh tests/test_docs_urls.py
git commit -m "$(cat <<'MSG'
docs: fix cdzucker clone-URL typos + dev-path reference (B8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Run `python -m pytest tests/ services/search/tests/ -v`. Expect baseline+4 passed + 2 M2M failures + 9 OSM POI errors.

---

### Task 2: Fix README §12 verify-deployment port inconsistency

**Files:**
- Modify: `README.md:466-484`
- Test: extend `tests/test_docs_urls.py`

**TDD preamble:** Read TDD skill. Same pitfall as Task 1.

- [ ] **Step 1: Write failing test**

Append to `tests/test_docs_urls.py`:

```python
def test_verify_deployment_section_uses_nginx_proxy():
    text = (REPO / "README.md").read_text()
    start = text.find("## 12.")
    assert start != -1
    end = text.find("\n## ", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    forbidden = [
        "http://localhost:8090",
        "http://localhost:8092",
        "http://localhost:8094",
        "http://localhost:8095",
        "http://localhost:8096",
        "http://localhost:8098",
    ]
    for url in forbidden:
        assert url not in section, f"§12 must use :8093 proxy, found: {url}"
    assert "http://localhost:8093/" in section
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_docs_urls.py::test_verify_deployment_section_uses_nginx_proxy -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite §12**

Route every check through `http://localhost:8093/`: tileserver at `/tileserver/styles.json`, nominatim at `/nominatim/status`, valhalla at `/valhalla/status`, search at `/search/health`, stt at `/stt/health`, gps WebSocket at `ws://localhost:8093/gps/ws`. Main frontend at `http://localhost:8093/`, admin at `http://localhost:8093/admin/`.

**Additionally — D2 coverage (wizard is primary path, manual is advanced/reference):** In README.md, reframe the "Manual setup guide" heading. Replace the existing heading + preamble with this literal markdown:

```markdown
## Manual setup (advanced / AI-agent reference)

> **The browser-based setup wizard (launched via `./setup.sh` after `sudo ./bootstrap.sh`) is the recommended path.** This manual section exists for debugging and automated-deployment purposes — follow these steps only if the wizard fails on your system, or if you're driving installation from a script.
```

Append a matching assertion to `tests/test_docs_urls.py`:

```python
def test_readme_manual_section_is_labeled_advanced():
    text = (REPO / "README.md").read_text()
    assert "Manual setup (advanced" in text
    assert "browser-based setup wizard" in text.lower() or \
           "setup wizard" in text.lower()
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_docs_urls.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_docs_urls.py
git commit -m "$(cat <<'MSG'
docs: route §12 verify-deployment URLs through nginx proxy (O2)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Run `python -m pytest tests/ services/search/tests/ -v`. Expect baseline+5 passed.

---

### Task 3: Fix bootstrap duplicate "Next step:" + add log-out reminder

**Files:**
- Modify: `bootstrap.sh:82-108`
- Test: `tests/test_bootstrap_messaging.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_bootstrap_messaging.py`:

```python
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_next_step_appears_at_most_once_per_branch():
    text = BOOTSTRAP.read_text()
    idx = text.find("Bootstrap complete")
    assert idx != -1
    tail = text[idx:]
    assert tail.count('Next step:') == 1


def test_bootstrap_mentions_logout_before_setup():
    assert "Log out" in BOOTSTRAP.read_text()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_messaging.py -v`
Expected: 2 FAIL.

- [ ] **Step 3: Fix bootstrap.sh**

Replace the tail block from line 82 onward with this literal content (subagents can paste verbatim). The block must print "Next step:" exactly once per branch, and remind the user to log out in BOTH branches:

```bash
# Tail block — replaces bootstrap.sh:82-108
echo ""
echo "============================================"
echo "Bootstrap complete."
echo "============================================"
echo ""
if [ "${NEEDS_REBOOT:-0}" = "1" ]; then
    echo "A reboot is required (cgroup memory controller was enabled)."
    echo ""
    echo "Next step:"
    echo "  1. sudo reboot"
    echo "  2. Log out and back in before running ./setup.sh (docker group membership needs to take effect)."
    echo "  3. cd \"$REPO_DIR\" && ./setup.sh"
    echo ""
    echo "If you're connected over SSH, reconnect after the reboot and re-run ./setup.sh."
else
    echo "Next step:"
    echo "  Log out and back in before running ./setup.sh (docker group membership needs to take effect)."
    echo "  Then: cd \"$REPO_DIR\" && ./setup.sh"
    echo ""
    echo "If you're connected over SSH, you can log out and reconnect to the same session."
fi
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_messaging.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh tests/test_bootstrap_messaging.py
git commit -m "$(cat <<'MSG'
fix(setup): dedupe bootstrap Next-step + remind user to log out (B37)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Run `python -m pytest tests/ services/search/tests/ -v`. Expect baseline+7 passed.

**After Phase 0 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 1.

---

## Phase 1 — Bootstrap hardening

### Task 4: Replace `docker-compose` v1 with `docker-compose-plugin`

**Files:**
- Modify: `bootstrap.sh:28-35`
- Test: `tests/test_bootstrap_docker_install.py` (NEW)

**TDD preamble:** Read TDD skill. Review pitfall "Preflight/fix registries with parallel keys that drift".

- [ ] **Step 1: Write failing test**

Create `tests/test_bootstrap_docker_install.py`:

```python
import re
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_no_legacy_docker_compose_package():
    text = BOOTSTRAP.read_text()
    for line in text.splitlines():
        if "apt install" not in line and "apt-get install" not in line:
            continue
        tokens = re.findall(r"[\w.-]+", line)
        for tok in tokens:
            assert tok != "docker-compose", f"legacy v1 compose: {line}"


def test_installs_compose_plugin_or_docker_ce():
    text = BOOTSTRAP.read_text()
    assert "docker-compose-plugin" in text or "docker-compose-v2" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_docker_install.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix bootstrap.sh**

Replace the `[1/6] Installing system packages...` block with one that first adds Docker's official apt repo (create /etc/apt/keyrings, install GPG key from download.docker.com, add deb line for the current codename + arch), then installs `docker-ce docker-ce-cli containerd.io docker-compose-plugin python3 python3-venv python3-pip gdal-bin osmium-tool gpsd gpsd-clients git wget curl unzip`. The repo-add is idempotent (guarded on `-f /etc/apt/keyrings/docker.gpg`).

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_docker_install.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh tests/test_bootstrap_docker_install.py
git commit -m "$(cat <<'MSG'
fix(setup): install Docker Compose v2 plugin, not legacy v1 (B5)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+9 passed.

---

### Task 5: Detect cmdline.txt path; skip on non-Pi

**Files:**
- Modify: `bootstrap.sh:50-55`
- Test: `tests/test_bootstrap_cmdline.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_bootstrap_cmdline.py`:

```python
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_bootstrap_guards_cmdline_sed():
    text = BOOTSTRAP.read_text()
    assert "if [ -f /boot/firmware/cmdline.txt ]" in text or \
           '[ -f /boot/firmware/cmdline.txt ]' in text
    assert "/boot/cmdline.txt" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_cmdline.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix bootstrap.sh**

Replace the cgroup-memory block with this literal block (paste verbatim):

```bash
CMDLINE=""
if [ -f /boot/firmware/cmdline.txt ]; then
    CMDLINE=/boot/firmware/cmdline.txt
elif [ -f /boot/cmdline.txt ]; then
    CMDLINE=/boot/cmdline.txt
fi
if [ -n "$CMDLINE" ]; then
    if ! grep -q "cgroup_enable=memory" "$CMDLINE"; then
        sed -i 's/$/ cgroup_enable=memory cgroup_memory=1/' "$CMDLINE"
        echo "  Enabled cgroup memory controller via $CMDLINE (reboot required)"
        NEEDS_REBOOT=1
    fi
else
    echo "  [skip] cgroup memory enable: no cmdline.txt found (not a Raspberry Pi OS install — Docker memory limits may not work)"
fi
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_cmdline.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh tests/test_bootstrap_cmdline.py
git commit -m "$(cat <<'MSG'
fix(setup): detect cmdline.txt location before editing (B31)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+10 passed.

---

### Task 6: Fix data symlink creation

**Files:**
- Modify: `bootstrap.sh:69-70`
- Test: `tests/test_bootstrap_symlink.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_bootstrap_symlink.py`:

```python
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_symlink_uses_force_no_deref_and_preclean():
    text = BOOTSTRAP.read_text()
    assert 'rm -f "$REPO_DIR/data"' in text
    assert 'ln -sfn' in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_symlink.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix bootstrap.sh**

Replace lines 69-70 with this literal block. Note the guard — if `./data` exists as a real directory (not a symlink) we refuse to clobber it, since a user might have manually dropped files there:

```bash
echo "      Creating data symlink..."
# Create/update ./data symlink. If a real directory exists where ./data should be,
# refuse to clobber it — require manual cleanup.
if [ -e "$REPO_DIR/data" ] && [ ! -L "$REPO_DIR/data" ]; then
    echo "ERROR: $REPO_DIR/data exists as a regular directory. Remove it manually before re-running bootstrap."
    exit 1
fi
ln -sfn "$DATA_DIR" "$REPO_DIR/data"
```

(Update the corresponding test from Step 1 if the `rm -f` string was asserted — instead assert on `ln -sfn` + the guard message.)

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_symlink.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh tests/test_bootstrap_symlink.py
git commit -m "$(cat <<'MSG'
fix(setup): idempotent data symlink creation (B32)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+11 passed.

---

### Task 7: Non-recursive chown + explicit subdir chown

**Files:**
- Modify: `bootstrap.sh:64-67`
- Test: extend `tests/test_bootstrap_symlink.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append to `tests/test_bootstrap_symlink.py`:

```python
def test_no_recursive_chown_of_srv_root():
    text = BOOTSTRAP.read_text()
    assert "chown -R \"$ACTUAL_USER\":\"$ACTUAL_USER\" /srv/geographica" not in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_symlink.py::test_no_recursive_chown_of_srv_root -v`
Expected: FAIL.

- [ ] **Step 3: Fix bootstrap.sh**

Replace the chown block with this literal version. Do NOT use `-R` — docker-managed volumes (Nominatim UID 999 postgres, Valhalla UID 1000) would be clobbered to host-user ownership on rerun:

```bash
# Non-recursive chown of the top-level dir and the three immediate data subdirs.
# Do NOT chown recursively — container-owned data (UID 1000 valhalla, UID 999 postgres)
# would be clobbered to host-user ownership.
chown "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica 2>/dev/null || true
chown "$ACTUAL_USER":"$ACTUAL_USER" /srv/geographica/data 2>/dev/null || true
for sub in pbf nominatim valhalla; do
    [ -d "/srv/geographica/data/$sub" ] && \
        chown "$ACTUAL_USER":"$ACTUAL_USER" "/srv/geographica/data/$sub" 2>/dev/null || true
done
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_symlink.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh
git commit -m "$(cat <<'MSG'
fix(setup): scope bootstrap chown to top-level dirs only (B33)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+12 passed.

---

### Task 8: Create tools/build-tippecanoe.sh + release README

**Files:**
- Create: `tools/build-tippecanoe.sh` (executable)
- Create: `tools/README.md`
- Test: `tests/test_tippecanoe_build_script.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_tippecanoe_build_script.py`:

```python
import os
from pathlib import Path
REPO = Path(__file__).parent.parent
SCRIPT = REPO / "tools" / "build-tippecanoe.sh"


def test_script_exists():
    assert SCRIPT.exists()


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_script_references_version_and_arch():
    text = SCRIPT.read_text()
    assert "TIPPECANOE_VERSION" in text
    assert "aarch64" in text or "arm64" in text


def test_script_produces_tarball():
    text = SCRIPT.read_text()
    assert "tippecanoe-" in text and ".tar.gz" in text


def test_readme_documents_release_cut():
    readme = REPO / "tools" / "README.md"
    assert readme.exists()
    assert "gh release" in readme.read_text()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_tippecanoe_build_script.py -v`
Expected: 5 FAIL.

- [ ] **Step 3: Create files**

Create `tools/build-tippecanoe.sh` with this exact content (paste verbatim):

```bash
#!/bin/bash
# tools/build-tippecanoe.sh — Reproducibly build ARM64 Tippecanoe for release assets.
# Run this on a Pi or ARM64 VM. Output: ./tippecanoe-arm64 ready to upload.
set -euo pipefail

TIPPECANOE_VERSION="${TIPPECANOE_VERSION:-2.80.0}"
BUILD_DIR="${BUILD_DIR:-/tmp/tippecanoe-build}"
OUTPUT_DIR="${OUTPUT_DIR:-$(pwd)}"

# Verify we're on ARM64
ARCH="$(uname -m)"
if [ "$ARCH" != "aarch64" ] && [ "$ARCH" != "arm64" ]; then
    echo "ERROR: This script builds for aarch64/arm64. Current arch: $ARCH"
    exit 1
fi

# Install build dependencies
sudo apt update
sudo apt install -y build-essential libsqlite3-dev zlib1g-dev git

# Clone and build
rm -rf "$BUILD_DIR"
git clone --depth=1 --branch="$TIPPECANOE_VERSION" \
    https://github.com/felt/tippecanoe.git "$BUILD_DIR"
cd "$BUILD_DIR"
make -j"$(nproc)"

# Strip and install
strip tippecanoe
cp tippecanoe "$OUTPUT_DIR/tippecanoe-arm64"

# Also tar the secondary binaries so the release asset is complete.
tar -czf "$OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz" \
    tippecanoe tippecanoe-decode tile-join 2>/dev/null || true

echo "Built: $OUTPUT_DIR/tippecanoe-arm64 (v$TIPPECANOE_VERSION)"
if [ -f "$OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz" ]; then
    echo "Tarball: $OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz"
    sha256sum "$OUTPUT_DIR/tippecanoe-${TIPPECANOE_VERSION}-linux-${ARCH}.tar.gz"
fi
echo ""
echo "To cut a release:"
echo "  1. gh release create v<tag> $OUTPUT_DIR/tippecanoe-arm64"
echo "  2. Update the URL in bootstrap.sh's tippecanoe-install block"
```

Create `tools/README.md` explaining: run `./build-tippecanoe.sh` on a Pi or ARM64 VM, then cut a release via `gh release create v1.X.Y ./tippecanoe-arm64 ./tippecanoe-*.tar.gz`. Bump `TIPPECANOE_RELEASE_URL` in `bootstrap.sh` to the new tag.

Make executable: `chmod +x tools/build-tippecanoe.sh`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_tippecanoe_build_script.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/ tests/test_tippecanoe_build_script.py
git commit -m "$(cat <<'MSG'
feat(setup): reproducible ARM64 tippecanoe build tool (B21/B27)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+17 passed.

---

### Task 9: bootstrap installs Tippecanoe from GitHub Release

**Files:**
- Modify: `bootstrap.sh` (add step before keyring)
- Test: `tests/test_bootstrap_tippecanoe.py` (NEW)

**TDD preamble:** Read TDD skill. Pitfall: "Streaming download lacks Content-Length short-read detection" — use `curl -fL` to error on HTTP failures.

- [ ] **Step 1: Write failing test**

Create `tests/test_bootstrap_tippecanoe.py`:

```python
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_bootstrap_fetches_tippecanoe_release():
    text = BOOTSTRAP.read_text()
    assert "TIPPECANOE_RELEASE_URL" in text
    assert "github.com/cameronzucker/geographica/releases" in text
    assert "curl -fL" in text


def test_bootstrap_installs_to_usr_local_bin():
    assert "/usr/local/bin/tippecanoe" in BOOTSTRAP.read_text()


def test_bootstrap_tippecanoe_has_fallback_message():
    assert "build-tippecanoe.sh" in BOOTSTRAP.read_text()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_tippecanoe.py -v`
Expected: 3 FAIL.

- [ ] **Step 3: Modify bootstrap.sh**

Insert this literal block before the keyring step. The `[N/M]` step prefix is a placeholder; a separate sub-step at the end of Phase 1 renumbers all step prefixes across the script for consistency — this Task 9 itself should NOT renumber.

```bash
echo "[N/M] Installing Tippecanoe (ARM64 binary from GitHub Release)..."
# Pin to the Geographica release tag for reproducibility. Update this version when cutting a new release.
TIPPECANOE_RELEASE_URL="https://github.com/cameronzucker/geographica/releases/download/v1.1.0/tippecanoe-arm64"
if command -v tippecanoe >/dev/null 2>&1; then
    echo "  tippecanoe already installed ($(tippecanoe --version 2>&1 | head -1))"
else
    if wget -q --show-progress -O /tmp/tippecanoe "$TIPPECANOE_RELEASE_URL"; then
        chmod +x /tmp/tippecanoe
        mv /tmp/tippecanoe /usr/local/bin/tippecanoe
        echo "  Installed tippecanoe to /usr/local/bin/tippecanoe"
    else
        echo "  WARNING: Could not download tippecanoe from $TIPPECANOE_RELEASE_URL"
        echo "  Public lands pipeline will fail until you install tippecanoe manually:"
        echo "    Option A: sudo apt install build-essential libsqlite3-dev zlib1g-dev"
        echo "              git clone https://github.com/felt/tippecanoe.git /tmp/tippecanoe"
        echo "              cd /tmp/tippecanoe && make -j4 && sudo make install"
        echo "    Option B: Download a release asset from https://github.com/cameronzucker/geographica/releases"
        echo "    Option C: Build via ./tools/build-tippecanoe.sh (see tools/README.md)"
    fi
fi
```

Note: the Step 1 test asserts on `curl -fL` — if you prefer `curl -fL -o ...` over `wget`, swap the download line; either is acceptable but the test regex must match what you ship. Update the test from Step 1 as needed so it accepts either `curl -fL` or `wget -q` as the download mechanism.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_tippecanoe.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh
git commit -m "$(cat <<'MSG'
feat(setup): bootstrap installs tippecanoe from GitHub Release (B21/B27)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+20 passed.

---

### Task 10: bootstrap pip-installs scripts/requirements.txt

**Files:**
- Modify: `bootstrap.sh` (add step)
- Test: `tests/test_bootstrap_python_deps.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_bootstrap_python_deps.py`:

```python
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_bootstrap_installs_pipeline_python_deps():
    text = BOOTSTRAP.read_text()
    assert "scripts/requirements.txt" in text
    assert "pip install" in text
    assert 'sudo -u "$ACTUAL_USER"' in text
    assert "--break-system-packages" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_bootstrap_python_deps.py -v`
Expected: FAIL.

- [ ] **Step 3: Modify bootstrap.sh**

Add this literal block (paste verbatim). The `[N/M]` placeholder is normalized in a later sub-step:

```bash
echo "[N/M] Installing Python packages for data pipeline..."
if [ -f "$REPO_DIR/scripts/requirements.txt" ]; then
    # Install as the actual user (not root). break-system-packages is needed on
    # Debian Trixie+ which PEP 668 ships with an externally-managed marker.
    sudo -u "$ACTUAL_USER" pip install --user --break-system-packages -r "$REPO_DIR/scripts/requirements.txt"
    echo "  Pipeline Python packages installed for user $ACTUAL_USER"
else
    echo "  WARNING: $REPO_DIR/scripts/requirements.txt not found — pipeline scripts will fail at import time"
fi
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_bootstrap_python_deps.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add bootstrap.sh
git commit -m "$(cat <<'MSG'
feat(setup): bootstrap pip-installs pipeline deps as ACTUAL_USER (B21)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+21 passed.

**After Phase 1 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 2.

---

## Phase 2 — Env generation

### Task 11: generate_env emits full set of docker-compose env vars, drops HOST_IP

**Files:**
- Modify: `setup/config.py:323-365` (`generate_env`)
- Modify: `setup/main.py` (update `ConfigRequest` + `post_config`)
- Modify: `.env.example`
- Test: extend `tests/test_setup_config.py` with `TestEnvGenerationFull`; update legacy tests

**TDD preamble:** Read TDD skill. Review pitfall "Hardcoded dev-machine paths as docker-compose env defaults" + "Multi-layer enum values diverge silently".

- [ ] **Step 1: Write failing test**

Append to `tests/test_setup_config.py`:

```python
class TestEnvGenerationFull:
    def _env(self):
        from config import generate_env, RAM_PROFILE_16GB
        return generate_env(
            tls_mode="https",
            ram_profile=RAM_PROFILE_16GB,
            bbox="-124.8,31.3,-102.0,49.0",
            data_path="/srv/geographica/data",
            scripts_path="/home/pi/geographica/scripts",
            tls_cert_dir="/srv/geographica/tls",
            tls_port=443,
            stt_backend="cpu",
        )

    def test_has_data_host_path(self):
        assert "DATA_HOST_PATH=/srv/geographica/data" in self._env()

    def test_has_scripts_host_path(self):
        assert "SCRIPTS_HOST_PATH=/home/pi/geographica/scripts" in self._env()

    def test_has_tls_mode(self):
        assert "TLS_MODE=https" in self._env()

    def test_has_tls_cert_dir(self):
        assert "TLS_CERT_DIR=/srv/geographica/tls" in self._env()

    def test_has_tls_port(self):
        assert "TLS_PORT=443" in self._env()

    def test_has_stt_backend(self):
        assert "STT_BACKEND=cpu" in self._env()

    def test_has_postgres_work_mem(self):
        assert "POSTGRES_WORK_MEM=" in self._env()

    def test_has_postgres_autovacuum_work_mem(self):
        assert "POSTGRES_AUTOVACUUM_WORK_MEM=" in self._env()

    def test_has_nominatim_memory(self):
        assert "NOMINATIM_MEMORY=" in self._env()

    def test_has_valhalla_threads(self):
        assert "VALHALLA_THREADS=" in self._env()

    def test_does_not_emit_host_ip(self):
        assert "HOST_IP=" not in self._env()
```

Update `TestEnvGeneration::test_env_contains_required_keys_16gb` and `test_env_contains_required_keys_8gb` to use the new keyword-only signature and no longer pass `host_ip`; assert `TLS_MODE=tailscale|http`, `POSTGRES_SHARED_BUFFERS=...`, and `BBOX=...`.

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_config.py::TestEnvGenerationFull -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite generate_env + ConfigRequest + post_config + .env.example**

Replace the `RAM_PROFILE_16GB`, `RAM_PROFILE_8GB`, and `generate_env` definitions in `setup/config.py` with this literal block (paste verbatim):

```python
RAM_PROFILE_16GB = {
    "nominatim_memory": "8G",
    "postgres_shared_buffers": "2GB",
    "postgres_maintenance_work_mem": "1GB",
    "postgres_effective_cache_size": "6GB",
    "postgres_work_mem": "32MB",
    "postgres_autovacuum_work_mem": "256MB",
    "valhalla_memory": "4G",
    "valhalla_threads": "4",
    "tileserver_memory": "1G",
    "stt_memory": "1536M",
    "pipeline_memory": "4G",
    "pipeline_gdal_cache": "1024",
    "planetiler_heap": "4g",
}

RAM_PROFILE_8GB = {
    "nominatim_memory": "4G",
    "postgres_shared_buffers": "1GB",
    "postgres_maintenance_work_mem": "512MB",
    "postgres_effective_cache_size": "3GB",
    "postgres_work_mem": "16MB",
    "postgres_autovacuum_work_mem": "128MB",
    "valhalla_memory": "2G",
    "valhalla_threads": "2",
    "tileserver_memory": "768M",
    "stt_memory": "1G",
    "pipeline_memory": "2G",
    "pipeline_gdal_cache": "512",
    "planetiler_heap": "2g",
}


def generate_env(
    *,
    tls_mode: str,
    bbox: str,
    data_path: str,
    scripts_path: str,
    ram_profile: dict,
    tls_cert_dir: str = "./tls",
    tls_port: int = 443,
    stt_backend: str = "cpu",
) -> str:
    """Render a .env body. Keyword-only so call sites can't silently drift.

    Emits exactly the 21 keys the wizard owns. HOST_IP is NOT emitted (B40
    obsolete — the UI no longer asks for an IP, so the validation bug the
    original B40 flagged no longer applies). IMAGERY_CONCURRENCY_* and
    M2M_BATCH_SIZE are NOT emitted — they're placebo env vars that scripts
    read as module-level constants today; fixing that is out of scope (O1).
    """
    lines = [
        f"TLS_MODE={tls_mode}",
        f"TLS_CERT_DIR={tls_cert_dir}",
        f"TLS_PORT={tls_port}",
        f"BBOX={bbox}",
        f"DATA_HOST_PATH={data_path}",
        f"SCRIPTS_HOST_PATH={scripts_path}",
        f"STT_BACKEND={stt_backend}",
        f"NOMINATIM_MEMORY={ram_profile['nominatim_memory']}",
        f"POSTGRES_SHARED_BUFFERS={ram_profile['postgres_shared_buffers']}",
        f"POSTGRES_MAINTENANCE_WORK_MEM={ram_profile['postgres_maintenance_work_mem']}",
        f"POSTGRES_EFFECTIVE_CACHE_SIZE={ram_profile['postgres_effective_cache_size']}",
        f"POSTGRES_WORK_MEM={ram_profile['postgres_work_mem']}",
        f"POSTGRES_AUTOVACUUM_WORK_MEM={ram_profile['postgres_autovacuum_work_mem']}",
        f"VALHALLA_MEMORY={ram_profile['valhalla_memory']}",
        f"VALHALLA_THREADS={ram_profile['valhalla_threads']}",
        f"TILESERVER_MEMORY={ram_profile['tileserver_memory']}",
        f"STT_MEMORY={ram_profile['stt_memory']}",
        f"PIPELINE_MEMORY={ram_profile['pipeline_memory']}",
        f"PIPELINE_GDAL_CACHE={ram_profile['pipeline_gdal_cache']}",
        f"PLANETILER_HEAP={ram_profile['planetiler_heap']}",
        "GPS_DEVICE=/dev/ttyAMA0",
    ]
    return "\n".join(lines) + "\n"
```

Update `setup/main.py::ConfigRequest`:

```python
class ConfigRequest(BaseModel):
    tls_mode: str
    bbox: str
    data_path: str
    scripts_path: str = ""
    tls_cert_dir: str = "./tls"
    tls_port: int = 443
    stt_backend: str = "cpu"
```

Update `post_config` to derive `scripts_path` from `Path(__file__).parent.parent / "scripts"` when the client sends empty string, pass all new fields to `generate_env` as keyword args.

Update `.env.example` to match the new schema exactly (21 keys above). Replace the TLS_MODE header comment block with `# TLS_MODE: http | https | tailscale`. Drop HOST_IP, IMAGERY_CONCURRENCY_*, M2M_BATCH_SIZE entirely.

Update `tests/test_setup_main.py::TestConfigEndpoint::test_config_writes_env` to drop `host_ip` from the request body and assert `DATA_HOST_PATH=/srv/geographica/data` appears in the file.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_config.py tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/config.py setup/main.py .env.example tests/test_setup_config.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): emit every docker-compose VAR from generate_env; drop HOST_IP (B2/B3/B11/B29)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+32 passed.

**B40 obsolescence:** HOST_IP field removed entirely (D6). The `ipaddress.ip_address()` validation this bug requested is no longer needed because no UI asks for an IP.

---

### Task 12: docker-compose memory limits via env vars

**Files:**
- Modify: `docker-compose.yml`
- Test: `tests/test_docker_compose_env.py` (NEW)

**TDD preamble:** Read TDD skill. Pitfall references: `dev/testing-pitfalls.md` — RAM profile placebo; also `docs/pitfalls/implementation-pitfalls.md` — Pi 5 memory budget entry (if present). Add a Step 1 assertion test that the SUM of all per-service memory-limit ceilings in the 16GB profile is ≤ 14 GB (leaves 2 GB for the host kernel, nginx, and the setup wizard itself): `nominatim_memory + valhalla_memory + tileserver_memory + stt_memory + pipeline_memory ≤ 14336 MB`. This catches the bug class where a future RAM-profile tweak silently oversubscribes the Pi.

- [ ] **Step 1: Write failing test**

Create `tests/test_docker_compose_env.py`:

```python
import re
from pathlib import Path
COMPOSE = Path(__file__).parent.parent / "docker-compose.yml"


def test_memory_limits_are_env_parameterized():
    text = COMPOSE.read_text()
    pattern = re.compile(r"^\s*memory:\s*(?!\"?\$\{)(\S+)", re.MULTILINE)
    bad = pattern.findall(text)
    allowed_fixed = {"128M", "256M"}
    unexpected = [b for b in bad if b not in allowed_fixed]
    assert not unexpected, f"hard-coded memory limits: {unexpected}"


def test_required_vars_present():
    text = COMPOSE.read_text()
    for var in ("${TILESERVER_MEMORY", "${VALHALLA_MEMORY", "${NOMINATIM_MEMORY",
                "${STT_MEMORY", "${PIPELINE_MEMORY"):
        assert var in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_docker_compose_env.py -v`
Expected: FAIL.

- [ ] **Step 3: Update docker-compose.yml**

Replace hard-coded memory limits for tileserver (`memory: 1G` -> `memory: "${TILESERVER_MEMORY:-1G}"`), valhalla (-> `"${VALHALLA_MEMORY:-4G}"`), nominatim (-> `"${NOMINATIM_MEMORY:-8G}"`), stt (-> `"${STT_MEMORY:-1536M}"`), pipeline (-> `"${PIPELINE_MEMORY:-4G}"`). gps/search/frontend stay at fixed 128M/256M.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_docker_compose_env.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml tests/test_docker_compose_env.py
git commit -m "$(cat <<'MSG'
fix(setup): parameterize container memory limits (B30)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+34 passed.

---

### Task 13: Pin Planetiler version to 0.10.2

**Files:**
- Modify: `setup/runner.py:52-65` (planetiler_cmd)
- Test: `tests/test_setup_runner.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_setup_runner.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.runner import planetiler_cmd, PLANETILER_VERSION


class TestPlanetilerPin:
    def test_version_constant_is_pinned(self):
        assert PLANETILER_VERSION == "0.10.2"

    def test_docker_image_tag_matches_version(self):
        cmd = planetiler_cmd("/tmp/a.osm.pbf", "/tmp/out.mbtiles", "4g")
        image = [a for a in cmd if "planetiler" in a][-1]
        assert image.endswith(":0.10.2")
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_runner.py::TestPlanetilerPin -v`
Expected: FAIL.

- [ ] **Step 3: Fix runner.py**

Add `PLANETILER_VERSION = "0.10.2"` at the top. Update the image ref in `planetiler_cmd` to `f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}"`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_runner.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add setup/runner.py tests/test_setup_runner.py
git commit -m "$(cat <<'MSG'
fix(setup): pin Planetiler to 0.10.2 (B28)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+36 passed.

**After Phase 2 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 3.

---

## Phase 3 — TLS vocabulary

### Task 14: Canonicalize http|https|tailscale across UI, JS, config, nginx

**Files:**
- Modify: `setup/static/index.html:42-48`
- Modify: `setup/static/setup.js:273-305, 500-509, 879-888`
- Modify: `setup/main.py` (delete /api/tls/generate + /api/tls/scan)
- Verify: `.env.example` already uses canonical values from Task 11
- Test: `tests/test_tls_mode_roundtrip.py` (NEW)

**TDD preamble:** Read TDD skill. Review pitfall "Multi-layer enum values diverge silently" — this task implements the round-trip test the pitfall prescribes.

- [ ] **Step 1: Write failing test**

Create `tests/test_tls_mode_roundtrip.py`:

```python
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
REPO = Path(__file__).parent.parent
INDEX_HTML = REPO / "setup" / "static" / "index.html"
ENTRYPOINT = REPO / "nginx" / "entrypoint.sh"

CANONICAL = {"http", "https", "tailscale"}


def _ui_values():
    text = INDEX_HTML.read_text()
    sel = re.search(r'<select id="tls-mode">(.*?)</select>', text, re.DOTALL)
    assert sel
    return set(re.findall(r'value="([^"]+)"', sel.group(1)))


def _nginx_values():
    text = ENTRYPOINT.read_text()
    return set(re.findall(r'\[\s*"\$TLS_MODE"\s*=\s*"([^"]+)"\s*\]', text))


def test_ui_values_are_canonical():
    assert _ui_values() <= CANONICAL


def test_ui_values_subset_of_nginx():
    ui = _ui_values() - {"http"}
    assert ui <= _nginx_values()


def test_generate_env_roundtrip():
    from setup.config import generate_env, RAM_PROFILE_16GB
    for mode in CANONICAL:
        env = generate_env(
            tls_mode=mode, ram_profile=RAM_PROFILE_16GB,
            bbox="-124.8,31.3,-102.0,49.0",
            data_path="/srv/geographica/data",
            scripts_path="/home/pi/geographica/scripts",
            tls_cert_dir="/srv/geographica/tls",
            tls_port=443, stt_backend="cpu",
        )
        assert f"TLS_MODE={mode}" in env
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_tls_mode_roundtrip.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix three files**

`setup/static/index.html` — replace the tls-mode `<select>` options with these three literal entries (paste verbatim):

```html
<option value="http">HTTP (no encryption)</option>
<option value="https">HTTPS (self-signed cert, generated at launch)</option>
<option value="tailscale">Tailscale (Let's Encrypt via ts.net)</option>
```

`setup/static/setup.js::onTlsModeChange` — replace the body with this literal function (paste verbatim):

```javascript
function onTlsModeChange() {
    var mode = $('#tls-mode').value;
    var hint = $('#tls-hint');
    if (mode === 'https') {
        hint.textContent = 'A self-signed certificate will be generated on first launch. Browsers will show a security warning you must accept.';
    } else if (mode === 'tailscale') {
        hint.textContent = 'Requires: sudo ./scripts/provision_tailscale_tls.sh (see README Tailscale section).';
    } else {
        hint.textContent = '';
    }
}
```

Drop the `/api/tls/scan` call. Delete any references to `tls-cert-group` show/hide beyond a static `display:none`.

Note (no code change): `nginx/entrypoint.sh` already auto-generates a self-signed cert when `TLS_MODE=https` and no cert is found at the mount. No `/api/tls/generate` endpoint is needed — that's why Task 14 deletes it.

In `renderHealth`, build the completion link as: proto = `http` when `config.tls_mode === 'http'` else `https`; host = `location.hostname`; port = `:8093` for http, empty for https/tailscale.

`setup/main.py` — delete the `@app.post("/api/tls/generate")` handler AND the `@app.post("/api/tls/scan")` handler entirely (original lines 317-368). Remove `TlsGenerateRequest` / `TlsScanRequest` models if present. Remove corresponding tests from `tests/test_setup_main.py` (any `TestTlsGenerate*` or `TestTlsScan*` classes).

`.env.example` — replace the `TLS_MODE=http` comment block with:

```
# TLS_MODE: http | https | tailscale
TLS_MODE=http
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_tls_mode_roundtrip.py tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/static/index.html setup/static/setup.js setup/main.py tests/test_tls_mode_roundtrip.py
git commit -m "$(cat <<'MSG'
fix(setup): canonicalize TLS modes to http|https|tailscale (B1/B19)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+39 passed.

---

### Task 15: README Tailscale idempotent sed

**Files:**
- Modify: `README.md:557-559`
- Test: `tests/test_readme_tailscale.py` (NEW)

**TDD preamble:** Read TDD skill. Pitfall reference: `dev/testing-pitfalls.md` — "Multi-layer enum values diverge silently" (TLS_MODE key must stay in sync across .env, UI select, nginx entrypoint).

- [ ] **Step 1: Write failing test**

Create `tests/test_readme_tailscale.py`:

```python
from pathlib import Path
README = Path(__file__).parent.parent / "README.md"


def test_tailscale_uses_sed_not_append():
    text = README.read_text()
    idx = text.lower().find("tailscale")
    assert idx != -1
    section = text[idx:idx + 1200]
    assert 'echo "TLS_MODE=tailscale" >> .env' not in section
    assert "sed -i" in section or "sed -E" in section
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_readme_tailscale.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix README**

Replace the Tailscale shell snippet in README.md with this literal block (paste verbatim inside the existing bash fence). The pattern is idempotent: if `TLS_MODE=` is already present in `.env`, rewrite it; otherwise append:

```bash
# Replace the existing echo '>>' lines with grep+sed:
grep -q "^TLS_MODE=" .env && sed -i 's/^TLS_MODE=.*/TLS_MODE=tailscale/' .env || echo 'TLS_MODE=tailscale' >> .env
grep -q "^TLS_CERT_DIR=" .env && sed -i 's|^TLS_CERT_DIR=.*|TLS_CERT_DIR=/srv/geographica/tls/tailscale|' .env || echo 'TLS_CERT_DIR=/srv/geographica/tls/tailscale' >> .env
```

The block goes into the README verbatim (not just in the plan).

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_readme_tailscale.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add README.md tests/test_readme_tailscale.py
git commit -m "$(cat <<'MSG'
docs: idempotent Tailscale TLS_MODE swap (B38)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+40 passed.

**After Phase 3 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 4.

---

## Phase 4 — Install-location UI

### Task 16: detect_storage filters against allowlist boundary

**Files:**
- Modify: `setup/config.py:203-250`
- Test: extend `tests/test_setup_config.py` with `TestStorageDetectionAllowlist`

**TDD preamble:** Read TDD skill. Pitfall: "String-prefix path allowlists permit sibling-with-same-prefix".

- [ ] **Step 1: Write failing test**

Append:

```python
class TestStorageDetectionAllowlist:
    def test_no_mounts_fail_validate_path(self):
        from config import detect_storage, validate_path
        for entry in detect_storage():
            candidate = (
                entry["path"] if entry["path"] != "/"
                else "/srv/geographica/data"
            )
            test_path = (candidate + "/geographica/data"
                         if candidate != "/srv/geographica/data"
                         else candidate)
            res = validate_path(test_path)
            assert res["valid"], (
                f"unusable mount {entry['path']}: {res}"
            )
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_config.py::TestStorageDetectionAllowlist -v`
Expected: FAIL on systems with non-allowlist mounts.

- [ ] **Step 3: Fix detect_storage**

After `seen_devices.add(device)`, skip any mount_path that isn't `/` and isn't exactly-equal-to or a child-of (`prefix + os.sep`) any `ALLOWED_PATH_PREFIXES` entry.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_config.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/config.py tests/test_setup_config.py
git commit -m "$(cat <<'MSG'
fix(setup): filter detect_storage through allowlist (B41)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+41 passed.

---

### Task 17: validate_path prefix boundary fix

**Files:**
- Modify: `setup/config.py:286-292`
- Test: extend `TestValidatePath`

**TDD preamble:** Read TDD skill. Pitfall: "String-prefix path allowlists".

- [ ] **Step 1: Write failing test**

Append to `TestValidatePath`:

```python
    def test_rejects_srvattacker(self):
        from config import validate_path
        assert validate_path("/srvattacker/malicious")["valid"] is False

    def test_rejects_homeroot(self):
        from config import validate_path
        assert validate_path("/homeroot/x")["valid"] is False

    def test_rejects_bare_srv(self):
        from config import validate_path
        assert validate_path("/srv")["valid"] is False

    def test_accepts_srv_subpath(self):
        from config import validate_path
        assert validate_path("/srv/anything")["valid"] is True
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_config.py::TestValidatePath -v`
Expected: FAIL on 3 of 4.

- [ ] **Step 3: Fix validate_path**

Replace the allowlist startswith check with a helper `_under(path, prefix)` that returns `path.startswith(prefix + os.sep)` (false for bare-prefix paths). Apply to both the resolved-path and original-path checks.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_config.py::TestValidatePath -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/config.py tests/test_setup_config.py
git commit -m "$(cat <<'MSG'
fix(setup): enforce path-boundary in validate_path (B34)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+45 passed.

---

### Task 18: validate_path symlink check walks original components

**Files:**
- Modify: `setup/config.py:294-299`
- Test: extend `TestValidatePath`

**TDD preamble:** Read TDD skill. Pitfall reference: `dev/testing-pitfalls.md` — "String-prefix path allowlists permit sibling-with-same-prefix".

- [ ] **Step 1: Write failing test**

Append:

```python
    def test_rejects_symlink_under_home(self, tmp_path, monkeypatch):
        import config as cfg
        monkeypatch.setattr(cfg, "ALLOWED_PATH_PREFIXES",
                            tuple(list(cfg.ALLOWED_PATH_PREFIXES) + [str(tmp_path)]))
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real_dir)
        res = cfg.validate_path(str(link / "data"))
        assert res["valid"] is False
        assert "symlink" in res["reason"].lower()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_config.py -v`
Expected: FAIL on new test.

- [ ] **Step 3: Fix symlink walk**

Replace the dead-code symlink check with a walk over components of the ORIGINAL `path_str` (not resolved). For each existing ancestor, if `is_symlink()` returns True, reject with `"Path contains a symlink, which is not allowed"`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_config.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/config.py tests/test_setup_config.py
git commit -m "$(cat <<'MSG'
fix(setup): walk original path for symlink check (B35)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+46 passed.

---

### Task 19: Step 1 HTML — drive + subpath + custom-path, drop host-ip

**Files:**
- Modify: `setup/static/index.html:27-73`
- Test: `tests/test_setup_index_html.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_setup_index_html.py`:

```python
from pathlib import Path
INDEX = Path(__file__).parent.parent / "setup" / "static" / "index.html"


def test_step1_has_data_drive_select():
    assert 'id="data-drive"' in INDEX.read_text()


def test_step1_has_data_subpath_input():
    assert 'id="data-subpath"' in INDEX.read_text()


def test_step1_has_data_custom_path_input():
    assert 'id="data-custom-path"' in INDEX.read_text()


def test_step1_has_data_path_hint_span():
    assert 'id="data-path-hint"' in INDEX.read_text()


def test_step1_removes_host_ip_field():
    assert 'id="host-ip"' not in INDEX.read_text()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_index_html.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite Step 1 HTML**

Remove host-ip field and its hint. Keep tls-mode select (already canonicalized in Task 14). Keep RAM profile display. Replace the single data-path dropdown with two field-groups: (a) drive select `#data-drive` with an `__other__` option, plus subpath input `#data-subpath` (default `geographica/data`) wrapped in `#data-subpath-group`; (b) custom-path input `#data-custom-path` wrapped in `#data-custom-group` (hidden by default). Add a shared `#data-path-hint` span below.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_index_html.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add setup/static/index.html tests/test_setup_index_html.py
git commit -m "$(cat <<'MSG'
feat(setup): two-control install-location UI; drop HOST_IP field (D1/D6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+51 passed.

---

### Task 20: Step 1 JS — drive change handler + debounced path validation + create-directory on Next

**Files:**
- Modify: `setup/static/setup.js:21-33, 154-164, 222-270, 500-509`
- Test: `tests/test_setup_js.py` (NEW)

**TDD preamble:** Read TDD skill. Review pitfall "Fire-and-forget async save from UI that silently swallows server errors" — block Next until validate-path resolves.

- [ ] **Step 1: Write failing test**

Create `tests/test_setup_js.py`:

```python
from pathlib import Path
JS = Path(__file__).parent.parent / "setup" / "static" / "setup.js"


def test_has_data_drive_listener():
    text = JS.read_text()
    assert "data-drive" in text and "addEventListener" in text


def test_resolves_full_data_path():
    text = JS.read_text()
    assert "data-subpath" in text
    assert "data-custom-path" in text


def test_calls_create_directory_on_next():
    assert "/api/create-directory" in JS.read_text()


def test_debounced_validate_path():
    assert "/api/validate-path" in JS.read_text()


def test_no_host_ip_in_config_object():
    assert "host_ip:" not in JS.read_text()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite Step 1 JS**

Update the `config` object: drop `host_ip`; add `layer_bbox: { basemap: '', base_imagery: '', detail_imagery: '' }`.

Rewrite `loadSystemInfo`: populate `#data-drive` from `systemInfo.storage`, always append `__other__` sentinel option, parse an optional `existing_env_parsed` field to pre-fill TLS/data values, call `onDataDriveChange()` at the end.

Add the following helpers as literal function bodies (paste verbatim):

```javascript
// Read the drive select + subpath/custom-path fields and return the full
// resolved data path. Returns empty string if nothing is selected.
function computeDataPath() {
    var drive = $('#data-drive').value;
    if (!drive) return '';
    if (drive === '__other__') {
        return ($('#data-custom-path').value || '').trim();
    }
    var subpath = ($('#data-subpath').value || 'geographica/data').trim().replace(/^\/+/, '');
    return drive.replace(/\/+$/, '') + '/' + subpath;
}

// Show/hide subpath-group vs custom-group based on current drive value.
function onDataDriveChange() {
    var drive = $('#data-drive').value;
    var subpathGroup = $('#data-subpath-group');
    var customGroup = $('#data-custom-group');
    if (drive === '__other__') {
        subpathGroup.style.display = 'none';
        customGroup.style.display = '';
    } else {
        subpathGroup.style.display = '';
        customGroup.style.display = 'none';
    }
    debouncedValidatePath();
}

// 400ms-debounced POST to /api/validate-path. Writes the result to
// #data-path-hint with an ok/warning/error CSS class.
var _validatePathTimer = null;
function debouncedValidatePath() {
    if (_validatePathTimer) clearTimeout(_validatePathTimer);
    _validatePathTimer = setTimeout(function () {
        var path = computeDataPath();
        var hint = $('#data-path-hint');
        if (!path) {
            hint.textContent = '';
            hint.className = 'field-hint';
            return;
        }
        api('POST', '/api/validate-path', { path: path })
            .then(function (res) {
                if (res.valid) {
                    hint.textContent = 'Path OK — will be created on Next if missing.';
                    hint.className = 'field-hint ok';
                } else {
                    hint.textContent = 'Invalid: ' + (res.reason || 'path not allowed');
                    hint.className = 'field-hint error';
                }
            })
            .catch(function (err) {
                hint.textContent = 'Validation check failed: ' + err.message;
                hint.className = 'field-hint warning';
            });
    }, 400);
}
```

Rewrite the Step 1 branch of `nextStep()` as a literal async chain (paste verbatim):

```javascript
// Step 1 branch of nextStep — runs when currentStep === 1.
if (currentStep === 1) {
    config.tls_mode = $('#tls-mode').value;
    var path = computeDataPath();
    if (!path) {
        showError('Please select a data drive and enter a subpath (or choose "Other" and enter a custom path).');
        return;
    }
    return api('POST', '/api/validate-path', { path: path })
        .then(function (res) {
            if (!res.valid) {
                showError('Invalid data path: ' + (res.reason || 'path rejected'));
                throw new Error('validate-path rejected');
            }
            return api('POST', '/api/create-directory', { path: path });
        })
        .then(function () {
            config.data_path = path;
            showStep(currentStep + 1);
        })
        .catch(function (err) {
            if (!/rejected/.test(err.message)) {
                showError('Could not create data directory: ' + err.message);
            }
        });
}
```

Update `saveConfig` to POST tls_mode, bbox, data_path, scripts_path='', tls_cert_dir='./tls', tls_port=443, stt_backend='cpu'.

Add `init()` listeners: `#data-drive` change → `onDataDriveChange`; `#data-subpath` input → `debouncedValidatePath`; `#data-custom-path` input → `debouncedValidatePath`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add setup/static/setup.js tests/test_setup_js.py
git commit -m "$(cat <<'MSG'
feat(setup): drive+subpath+custom path UI, debounced validation (D1/B9)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+56 passed.

---

### Task 21: /api/launch re-targets ./data symlink to DATA_HOST_PATH

**Files:**
- Modify: `setup/main.py:525-579`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall reference: inline note — "Destructive symlink retarget without backup" (if the existing ./data target holds data from a prior run, unlinking + re-pointing must be deliberate, not automatic). This is a candidate to add to `dev/testing-pitfalls.md` in a future cycle; for now, just be careful — reject with a clear error when `./data` is a regular directory (not a symlink) containing files.

- [ ] **Step 1: Write failing test**

Append:

```python
class TestLaunchReTargetsSymlink:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_launch_repoints_data_symlink(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        env_file = repo_root / ".env"
        new_data = tmp_path / "custom_data"
        new_data.mkdir()
        env_file.write_text(f"DATA_HOST_PATH={new_data}\n")
        old_data = tmp_path / "old_data"
        old_data.mkdir()
        (repo_root / "data").symlink_to(old_data)

        from setup import main as mod
        monkeypatch.setattr(mod, "ENV_PATH", str(env_file))

        async def fake_run(args, cwd, on_output, env_extra=None):
            return 0
        monkeypatch.setattr(mod, "run_command", fake_run)

        async def fake_exec(*args, **kwargs):
            class P:
                returncode = 0
                async def communicate(self):
                    return (b"", b"")
            return P()
        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)

        monkeypatch.chdir(repo_root)
        resp = self.client.post("/api/launch", headers=self.headers)
        assert resp.status_code == 200
        assert (repo_root / "data").resolve() == new_data.resolve()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestLaunchReTargetsSymlink -v`
Expected: FAIL.

- [ ] **Step 3: Update post_launch**

Before the pre_check subprocess call, parse `.env` for `DATA_HOST_PATH=`, and if found: unlink existing `./data` (symlink or directory, guarded), `mkdir -p` the target path, `symlink_to(target)`. Raise HTTPException 500 on OSError with the target in the detail.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py::TestLaunchReTargetsSymlink -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): launch re-targets ./data symlink to DATA_HOST_PATH (B2)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+57 passed.

---

### Task 22: Completion link via window.location.hostname

**Files:**
- Verify: `setup/static/setup.js:879-888` (changed in Task 14)
- Test: extend `tests/test_setup_js.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append:

```python
def test_completion_link_uses_location_hostname():
    assert "location.hostname" in JS.read_text()


def test_completion_link_http_port_8093():
    assert ":8093" in JS.read_text()


def test_completion_link_https_no_explicit_port():
    # https mode uses default :443 — no hardcoded explicit port required.
    text = JS.read_text()
    # Must branch on tls_mode when adding port
    assert "config.tls_mode" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: Should pass if Task 14 landed correctly; otherwise adjust.

- [ ] **Step 3: Verify/adjust setup.js**

Ensure `renderHealth` builds the completion link from `location.hostname` with port `:8093` only for http mode, blank for https/tailscale.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/static/setup.js tests/test_setup_js.py
git commit -m "$(cat <<'MSG'
test(setup): lock completion link URL construction (B39)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+60 passed.

**After Phase 4 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 5.

---

## Phase 5 — Credentials via keyring

### Task 23: Rewrite post_credentials to write through keyring Unix socket

**Files:**
- Modify: `setup/main.py:65, 136-141, 302-314`
- Modify: `setup/static/index.html:181-215` (rename Copernicus inputs)
- Modify: `setup/static/setup.js:489-528`
- Test: rewrite `tests/test_setup_main.py::TestCredentialsEndpoint` as `TestCredentialsEndpointKeyring`

**TDD preamble:** Read TDD skill. Pitfall reference: `dev/testing-pitfalls.md` — "Fire-and-forget async save from UI that silently swallows server errors" (the `.catch → showError` wiring in Step 3 is exactly this pitfall's prescribed fix).

- [ ] **Step 1: Write failing test**

Replace the old `TestCredentialsEndpoint` with a `TestCredentialsEndpointKeyring` class that: spins up a fake Unix-socket agent in a background thread, monkeypatches `setup.main.KEYRING_SOCKET_PATH`, and asserts:

- `test_credentials_go_to_keyring_socket` — POST with all four fields results in four store actions `(m2m,username), (m2m,token), (copernicus,username), (copernicus,password)`.
- `test_credentials_skips_empty_values` — POST with only m2m_username results in exactly one store action.
- `test_credentials_surfaces_socket_failure` — when socket path doesn't exist, endpoint returns 503 with "systemctl" in detail.

Also remove the top-of-file `from setup.main import ... CREDENTIALS_PATH ...` since the constant no longer exists.

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestCredentialsEndpointKeyring -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite post_credentials**

In `setup/main.py`:

- Delete the `CREDENTIALS_PATH = ...` constant.
- Add `KEYRING_SOCKET_PATH = "/run/geographica/keyring.sock"` near the other module constants.
- Rewrite `CredentialsRequest` to `(m2m_username, m2m_token, copernicus_username, copernicus_password)`, each `str = ""`.
- Replace the `post_credentials` handler with this literal body (paste verbatim):

```python
async def _write_to_keyring(cred_type: str, fields: dict[str, str]) -> None:
    """Send store-actions to the keyring agent over its Unix socket.

    Raises HTTPException(503) if the socket is unavailable — surfaces the
    'did you forget to start the keyring agent?' case to the user.
    Raises HTTPException(500) if the agent responds with ok=False.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(KEYRING_SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Keyring agent not reachable at {KEYRING_SOCKET_PATH} ({e}). "
                "Start it with: sudo systemctl start geographica-keyring"
            ),
        )
    try:
        for key, value in fields.items():
            if not value:
                continue  # skip empty values — don't clobber the stored entry
            msg = json.dumps({
                "action": "store",
                "type": cred_type,
                "key": key,
                "value": value,
            }) + "\n"
            writer.write(msg.encode("utf-8"))
            await writer.drain()
            resp_line = await reader.readline()
            if not resp_line:
                raise HTTPException(status_code=500,
                                    detail=f"keyring agent closed socket mid-write ({cred_type}/{key})")
            resp = json.loads(resp_line.decode("utf-8"))
            if not resp.get("ok"):
                raise HTTPException(
                    status_code=500,
                    detail=f"keyring agent rejected {cred_type}/{key}: {resp.get('error', 'unknown')}",
                )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


@app.post("/api/credentials")
async def post_credentials(body: CredentialsRequest,
                           x_csrf_token: str = Header(None)):
    if x_csrf_token != CSRF_TOKEN:
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
    await _write_to_keyring("m2m", {
        "username": body.m2m_username,
        "token": body.m2m_token,
    })
    await _write_to_keyring("copernicus", {
        "username": body.copernicus_username,
        "password": body.copernicus_password,
    })
    return {"ok": True}
```

Add `import json` at module-top if absent.

In `setup/static/index.html`: rename Copernicus inputs to `copernicus-username` / `copernicus-password`; update labels and placeholders.

In `setup/static/setup.js::saveCredentials`: read from the renamed inputs; only POST if any value is non-empty; return the Promise (don't swallow). Wire the `.catch` branch to call `showError`:

```javascript
function saveCredentials() {
    var m2mU = ($('#m2m-username').value || '').trim();
    var m2mT = ($('#m2m-token').value || '').trim();
    var copU = ($('#copernicus-username').value || '').trim();
    var copP = ($('#copernicus-password').value || '').trim();
    if (!m2mU && !m2mT && !copU && !copP) {
        return Promise.resolve({ ok: true, skipped: true });
    }
    return api('POST', '/api/credentials', {
        m2m_username: m2mU, m2m_token: m2mT,
        copernicus_username: copU, copernicus_password: copP,
    }).catch(function (err) {
        showError('Credentials save failed: ' + err.message +
                  ' — is the keyring agent running? Try: sudo systemctl start geographica-keyring');
        throw err;
    });
}
```

**Test fixture:** Add this fake keyring server fixture to `tests/test_setup_main.py`. Subagents should spin it up in a background thread, monkeypatch `setup.main.KEYRING_SOCKET_PATH` to its path, and assert `captured_messages` contains the expected records.

```python
import asyncio
import json
import os
import threading

def fake_keyring_server(socket_path: str, captured_messages: list):
    """Listen on a Unix socket, append each JSON line to captured_messages,
    and respond with {'ok': true}. Runs until stop_event is set by caller."""
    async def _handle(reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = json.loads(line.decode("utf-8"))
                captured_messages.append(msg)
                writer.write(json.dumps({"ok": True}).encode("utf-8") + b"\n")
                await writer.drain()
        finally:
            writer.close()

    async def _main():
        try:
            os.unlink(socket_path)
        except FileNotFoundError:
            pass
        server = await asyncio.start_unix_server(_handle, path=socket_path)
        async with server:
            await server.serve_forever()

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=lambda: loop.run_until_complete(_main()), daemon=True)
    t.start()
    return loop, t
```

**B26 coverage:** The `showError` wiring in `saveCredentials` above is exactly what B26 (credentials error surface) requires — any failure from the keyring-socket round trip is now visible to the user AND actionable (tells them to start the systemctl unit). B26 is therefore fully covered by Task 23 and doesn't need a separate task.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py setup/static/index.html setup/static/setup.js tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): write credentials through keyring Unix socket (B6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+63 passed.

**After Phase 5 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 6.

---

## Phase 6 — Pipeline + structured steps + concurrency

### Task 24: Create setup/pipeline_steps.py (dataclass + registry)

**Files:**
- Create: `setup/pipeline_steps.py`
- Test: `tests/test_pipeline_steps.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_pipeline_steps.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.pipeline_steps import (
    PipelineStep, ALL_PIPELINE_STEPS, filter_active_steps,
)


def test_step_dataclass_is_frozen():
    import dataclasses
    assert dataclasses.is_dataclass(PipelineStep)
    fields = {f.name for f in dataclasses.fields(PipelineStep)}
    assert {"id", "label", "cmd_builder", "required_deps",
            "required_creds", "skippable_by"} <= fields


def test_registry_has_all_13_steps():
    ids = [s.id for s in ALL_PIPELINE_STEPS]
    assert len(ids) == 13
    for expected in [
        "osm_download", "osm_merge", "osm_copy", "planetiler_pull",
        "planetiler_build", "poi_build", "osm_pois", "public_lands",
        "elevation", "base_imagery", "detail_imagery", "fonts", "docker_build",
    ]:
        assert expected in ids


def test_filter_skips_basemap_steps_when_basemap_skipped():
    active = filter_active_steps(ALL_PIPELINE_STEPS, {"basemap": "skip",
        "base_imagery": "naip", "detail_imagery": "m2m", "elevation": "download"})
    ids = [s.id for s in active]
    assert "planetiler_build" not in ids
    assert "poi_build" not in ids


def test_filter_skips_detail_imagery_when_skipped():
    active = filter_active_steps(ALL_PIPELINE_STEPS, {"basemap": "download",
        "base_imagery": "naip", "detail_imagery": "skip", "elevation": "download"})
    ids = [s.id for s in active]
    assert "detail_imagery" not in ids
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_pipeline_steps.py -v`
Expected: import failure.

- [ ] **Step 3: Create setup/pipeline_steps.py**

Create the file with this exact content (paste verbatim). The file must include a `PipelineContext` TypedDict so downstream builders have a typed contract, and each `cmd_builder` must be a callable that raises `NotImplementedError` until Task 25 wires real builders — use the `_raise` helper pattern rather than bare Ellipsis (which would silently pass type checks but crash on call with a confusing `'ellipsis' object is not callable`):

```python
"""Structured pipeline-step registry (D5)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Tuple, TypedDict


class PipelineContext(TypedDict):
    bbox: str                      # basemap-level bbox (fallback for layers without override)
    layer_bbox: dict[str, str]     # per-layer bbox override (key = layer name)
    layers: dict[str, str]         # per-layer source choice
    data_path: str                 # host path for data output (from Step 1)
    scripts_path: str              # host path for scripts directory (= repo_root/scripts)
    base_imagery_zoom: int         # from Step 2 slider (default 15)


def _raise(msg: str):
    """Return a callable that raises NotImplementedError when invoked.
    Used for cmd_builder placeholders that Task 25 replaces with real builders."""
    def _inner(ctx: PipelineContext):
        raise NotImplementedError(msg)
    return _inner


@dataclass(frozen=True)
class PipelineStep:
    id: str
    label: str
    cmd_builder: Callable[[PipelineContext], list[str]]
    required_deps: Tuple[str, ...]
    required_creds: Tuple[str, ...]
    skippable_by: Tuple[str, ...]  # layer keys; if any == 'skip', omit step


ALL_PIPELINE_STEPS: Tuple[PipelineStep, ...] = (
    PipelineStep("osm_download", "Download OSM data",
                 _raise("cmd builder for osm_download not yet implemented — see Task 25"),
                 ("wget",), (), ("basemap",)),
    PipelineStep("osm_merge", "Merge OSM extracts",
                 _raise("cmd builder for osm_merge not yet implemented — see Task 25"),
                 ("osmium-tool",), (), ("basemap",)),
    PipelineStep("osm_copy", "Stage OSM data",
                 _raise("cmd builder for osm_copy not yet implemented — see Task 25"),
                 (), (), ("basemap",)),
    PipelineStep("planetiler_pull", "Pull Planetiler image",
                 _raise("cmd builder for planetiler_pull not yet implemented — see Task 25"),
                 ("docker",), (), ("basemap",)),
    PipelineStep("planetiler_build", "Build basemap tiles",
                 _raise("cmd builder for planetiler_build not yet implemented — see Task 25"),
                 ("docker",), (), ("basemap",)),
    PipelineStep("poi_build", "Build POI index",
                 _raise("cmd builder for poi_build not yet implemented — see Task 25"),
                 ("python3",), (), ("basemap",)),
    PipelineStep("osm_pois", "Extract OSM POIs",
                 _raise("cmd builder for osm_pois not yet implemented — see Task 25"),
                 ("osmium-tool", "python3"), (), ("basemap",)),
    PipelineStep("public_lands", "Process public lands",
                 _raise("cmd builder for public_lands not yet implemented — see Task 25"),
                 ("tippecanoe", "python3"), (), ("basemap",)),
    PipelineStep("elevation", "Download elevation data",
                 _raise("cmd builder for elevation not yet implemented — see Task 25"),
                 ("python3",), (), ("elevation",)),
    PipelineStep("base_imagery", "Download base imagery",
                 _raise("cmd builder for base_imagery not yet implemented — see Task 25"),
                 ("python3",), (), ("base_imagery",)),
    PipelineStep("detail_imagery", "Download detail imagery",
                 _raise("cmd builder for detail_imagery not yet implemented — see Task 25"),
                 ("python3",), ("m2m", "copernicus"), ("detail_imagery",)),
    PipelineStep("fonts", "Download map fonts",
                 _raise("cmd builder for fonts not yet implemented — see Task 25"),
                 (), (), ("basemap",)),
    PipelineStep("docker_build", "Build Docker images",
                 _raise("cmd builder for docker_build not yet implemented — see Task 25"),
                 ("docker",), (), ()),
)


def filter_active_steps(all_steps, layer_selections: dict) -> tuple:
    """Return only steps whose `skippable_by` layers are not all 'skip'."""
    out = []
    for s in all_steps:
        if not s.skippable_by:
            out.append(s)
            continue
        any_active = any(
            layer_selections.get(layer) and layer_selections.get(layer) != "skip"
            for layer in s.skippable_by
        )
        if any_active:
            out.append(s)
    return tuple(out)
```

Add an additional Step 1 test asserting `PipelineContext` is present and has the 6 expected keys:

```python
def test_pipeline_context_typed_dict_has_expected_keys():
    from setup.pipeline_steps import PipelineContext
    # TypedDict __annotations__ exposes its fields
    assert set(PipelineContext.__annotations__.keys()) == {
        "bbox", "layer_bbox", "layers",
        "data_path", "scripts_path", "base_imagery_zoom",
    }
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_pipeline_steps.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add setup/pipeline_steps.py tests/test_pipeline_steps.py
git commit -m "$(cat <<'MSG'
feat(setup): structured PipelineStep registry (D5/B10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+67 passed.

---

### Task 25: Add missing command builders to runner.py

**Files:**
- Modify: `setup/runner.py`
- Modify: `setup/pipeline_steps.py` (wire real cmd_builder fns)
- Test: `tests/test_setup_runner.py` (extend)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append to `tests/test_setup_runner.py`:

```python
from setup.runner import (
    osm_download_cmd, osm_merge_cmd, osm_copy_cmd,
    planetiler_pull_cmd, base_imagery_cmd, detail_imagery_cmd,
    public_lands_cmd, fonts_cmd, styles_cmd, docker_build_cmd,
)


class TestCommandBuilders:
    def test_osm_download_cmd(self):
        cmd = osm_download_cmd(
            geofabrik_slugs=["arizona"],
            output_dir="/srv/geographica/data/pbf",
        )
        assert "wget" in cmd[0] or "curl" in cmd[0]
        assert any("arizona" in part for part in cmd)

    def test_osm_merge_cmd(self):
        cmd = osm_merge_cmd(
            input_paths=["/a.osm.pbf", "/b.osm.pbf"],
            output="/merged.osm.pbf",
        )
        assert "osmium" in cmd[0]
        assert "/merged.osm.pbf" in cmd

    def test_osm_copy_cmd(self):
        cmd = osm_copy_cmd("/src.osm.pbf", "/dst.osm.pbf")
        assert "cp" in cmd[0]

    def test_planetiler_pull_cmd(self):
        cmd = planetiler_pull_cmd()
        assert cmd[0] == "docker"
        assert cmd[1] == "pull"
        assert cmd[-1].endswith(":0.10.2")

    def test_base_imagery_cmd_naip(self):
        cmd = base_imagery_cmd(source="naip", bbox="-114,31,-109,37", zoom=15,
                               output="/srv/geographica/data/imagery.mbtiles")
        assert "scripts/acquire_imagery.py" in " ".join(cmd) or \
               "acquire_imagery.py" in " ".join(cmd)

    def test_detail_imagery_cmd_m2m(self):
        cmd = detail_imagery_cmd(source="m2m", bbox="-114,31,-109,37",
                                 output="/srv/geographica/data/imagery_detail.mbtiles")
        assert "m2m" in " ".join(cmd) or "acquire_imagery.py" in " ".join(cmd)

    def test_public_lands_cmd(self):
        cmd = public_lands_cmd(bbox="-114,31,-109,37",
                               output="/srv/geographica/data/public_lands.mbtiles")
        assert "build_public_lands.py" in " ".join(cmd)

    def test_fonts_cmd(self):
        cmd = fonts_cmd(output="/srv/geographica/data/fonts")
        # fonts is a git clone or curl from a known repo
        assert "fonts" in " ".join(cmd).lower()

    def test_styles_cmd(self):
        cmd = styles_cmd(output="/srv/geographica/data/styles")
        assert "styles" in " ".join(cmd).lower()

    def test_docker_build_cmd(self):
        cmd = docker_build_cmd()
        assert cmd[:3] == ["docker", "compose", "build"]
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_runner.py::TestCommandBuilders -v`
Expected: ImportError.

- [ ] **Step 3: Add builders to runner.py**

Important: `scripts/download_osm.py`, `scripts/download_fonts.py`, and `scripts/install_styles.py` DO NOT exist today. Do NOT invoke them. Instead, builders that need fan-out logic should return a `bash -c` single-command invocation. Scripts that DO exist and that builders should call directly: `scripts/acquire_imagery.py`, `scripts/acquire_sentinel.py`, `scripts/build_public_lands.py`, `scripts/build_poi_index.py`, `scripts/build_osm_pois.py`, `scripts/download_elevation.py`.

Add the following as module-level functions in `setup/runner.py`. All take a `ctx: PipelineContext` (or simple args) and return `list[str]`:

```python
# Module-level constant. Bump when pinning a new Planetiler version.
PLANETILER_VERSION = "0.10.2"


def osm_download_cmd(ctx) -> list[str]:
    """Download Geofabrik state PBFs. Uses bash -c for the for-loop.
    The list of slugs is hardcoded to the 11 western US states the project targets
    — if the project later wants user-selectable states, extend PipelineContext."""
    states = ("arizona california colorado idaho montana nevada "
              "new-mexico oregon utah washington wyoming")
    out = f"{ctx['data_path']}/pbf"
    script = (
        f"set -e; mkdir -p '{out}'; cd '{out}'; "
        f"for s in {states}; do "
        f"  wget -c --no-verbose "
        f"  \"https://download.geofabrik.de/north-america/us/${{s}}-latest.osm.pbf\"; "
        f"done"
    )
    return ["bash", "-c", script]


def osm_merge_cmd(ctx) -> list[str]:
    """Merge all state PBFs into western-us.osm.pbf."""
    out = f"{ctx['data_path']}/pbf"
    return [
        "bash", "-c",
        f"set -e; cd '{out}' && osmium merge *-latest.osm.pbf "
        f"-o western-us.osm.pbf --overwrite",
    ]


def osm_copy_cmd(ctx) -> list[str]:
    """Stage OSM PBF into valhalla/ subdir for the valhalla container."""
    src = f"{ctx['data_path']}/pbf/western-us.osm.pbf"
    dst_dir = f"{ctx['data_path']}/valhalla"
    return [
        "bash", "-c",
        f"set -e; mkdir -p '{dst_dir}' && cp '{src}' '{dst_dir}/western-us.osm.pbf'",
    ]


def planetiler_pull_cmd(ctx=None) -> list[str]:
    return ["docker", "pull", f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}"]


def planetiler_build_cmd(ctx) -> list[str]:
    """Run the planetiler container against the merged OSM extract."""
    return [
        "docker", "run", "--rm",
        "-v", f"{ctx['data_path']}:/data",
        f"ghcr.io/onthegomap/planetiler:{PLANETILER_VERSION}",
        "--area=custom",
        f"--osm-path=/data/pbf/western-us.osm.pbf",
        f"--output=/data/basemap.mbtiles",
        "--force",
    ]


def poi_build_cmd(ctx) -> list[str]:
    """Build Nominatim+FTS5 POI index over the bbox."""
    return [
        "python3", f"{ctx['scripts_path']}/build_poi_index.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--output", f"{ctx['data_path']}/poi.sqlite",
    ]


def osm_pois_cmd(ctx) -> list[str]:
    """Extract OSM POIs from the merged PBF (second POI index layer)."""
    return [
        "python3", f"{ctx['scripts_path']}/build_osm_pois.py",
        "--pbf", f"{ctx['data_path']}/pbf/western-us.osm.pbf",
        "--output", f"{ctx['data_path']}/poi.sqlite",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
    ]


def public_lands_cmd(ctx) -> list[str]:
    return [
        "python3", f"{ctx['scripts_path']}/build_public_lands.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--output", f"{ctx['data_path']}/public_lands.mbtiles",
        "--cache-dir", f"{ctx['data_path']}/cache/public_lands",
    ]


def elevation_cmd(ctx) -> list[str]:
    return [
        "python3", f"{ctx['scripts_path']}/download_elevation.py",
        "--bbox", ctx.get("layer_bbox", {}).get("basemap") or ctx["bbox"],
        "--zoom", "0-14",
        "--output", f"{ctx['data_path']}/elevation.mbtiles",
    ]


def base_imagery_cmd(ctx) -> list[str]:
    """Dispatch on ctx['layers']['base_imagery'] ∈ {naip, sentinel, noaa, skip}.
    'skip' is filtered out upstream by filter_active_steps; assert defensively."""
    source = ctx["layers"]["base_imagery"]
    if source == "skip":
        raise ValueError("base_imagery_cmd invoked with source='skip' — filter_active_steps should have removed this step")
    bbox = ctx.get("layer_bbox", {}).get("base_imagery") or ctx["bbox"]
    output = f"{ctx['data_path']}/imagery.mbtiles"
    zoom = ctx.get("base_imagery_zoom", 15)
    if source == "sentinel":
        return [
            "python3", f"{ctx['scripts_path']}/acquire_sentinel.py",
            "--bbox", bbox, "--zoom", str(zoom), "--output", output,
        ]
    # naip / noaa / tnmaccess all use acquire_imagery.py with --mode
    return [
        "python3", f"{ctx['scripts_path']}/acquire_imagery.py",
        "--mode", source, "--bbox", bbox,
        "--zoom", f"0-{zoom}", "--output", output,
    ]


def detail_imagery_cmd(ctx) -> list[str]:
    """Dispatch on ctx['layers']['detail_imagery'] ∈ {m2m, copernicus, skip}."""
    source = ctx["layers"]["detail_imagery"]
    if source == "skip":
        raise ValueError("detail_imagery_cmd invoked with source='skip' — filter_active_steps bug")
    bbox = ctx.get("layer_bbox", {}).get("detail_imagery") or ctx["bbox"]
    output = f"{ctx['data_path']}/imagery_detail.mbtiles"
    if source == "copernicus":
        return [
            "python3", f"{ctx['scripts_path']}/acquire_sentinel.py",
            "--bbox", bbox, "--detail", "--output", output,
        ]
    # m2m (USGS Earth Explorer machine-to-machine)
    return [
        "python3", f"{ctx['scripts_path']}/acquire_imagery.py",
        "--mode", "m2m", "--bbox", bbox, "--output", output,
    ]


def fonts_cmd(ctx) -> list[str]:
    """Fetch the PBF fonts bundle that tileserver-gl expects. No dedicated
    Python script — use bash wget + unzip."""
    dst = "tileserver/fonts-served"
    return [
        "bash", "-c",
        f"set -e; mkdir -p '{dst}' && cd '{dst}' && "
        f"wget -q -O fonts.zip "
        f"'https://github.com/openmaptiles/fonts/releases/download/v2.0/fonts.zip' && "
        f"unzip -o -q fonts.zip && rm fonts.zip",
    ]


def styles_cmd(ctx) -> list[str]:
    """Pull positron + dark-matter sprite icons into tileserver/styles/*/icons/.
    Uses git clone — no dedicated Python script."""
    return [
        "bash", "-c",
        "set -e; "
        "for style in positron dark-matter; do "
        "  mkdir -p tileserver/styles/$style/icons; "
        "  git clone --depth=1 "
        "    https://github.com/openmaptiles/$style-gl-style.git "
        "    /tmp/$style-style-$$; "
        "  cp -r /tmp/$style-style-$$/icons/* tileserver/styles/$style/icons/ || true; "
        "  rm -rf /tmp/$style-style-$$; "
        "done",
    ]


def docker_build_cmd(ctx=None) -> list[str]:
    """Build persistent service images (gps, search, stt, frontend).
    The pipeline-profile image is built separately in post_launch (Task 42)."""
    return ["docker", "compose", "build"]
```

Wire these into `setup/pipeline_steps.py` by importing and replacing each `_raise(...)` placeholder with the real function:

```python
from setup.runner import (
    osm_download_cmd, osm_merge_cmd, osm_copy_cmd,
    planetiler_pull_cmd, planetiler_build_cmd,
    poi_build_cmd, osm_pois_cmd, public_lands_cmd, elevation_cmd,
    base_imagery_cmd, detail_imagery_cmd,
    fonts_cmd, docker_build_cmd,
)

ALL_PIPELINE_STEPS = (
    PipelineStep("osm_download", "Download OSM data", osm_download_cmd,
                 ("wget",), (), ("basemap",)),
    # ... (etc. — one per builder, replacing the _raise placeholder)
)
```

Update the Step 1 test signatures if they currently call builders with kwargs that don't match. The canonical signature is `builder(ctx: PipelineContext) -> list[str]`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_runner.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/runner.py setup/pipeline_steps.py tests/test_setup_runner.py
git commit -m "$(cat <<'MSG'
feat(setup): full command-builder library for pipeline (B10/B28)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+77 passed.

---

### Task 26: Rewrite _run_pipeline to call run_command per step

**Files:**
- Modify: `setup/main.py:428-519` (PIPELINE_STEPS + `_run_pipeline`)
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall references: `dev/testing-pitfalls.md` — "Orchestrator loops that iterate steps without invoking subprocess" AND "Progress-state updates skipped in failure paths leave the UI stuck" (the `try/finally` in Step 3 prevents the stuck-UI class — every branch must clear `running=False` and broadcast a final state).

- [ ] **Step 1: Write failing test**

Append:

```python
class TestRunPipelineInvokesSubprocess:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_run_pipeline_calls_run_command_per_active_step(self, tmp_path, monkeypatch):
        from setup import main as mod
        calls = []

        async def fake_run(args, cwd, on_output, env_extra=None):
            calls.append(args)
            return 0

        monkeypatch.setattr(mod, "run_command", fake_run)
        # Use a temp data_path so checkpoint doesn't collide
        body = mod.StartRequest(
            bbox="-114.8,31.3,-109.0,37.0",
            layers={"basemap": "download", "base_imagery": "naip",
                    "detail_imagery": "skip", "elevation": "download"},
            data_path=str(tmp_path),
            base_imagery_zoom=15,
        )
        import asyncio as _a
        _a.run(mod._run_pipeline(body))
        # At least one call per active step; detail_imagery skipped.
        assert len(calls) >= 10
        assert not any("acquire_imagery.py" in " ".join(c) and "detail" in " ".join(c) for c in calls)
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestRunPipelineInvokesSubprocess -v`
Expected: FAIL (current loop never calls run_command).

- [ ] **Step 3: Rewrite _run_pipeline**

Delete the `PIPELINE_STEPS = [...]` list in main.py. Import from `setup.pipeline_steps`:

```python
from setup.pipeline_steps import ALL_PIPELINE_STEPS, filter_active_steps
```

Replace `_run_pipeline` body with this literal implementation (paste verbatim). Every exit branch — success, non-zero exit, exception, disk error, FileNotFoundError from disk_usage — must set `current_state["running"] = False` and broadcast a final state. The `try/finally` guarantees the flag is always cleared so a crashed pipeline can't permanently lock the endpoint:

```python
async def _run_pipeline(config: "StartRequest") -> None:
    """Run each active pipeline step in sequence. Every branch clears running=False."""
    from setup.pipeline_steps import ALL_PIPELINE_STEPS, filter_active_steps

    cwd = str(Path(__file__).parent.parent)
    ctx: dict = {
        "bbox": config.bbox,
        "layer_bbox": config.layer_bbox or {},
        "layers": config.layers or {},
        "data_path": config.data_path,
        "scripts_path": str(Path(cwd) / "scripts"),
        "base_imagery_zoom": config.base_imagery_zoom,
    }
    ckpt_path = Path(config.data_path) / ".setup_checkpoint.json"
    checkpoint = Checkpoint(str(ckpt_path))

    current_state["step"] = "running"

    def _on_output(step_id: str, source: str, data: bytes):
        text = data.decode("utf-8", errors="replace")
        asyncio.create_task(broadcast({
            "type": "output",
            "step": step_id,
            "source": source,  # "stdout" | "stderr"
            "data": text,
        }))

    try:
        active = filter_active_steps(ALL_PIPELINE_STEPS, ctx["layers"])
        for step in active:
            if checkpoint.is_completed(step.id):
                await broadcast({"type": "step_skipped", "step": step.id,
                                 "reason": "checkpoint"})
                continue

            await broadcast({"type": "step_start", "step": step.id,
                             "label": step.label})

            # Disk-space check per step. FileNotFoundError on data_path means
            # user pointed at a path that doesn't exist — surface clearly.
            try:
                usage = shutil.disk_usage(config.data_path)
                free_gb = usage.free / (1024 ** 3)
            except FileNotFoundError:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": f"Data path {config.data_path} does not exist. "
                               "Create it or rerun Step 1.",
                })
                return
            if free_gb < 5:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": f"Only {free_gb:.1f} GB free at {config.data_path}; "
                               "need at least 5 GB to continue.",
                })
                return

            # Build command. Builders raise ValueError on logic bugs
            # (e.g. step reached with source='skip' — filter should have removed).
            try:
                cmd = step.cmd_builder(ctx)
            except Exception as e:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": f"cmd builder failed: {e!r}",
                })
                return

            stderr_tail = bytearray()

            def _step_on_output(source, data, _step_id=step.id):
                if source == "stderr":
                    stderr_tail.extend(data)
                    if len(stderr_tail) > 2000:
                        del stderr_tail[:len(stderr_tail) - 2000]
                _on_output(_step_id, source, data)

            exit_code = await run_command(args=cmd, cwd=cwd, on_output=_step_on_output)
            if exit_code != 0:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": stderr_tail[-500:].decode("utf-8", errors="replace") or
                               f"exit code {exit_code} (no stderr captured)",
                })
                return

            checkpoint.mark_completed(step.id)
            await broadcast({"type": "step_done", "step": step.id})

        current_state["step"] = "done"
        await broadcast({"type": "pipeline_done"})
    except Exception as e:
        current_state["step"] = "error"
        await broadcast({
            "type": "error",
            "message": f"Unhandled pipeline error: {e!r}",
        })
    finally:
        current_state["running"] = False
        await broadcast({"type": "state", "running": False,
                         "step": current_state["step"]})
```

**Test coverage:** Step 1 test must cover BOTH success path (fake_run returns 0, assert all active steps invoked) AND error path (fake_run returns 1 on step N, assert error broadcast with `step + stderr`, assert `running=False`, assert no `pipeline_done`). Extend the existing `TestRunPipelineInvokesSubprocess` with a second method `test_run_pipeline_error_clears_running_flag`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py::TestRunPipelineInvokesSubprocess -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): _run_pipeline actually invokes run_command per step (B10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+78 passed.

---

### Task 27: Extend StartRequest with per-layer LayerConfig

**Files:**
- Modify: `setup/main.py:155-159` (`StartRequest`)
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall: "Pydantic request models silently drop fields the client sends" — set `extra="forbid"`.

- [ ] **Step 1: Write failing test**

Append:

```python
class TestStartRequestLayerConfig:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_start_accepts_per_layer_bbox(self, tmp_path, monkeypatch):
        from setup import main as mod
        async def fake_run(args, cwd, on_output, env_extra=None):
            return 0
        monkeypatch.setattr(mod, "run_command", fake_run)
        resp = self.client.post("/api/start", json={
            "bbox": "-114.8,31.3,-109.0,37.0",
            "layers": {"basemap": "download", "base_imagery": "naip",
                       "detail_imagery": "skip", "elevation": "download"},
            "data_path": str(tmp_path),
            "base_imagery_zoom": 15,
            "layer_bbox": {
                "basemap": "-114.8,31.3,-109.0,37.0",
                "base_imagery": "-113.0,33.0,-111.0,34.0",
                "detail_imagery": ""
            }
        }, headers=self.headers)
        assert resp.status_code == 200, resp.text

    def test_start_rejects_unknown_field(self):
        resp = self.client.post("/api/start", json={
            "bbox": "-114.8,31.3,-109.0,37.0",
            "layers": {"basemap": "download"},
            "data_path": "/srv/geographica/data",
            "random_garbage_field": "boom",
        }, headers=self.headers)
        assert resp.status_code == 422
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestStartRequestLayerConfig -v`
Expected: FAIL (StartRequest doesn't know the new fields; doesn't forbid extras).

- [ ] **Step 3: Update StartRequest**

```python
from pydantic import BaseModel, ConfigDict


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox: str
    layers: dict = {}  # {basemap, base_imagery, detail_imagery, elevation} -> source|'skip'
    data_path: str = "/srv/geographica/data"
    base_imagery_zoom: int = 15
    layer_bbox: dict = {}  # {layer: bbox_string} — empty string means "same as top-level bbox"
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py::TestStartRequestLayerConfig -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
feat(setup): per-layer bbox/zoom/source in StartRequest (Option B + B20)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+80 passed.

---

### Task 28: Step 2 HTML — per-layer "Customize coverage" details

**Files:**
- Modify: `setup/static/index.html:93-178`
- Test: extend `tests/test_setup_index_html.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append:

```python
def test_step2_has_customize_details_for_each_overridable_layer():
    text = INDEX.read_text()
    for layer in ("basemap", "base_imagery", "detail_imagery"):
        assert f'id="customize-{layer}"' in text or f'data-layer="{layer}"' in text


def test_step2_does_not_offer_elevation_override():
    # Elevation always follows basemap bbox.
    text = INDEX.read_text()
    assert 'id="customize-elevation"' not in text


def test_step2_drops_badges():
    text = INDEX.read_text()
    for badge in ("Broadest area", "Medium area", "Smallest area", "Same as basemap"):
        assert badge not in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_index_html.py -v`
Expected: FAIL.

- [ ] **Step 3: Update Step 2 HTML**

Use this literal `<details>` template for EACH of the three override-enabled layers — replace `base_imagery` with `basemap` (data-layer="basemap") and `detail_imagery` (data-layer="detail_imagery") respectively. The Elevation layer gets NO override control.

```html
<details class="layer-coverage">
    <summary>Customize coverage for this layer</summary>
    <label>
        <input type="checkbox" class="same-as-basemap" data-layer="base_imagery" checked>
        Same as basemap bbox
    </label>
    <div class="custom-bbox-group" style="display:none">
        <label for="bbox-base_imagery">Custom bbox (west,south,east,north):</label>
        <input type="text" id="bbox-base_imagery" class="bbox-override" placeholder="-112.0,35.0,-111.5,35.5">
        <span class="field-hint bbox-hint" id="bbox-hint-base_imagery"></span>
    </div>
</details>
```

Repeat for basemap (data-layer='basemap', id='bbox-basemap', hint-id='bbox-hint-basemap') and detail_imagery (data-layer='detail_imagery', id='bbox-detail_imagery', hint-id='bbox-hint-detail_imagery'). Elevation layer gets NO `<details>` — it always follows the basemap bbox.

Remove the old badge spans entirely ("Broadest area", "Medium area", "Smallest area", "Same as basemap"). Update any layer-card labels that referenced the tiered-coverage vocabulary to use plain source/skip wording.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_index_html.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add setup/static/index.html tests/test_setup_index_html.py
git commit -m "$(cat <<'MSG'
feat(setup): per-layer customize-coverage UI (Option B)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+83 passed.

---

### Task 29: Step 2 JS — build layer_bbox dict, validate each, send zoom

**Files:**
- Modify: `setup/static/setup.js` (nextStep Step 2 branch + init wiring + startPipeline payload)
- Test: extend `tests/test_setup_js.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append:

```python
def test_js_handles_same_as_basemap_checkbox():
    text = JS.read_text()
    assert "same-as-basemap" in text


def test_js_sends_layer_bbox_and_zoom():
    text = JS.read_text()
    assert "layer_bbox" in text
    assert "base_imagery_zoom" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: FAIL on 2 new tests.

- [ ] **Step 3: Update setup.js**

Add an `initLayerBboxOverrides()` function: for each `.same-as-basemap` checkbox, on change, enable/disable the sibling `.layer-bbox-input`; when checked, clear the input and set the disabled state. On input change of `.layer-bbox-input`, write into `config.layer_bbox[layer]`.

In the Step 2 branch of `nextStep`: for each overridable layer, validate its bbox string via `validate_bbox`-style check (4 floats, west<east, south<north). If any override is invalid, show error and return.

In `startPipeline`, update the payload to include `base_imagery_zoom` (already present) and `layer_bbox` (dict from config). Remove the old `layers: []` array form and send `layers: config.layers` as a dict matching StartRequest.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/static/setup.js tests/test_setup_js.py
git commit -m "$(cat <<'MSG'
feat(setup): JS sends layer_bbox overrides + zoom to backend (B20)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+85 passed.

---

### Task 30: /api/start TOCTOU with asyncio.Lock

**Files:**
- Modify: `setup/main.py:446-455`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall: "TOCTOU in async endpoints" (new one to add).

Also append a new testing-pitfalls entry — append this text to `/home/administrator/Code/geographica/dev/testing-pitfalls.md`:

```markdown
## TOCTOU in async endpoints — check-then-mutate across await points
When a FastAPI handler reads `state["running"]`, checks it, then schedules a background task via `asyncio.create_task(...)` and only THEN sets the flag to True (or sets it inside the spawned coroutine), two concurrent requests both pass the check before either writes. Tests should fire N concurrent POSTs to the gating endpoint and assert exactly one task ran (and the others returned 409). Fix: set the flag synchronously under an `asyncio.Lock` INSIDE the handler, before scheduling any task.
*Found in:* `setup/main.py:446-455` — /api/start TOCTOU allows concurrent pipelines.
```

- [ ] **Step 1: Write failing test**

Append to `tests/test_setup_main.py`. Use `httpx.AsyncClient` + `asyncio.gather` (not threading — TestClient's thread pool doesn't exercise the asyncio.Lock correctly):

```python
import httpx
import asyncio

@pytest.mark.asyncio
async def test_start_toctou_race(monkeypatch):
    # Simulate two concurrent /api/start calls; only one should win.
    from setup.main import app, CSRF_TOKEN

    spawn_count = [0]
    pipeline_gate = asyncio.Event()

    async def fake_pipeline(body):
        spawn_count[0] += 1
        await pipeline_gate.wait()

    monkeypatch.setattr("setup.main._run_pipeline", fake_pipeline)

    payload = {"bbox": "-124,31,-102,49", "data_path": "/tmp", "layers": {}}
    headers = {"X-CSRF-Token": CSRF_TOKEN}

    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        r1, r2 = await asyncio.gather(
            client.post("/api/start", json=payload, headers=headers),
            client.post("/api/start", json=payload, headers=headers),
        )
    pipeline_gate.set()

    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409], f"Expected exactly one 200 + one 409, got {statuses}"
    assert spawn_count[0] == 1
```

Requires `pytest-asyncio` in the dev dependencies. If not present, add it to `tests/requirements.txt` (or top-level) and note the addition in the commit.

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestStartTOCTOU -v`
Expected: FAIL.

- [ ] **Step 3: Fix post_start**

Add a module-level `_start_lock = asyncio.Lock()`. Rewrite:

```python
@app.post("/api/start")
async def post_start(body: StartRequest):
    if not validate_bbox(body.bbox):
        raise HTTPException(status_code=400, detail="Invalid bbox")
    async with _start_lock:
        if current_state["running"]:
            raise HTTPException(status_code=409, detail="Pipeline already running")
        current_state["running"] = True
        current_state["step"] = "starting"
    asyncio.create_task(_run_pipeline(body))
    return {"ok": True}
```

Ensure `_run_pipeline` still sets `current_state["running"] = False` in its finally.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py::TestStartTOCTOU -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py dev/testing-pitfalls.md
git commit -m "$(cat <<'MSG'
fix(setup): TOCTOU-safe /api/start with asyncio.Lock (B15)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+86 passed.

---

### Task 31: progress_buffer snapshot on ws connect

**Files:**
- Modify: `setup/main.py:411-414` (`ws_progress`)
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall: "Deque/list iteration during async-concurrent mutation".

- [ ] **Step 1: Write failing test**

Append:

```python
def test_ws_progress_snapshots_buffer(monkeypatch):
    """Verify the iteration uses list(progress_buffer), not raw deque."""
    from setup import main as mod
    import inspect
    src = inspect.getsource(mod.ws_progress)
    assert "list(progress_buffer)" in src or "list(mod.progress_buffer)" in src or \
           "snapshot" in src.lower(), (
        "ws_progress must snapshot progress_buffer via list(...) to avoid "
        "deque-mutated-during-iteration under concurrent pipeline output"
    )
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix ws_progress**

Replace `for event in progress_buffer:` with `for event in list(progress_buffer):`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): snapshot progress_buffer during ws replay (B16)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+87 passed.

---

### Task 32: Subprocess process-group + killpg shutdown

**Files:**
- Modify: `setup/runner.py:103-156` (`run_command` + `shutdown_children`)
- Test: extend `tests/test_setup_runner.py`

**TDD preamble:** Read TDD skill. Pitfall: "Subprocess orphan: grandchildren survive wizard shutdown".

- [ ] **Step 1: Write failing test**

Append:

```python
class TestShutdownKillsGrandchildren:
    def test_run_command_uses_start_new_session(self, monkeypatch):
        from setup import runner
        import inspect
        src = inspect.getsource(runner.run_command)
        assert "start_new_session=True" in src, (
            "run_command must spawn with start_new_session=True so shutdown "
            "can os.killpg the whole group (B17)"
        )

    def test_shutdown_children_uses_killpg(self):
        from setup import runner
        import inspect
        src = inspect.getsource(runner.shutdown_children)
        assert "killpg" in src
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_runner.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix runner.py**

In `run_command`, pass `start_new_session=True` to `asyncio.create_subprocess_exec`.

Rewrite `shutdown_children`:

```python
def shutdown_children() -> None:
    for proc in list(_active_processes):
        if proc.returncode is not None:
            continue
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_runner.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/runner.py tests/test_setup_runner.py
git commit -m "$(cat <<'MSG'
fix(setup): process-group + killpg for subprocess cleanup (B17)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+89 passed.

---

### Task 33: Parallel broadcast with per-socket timeout

**Files:**
- Modify: `setup/main.py:435-443`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall reference: `dev/testing-pitfalls.md` — "Deque/list iteration during async-concurrent mutation" (snapshotting the socket set before the gather is the same mitigation this pitfall describes for progress_buffer).

- [ ] **Step 1: Write failing test**

Append:

```python
def test_broadcast_uses_gather_with_timeout():
    from setup import main as mod
    import inspect
    src = inspect.getsource(mod.broadcast)
    assert "asyncio.gather" in src
    assert "wait_for" in src or "timeout" in src.lower()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Rewrite broadcast**

```python
async def broadcast(event: dict):
    progress_buffer.append(event)
    socks = list(connected_websockets)
    if not socks:
        return
    async def _send(ws):
        try:
            await asyncio.wait_for(ws.send_json(event), timeout=2.0)
            return None
        except Exception:
            return ws
    results = await asyncio.gather(*[_send(w) for w in socks], return_exceptions=True)
    for r in results:
        if isinstance(r, WebSocket):
            if r in connected_websockets:
                connected_websockets.remove(r)
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): parallel ws broadcast with per-socket 2s timeout (B18)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+90 passed.

---

### Task 34: Error broadcasts include step + stderr tail

**Files:**
- Modify: `setup/main.py::_run_pipeline` (except branch + non-zero exit branch)
- Modify: `setup/static/setup.js::handleProgressEvent` error branch
- Test: extend `tests/test_setup_main.py` (behavioral) + `tests/test_setup_js.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append to `tests/test_setup_js.py`:

```python
def test_error_shown_in_main_panel_not_only_log():
    text = JS.read_text()
    # The `showPipelineError` call must populate #error-actions (main panel),
    # not only appendLog.
    assert "showPipelineError" in text
    assert "#error-actions" in text
```

Append to `tests/test_setup_main.py`:

```python
def test_pipeline_error_broadcast_includes_step_and_stderr(tmp_path, monkeypatch):
    from setup import main as mod
    events = []
    async def capture(evt):
        events.append(evt)
    monkeypatch.setattr(mod, "broadcast", capture)

    async def failing_run(args, cwd, on_output, env_extra=None):
        on_output("stderr", b"boom stack trace line 1\nline 2\n")
        return 1

    monkeypatch.setattr(mod, "run_command", failing_run)
    body = mod.StartRequest(
        bbox="-114.8,31.3,-109.0,37.0",
        layers={"basemap": "download"},
        data_path=str(tmp_path),
    )
    import asyncio as _a
    _a.run(mod._run_pipeline(body))
    errors = [e for e in events if e.get("type") == "error"]
    assert errors
    e = errors[0]
    assert "step" in e
    assert "boom" in (e.get("message") or "")
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py tests/test_setup_js.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix main.py + setup.js**

In `_run_pipeline`, maintain a per-step `stderr_tail` bytearray in `on_output` (append on `source=="stderr"`). On non-zero exit, broadcast `{"type":"error","step":step.id,"message": stderr_tail[-500:].decode(errors='replace')}`. In the outer `except Exception as e:` branch, include the current step id and `str(e)` as message.

In setup.js `handleProgressEvent`, the `type === 'error'` branch already calls `showPipelineError` when `event.step` is present. Verify it also sets `#error-actions` display to visible (it does via `showPipelineError`).

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py tests/test_setup_js.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py setup/static/setup.js tests/test_setup_main.py tests/test_setup_js.py
git commit -m "$(cat <<'MSG'
fix(setup): pipeline errors surface step + stderr tail (B25)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+92 passed.

---

### Task 35: Checkpoint crash-resilience + reset endpoint + UI button

**Files:**
- Modify: `setup/runner.py:15-42` (`Checkpoint`)
- Modify: `setup/main.py` (add `/api/checkpoint/reset` endpoint)
- Modify: `setup/static/index.html` (Step 4 reset button)
- Modify: `setup/static/setup.js` (reset handler)
- Test: `tests/test_setup_runner.py` (extend) + `tests/test_setup_main.py` (extend)

**TDD preamble:** Read TDD skill. Pitfall: "Non-atomic checkpoint writes lose all progress on crash".

- [ ] **Step 1: Write failing test**

Append to `tests/test_setup_runner.py`:

```python
class TestCheckpointResilience:
    def test_corrupt_json_returns_empty(self, tmp_path):
        from setup.runner import Checkpoint
        path = tmp_path / "ckpt.json"
        path.write_text("{not valid json")
        cp = Checkpoint(str(path))
        assert cp.get_completed() == []

    def test_persist_is_atomic(self, tmp_path, monkeypatch):
        from setup import runner
        import inspect
        src = inspect.getsource(runner.Checkpoint._persist)
        assert ".tmp" in src or "os.replace" in src or "rename" in src

    def test_persist_creates_parent_dir(self, tmp_path):
        from setup.runner import Checkpoint
        nested = tmp_path / "deep" / "nested" / "ckpt.json"
        cp = Checkpoint(str(nested))
        cp.mark_completed("x")
        assert nested.exists()

    def test_reset_clears_file(self, tmp_path):
        from setup.runner import Checkpoint
        path = tmp_path / "ckpt.json"
        cp = Checkpoint(str(path))
        cp.mark_completed("a")
        cp.reset()
        assert not path.exists()
```

Append to `tests/test_setup_main.py`:

```python
class TestCheckpointResetEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_reset_endpoint_exists(self, tmp_path, monkeypatch):
        resp = self.client.post("/api/checkpoint/reset",
                                json={"data_path": str(tmp_path)},
                                headers=self.headers)
        assert resp.status_code in (200, 400)
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_runner.py tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix Checkpoint + add endpoint + UI**

In `setup/runner.py::Checkpoint.__init__`, wrap `json.loads(self._path.read_text())` in try/except returning `{}`.

Rewrite `_persist`:

```python
def _persist(self) -> None:
    self._path.parent.mkdir(parents=True, exist_ok=True)
    tmp = self._path.with_suffix(self._path.suffix + ".tmp")
    tmp.write_text(json.dumps({"completed": sorted(self._completed)}))
    os.replace(str(tmp), str(self._path))
```

In `setup/main.py` add:

```python
class CheckpointResetRequest(BaseModel):
    data_path: str


@app.post("/api/checkpoint/reset")
async def post_checkpoint_reset(body: CheckpointResetRequest):
    validation = validate_path(body.data_path)
    if not validation.get("valid"):
        raise HTTPException(status_code=400, detail=validation.get("reason", "Invalid path"))
    ckpt_path = Path(body.data_path) / ".setup_checkpoint.json"
    if ckpt_path.exists():
        ckpt_path.unlink()
    return {"ok": True}
```

In `setup/static/index.html` Step 4, add inside the `#pipeline-section`:

```html
        <button class="btn btn-secondary btn-small" id="btn-reset-checkpoint" type="button">
          Reset checkpoint
        </button>
```

In `setup/static/setup.js` init(), wire:

```javascript
    $('#btn-reset-checkpoint').addEventListener('click', function () {
      if (!confirm('Reset pipeline checkpoint? This will re-run completed steps on the next start.')) return;
      api('POST', '/api/checkpoint/reset', { data_path: config.data_path })
        .then(function () { alert('Checkpoint cleared.'); })
        .catch(function (err) { showError('Reset failed: ' + err.message); });
    });
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_runner.py tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/runner.py setup/main.py setup/static/index.html setup/static/setup.js tests/test_setup_runner.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): crash-resilient checkpoint + reset endpoint/UI (B14)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+97 passed.

---

### Task 36: Disk-error path does not fall through to pipeline_done

**Files:**
- Modify: `setup/main.py::_run_pipeline`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append:

```python
def test_disk_error_does_not_broadcast_pipeline_done(tmp_path, monkeypatch):
    from setup import main as mod
    events = []
    async def capture(evt):
        events.append(evt)
    monkeypatch.setattr(mod, "broadcast", capture)

    import shutil
    monkeypatch.setattr(
        shutil, "disk_usage",
        lambda p: type("U", (), {"total": 1, "used": 1, "free": 1})(),
    )
    body = mod.StartRequest(
        bbox="-114.8,31.3,-109.0,37.0",
        layers={"basemap": "download"},
        data_path=str(tmp_path),
    )
    import asyncio as _a
    _a.run(mod._run_pipeline(body))
    assert not any(e.get("type") == "pipeline_done" for e in events), (
        "disk-critically-low must NOT broadcast success"
    )
    assert any(e.get("type") == "error" for e in events)
    # State reflects error
    assert mod.current_state["step"] == "error"
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix disk-error branch**

In `_run_pipeline` disk-space check, on `free_gb < 5`, set `current_state["step"] = "error"`, broadcast the error event, then `return` (not `break` — break falls through to pipeline_done).

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): disk-critical path returns, never marks pipeline done (E9)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+98 passed.

**After Phase 6 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 7.

---

## Phase 7 — Preflight + install prompt

### Task 37: Extend PREFLIGHT_CHECKS + add fix_hint field

**Files:**
- Modify: `setup/main.py:52-62` (PREFLIGHT_CHECKS)
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall: "Preflight/fix registries with parallel keys that drift" — new check items should include actionable fix_hint strings.

- [ ] **Step 1: Write failing test**

Append:

```python
class TestPreflightCoversAllDeps:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_preflight_includes_tippecanoe(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "tippecanoe" in names

    def test_preflight_includes_pipeline_python_deps(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "python-pipeline-deps" in names

    def test_preflight_includes_keyring_agent(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "keyring-agent" in names

    def test_preflight_includes_cgroup_memory(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "cgroup-memory" in names

    def test_preflight_includes_openssl(self):
        resp = self.client.get("/api/preflight")
        names = [c["name"] for c in resp.json()["checks"]]
        assert "openssl" in names

    def test_every_check_has_fix_hint(self):
        from setup.main import PREFLIGHT_CHECKS
        for entry in PREFLIGHT_CHECKS:
            assert "fix_hint" in entry, f"{entry['name']} missing fix_hint"
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestPreflightCoversAllDeps -v`
Expected: FAIL.

- [ ] **Step 3: Extend PREFLIGHT_CHECKS**

Rewrite `PREFLIGHT_CHECKS` as a list of dicts each with: `name`, `label`, `check_cmd` (for classic binary checks) OR `check_fn` (for Python checks), and `fix_hint`. Add:

- `tippecanoe` — `check_cmd=["tippecanoe", "--version"]`, `fix_hint="sudo ./bootstrap.sh (installs tippecanoe 2.80.0)"`.
- `python-pipeline-deps` — `check_fn=_check_python_pipeline_deps` which tries `import rasterio, shapely, scipy, numpy` and returns ok/missing. `fix_hint="sudo ./bootstrap.sh (installs scripts/requirements.txt)"`.
- `keyring-agent` — `check_fn=_check_keyring_socket` that `os.path.exists("/run/geographica/keyring.sock")` is True. `fix_hint="sudo systemctl start geographica-keyring"`.
- `cgroup-memory` — `check_fn=_check_cgroup_memory` that `Path("/sys/fs/cgroup/memory.max").exists() or "memory" in Path("/proc/cgroups").read_text()`. `fix_hint="Enable cgroup memory controller (reboot after ./bootstrap.sh)"`.
- `openssl` — `check_cmd=["openssl", "version"]`, `fix_hint="sudo ./bootstrap.sh"`.

Existing entries keep their `check_cmd` and gain `fix_hint="sudo ./bootstrap.sh"` uniformly.

Update the `/api/preflight` handler to return `fix_hint` in each response dict.

Add the helper functions near the top of main.py.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py::TestPreflightCoversAllDeps -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
feat(setup): preflight covers tippecanoe, Python deps, keyring, cgroup, openssl (B21)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+104 passed.

---

### Task 38: Drop /api/fix-dependency + FIX_REGISTRY + Install buttons

**Files:**
- Modify: `setup/main.py:39-49, 239-261` (delete FIX_REGISTRY + /api/fix-dependency + FixDependencyRequest)
- Modify: `setup/static/setup.js::runPreflightChecks::fixDependency` (delete button + function)
- Test: update `tests/test_setup_main.py` (delete `TestFixDependencyEndpoint`, add skip-trace test)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Delete `TestFixDependencyEndpoint` class entirely.

Append:

```python
class TestFixDependencyRemoved:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_fix_dependency_endpoint_returns_404(self):
        resp = self.client.post("/api/fix-dependency",
                                json={"dependency": "docker"},
                                headers=self.headers)
        assert resp.status_code == 404
```

Append to `tests/test_setup_js.py`:

```python
def test_js_has_no_fix_dependency_button():
    text = JS.read_text()
    # The fix button must be removed
    assert "/api/fix-dependency" not in text
    assert "fixDependency" not in text, \
        "fixDependency still present in setup.js — Task 38 requires deletion, not commenting-out"
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py tests/test_setup_js.py -v`
Expected: FAIL until fixes land.

- [ ] **Step 3: Delete code**

In `setup/main.py`: delete `FIX_REGISTRY = {...}` (lines 39-49), `FixDependencyRequest` (lines 147-148), `post_fix_dependency` handler (lines 239-261).

In `setup/static/setup.js`: delete `fixDependency` function (lines 597-614). In `runPreflightChecks`, replace the per-failed-item Install button with a single block at the top of the list:

```javascript
      var actionsEl = $('#preflight-actions');
      actionsEl.style.display = '';
      if (!allOk) {
        var remedyBox = $('#preflight-remedy');
        if (!remedyBox) {
          remedyBox = createEl('div', 'preflight-remedy');
          remedyBox.id = 'preflight-remedy';
          actionsEl.parentNode.insertBefore(remedyBox, actionsEl);
        }
        remedyBox.textContent = '';
        var msg = createEl('div', null,
          'To install missing dependencies, run this in a terminal:');
        var pre = createEl('pre', 'remedy-cmd', 'sudo ./bootstrap.sh');
        var copyBtn = createEl('button', 'btn btn-secondary btn-small', 'Copy');
        copyBtn.addEventListener('click', function () {
          navigator.clipboard.writeText('sudo ./bootstrap.sh');
          copyBtn.textContent = 'Copied';
          setTimeout(function () { copyBtn.textContent = 'Copy'; }, 2000);
        });
        remedyBox.appendChild(msg);
        remedyBox.appendChild(pre);
        remedyBox.appendChild(copyBtn);
      }
```

Update `index.html` to reserve an `#preflight-actions` section (already exists) with a Re-check button. No per-row install button anywhere.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py tests/test_setup_js.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py setup/static/setup.js tests/test_setup_main.py tests/test_setup_js.py
git commit -m "$(cat <<'MSG'
refactor(setup): drop /api/fix-dependency; point users at bootstrap (D3/B22/B23/B24)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+106 passed.

**After Phase 7 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 8.

---

## Phase 8 — UI polish

### Task 39: Shared showError + await saves in nextStep

**Files:**
- Modify: `setup/static/setup.js` (add showError helper, wire into catch branches, await saves in nextStep)
- Test: extend `tests/test_setup_js.py`

**TDD preamble:** Read TDD skill. Pitfall: "Fire-and-forget async save from UI".

- [ ] **Step 1: Write failing test**

Append:

```python
def test_js_has_shared_showError():
    text = JS.read_text()
    assert "function showError" in text


def test_js_no_silent_catch_console_error():
    text = JS.read_text()
    # Every `.catch(function(err){ console.error` must also call showError
    import re
    silent = re.findall(r"\.catch\(\s*function\s*\([^)]*\)\s*\{\s*console\.error[^}]*\}\s*\)", text)
    assert not silent, (
        "Each .catch that only console.errors must also call showError. "
        f"Found silent catches: {silent[:3]}"
    )


def test_nextStep_awaits_saveConfig_and_saveCredentials():
    text = JS.read_text()
    # nextStep's Step 3 branch should chain saveConfig/saveCredentials promises
    assert "saveConfig()" in text
    assert "saveCredentials()" in text
    # And use await-style chaining (then/await). We don't parse JS, but
    # absence of `saveConfig();\n    saveCredentials();` pattern is enough.
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: FAIL on first two.

- [ ] **Step 3: Add showError + rewire**

Add helper (place near top of IIFE):

```javascript
  function showError(msg, context) {
    var banner = document.getElementById('global-error-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'global-error-banner';
      banner.className = 'global-error-banner';
      document.body.insertBefore(banner, document.body.firstChild);
    }
    banner.textContent = (context ? '[' + context + '] ' : '') + msg;
    banner.style.display = '';
    // Auto-hide after 10s
    clearTimeout(showError._t);
    showError._t = setTimeout(function () {
      banner.style.display = 'none';
    }, 10000);
  }
```

In `saveConfig`: return the Promise; add `.catch(function (err) { showError('Save config failed: ' + err.message); throw err; })`.
Similarly for `saveCredentials`, `loadPresets`, `onTlsModeChange`, `loadSystemInfo`.

In `nextStep`, rewrite the Step 3 branch:

```javascript
    if (currentStep === 3) {
      return saveConfig()
        .then(function () { return saveCredentials(); })
        .then(function () { showStep(currentStep + 1); })
        .catch(function (err) { /* already surfaced by helpers */ });
    }
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_js.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/static/setup.js tests/test_setup_js.py
git commit -m "$(cat <<'MSG'
fix(setup): shared showError helper; await saves in nextStep (B13)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+109 passed.

---

### Task 40: Parse existing .env + merge in /api/system + preserve non-wizard keys

**Files:**
- Modify: `setup/main.py::get_system` (add parsed dict)
- Modify: `setup/main.py::post_config` (merge, don't overwrite)
- Modify: `setup/static/setup.js::loadSystemInfo` (pre-fill from parsed)
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall references: `dev/testing-pitfalls.md` — "UI message promises behavior the code doesn't implement" AND "Non-atomic checkpoint writes lose all progress on crash" (the atomic-write pattern in Step 3 applies that pitfall's prescribed fix to `.env` rewrites — a crash mid-write can't leave an empty/truncated .env).

- [ ] **Step 1: Write failing test**

Append:

```python
class TestExistingEnvPreserved:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_system_includes_parsed_env(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("TLS_MODE=tailscale\nBBOX=-120,30,-100,45\nCUSTOM_KEY=foo\n")
        monkeypatch.setattr("setup.main.ENV_PATH", str(env))
        resp = self.client.get("/api/system")
        data = resp.json()
        assert data["existing_env"] is True
        assert data["existing_env_parsed"]["TLS_MODE"] == "tailscale"
        assert data["existing_env_parsed"]["CUSTOM_KEY"] == "foo"

    def test_post_config_preserves_custom_keys(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("CUSTOM_KEY=preserved\nTLS_MODE=http\n")
        monkeypatch.setattr("setup.main.ENV_PATH", str(env))
        resp = self.client.post("/api/config", json={
            "tls_mode": "https",
            "bbox": "-114.8,31.3,-109.0,37.0",
            "data_path": "/srv/geographica/data",
        }, headers=self.headers)
        assert resp.status_code == 200
        contents = env.read_text()
        assert "CUSTOM_KEY=preserved" in contents
        assert "TLS_MODE=https" in contents
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestExistingEnvPreserved -v`
Expected: FAIL.

- [ ] **Step 3: Implement parse + merge**

Add helper `_parse_env(path)` that reads the file line-by-line, skips blanks and `#` lines, splits at first `=`, returns dict.

Update `get_system`:

```python
@app.get("/api/system")
async def get_system():
    ram_mb = detect_ram_mb()
    existing_env_parsed = {}
    if os.path.exists(ENV_PATH):
        existing_env_parsed = _parse_env(ENV_PATH)
    return {
        "ram_mb": ram_mb,
        "ram_profile": get_ram_profile(ram_mb),
        "storage": detect_storage(),
        "existing_env": os.path.exists(ENV_PATH),
        "existing_env_parsed": existing_env_parsed,
    }
```

Update `post_config`: before writing, parse existing .env; the wizard owns exactly the set below (must match the keys `generate_env` emits from Task 11). Merge wizard-generated text with existing non-WIZARD_KEYS lines, then write atomically (tmp + replace) so a crash mid-write can't leave an empty or truncated .env:

```python
WIZARD_KEYS = {
    "TLS_MODE", "TLS_CERT_DIR", "TLS_PORT", "BBOX",
    "DATA_HOST_PATH", "SCRIPTS_HOST_PATH", "STT_BACKEND",
    "NOMINATIM_MEMORY", "POSTGRES_SHARED_BUFFERS",
    "POSTGRES_MAINTENANCE_WORK_MEM", "POSTGRES_EFFECTIVE_CACHE_SIZE",
    "POSTGRES_WORK_MEM", "POSTGRES_AUTOVACUUM_WORK_MEM",
    "VALHALLA_MEMORY", "VALHALLA_THREADS",
    "TILESERVER_MEMORY", "STT_MEMORY",
    "PIPELINE_MEMORY", "PIPELINE_GDAL_CACHE", "PLANETILER_HEAP",
    "GPS_DEVICE",
}
```

The atomic-write pattern (use instead of a naive `write_text` that can truncate on crash):

```python
tmp_path = Path(ENV_PATH).with_suffix(".tmp")
tmp_path.write_text(merged_content)
tmp_path.replace(ENV_PATH)
```

In `setup/static/setup.js::loadSystemInfo`, use `data.existing_env_parsed` to pre-fill TLS mode + DATA_HOST_PATH (already done in Task 20 — verify).

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py setup/static/setup.js tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): preserve non-wizard .env keys + pre-fill from existing (B12)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+111 passed.

---

### Task 41: Parametrized all_healthy status-string test + regex fix

**Files:**
- Modify: `setup/main.py::post_launch` (all_healthy logic)
- Test: extend `tests/test_setup_main.py` with parametrized cases

**TDD preamble:** Read TDD skill. Pitfall: "Substring matching on status strings".

- [ ] **Step 1: Write failing test**

Append:

```python
import re

class TestAllHealthyRegex:
    @pytest.mark.parametrize("svcs,expected", [
        # All healthy
        ([{"Health": "healthy"}, {"Health": "healthy"}], True),
        # One unhealthy
        ([{"Health": "healthy"}, {"Health": "unhealthy"}], False),
        # Status field variants
        ([{"Status": "Up 2 days (healthy)"}, {"Status": "Up 2 days (healthy)"}], True),
        ([{"Status": "Up 2 days (unhealthy)"}], False),
        ([{"Status": "Up 2 days (health: starting)"}], False),
        ([{"Status": "Up 5 minutes"}], False),
        ([{"Status": "Exited (1)"}], False),
        ([{}], False),
    ])
    def test_all_healthy_classifier(self, svcs, expected):
        from setup.main import _is_all_healthy
        assert _is_all_healthy(svcs) is expected
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py::TestAllHealthyRegex -v`
Expected: FAIL.

- [ ] **Step 3: Extract + fix classifier**

Factor the classifier into a helper:

```python
_HEALTHY_RE = re.compile(r"\(healthy\)")


def _is_all_healthy(services: list[dict]) -> bool:
    if not services:
        return False
    for s in services:
        health = s.get("Health", "") or ""
        if health == "healthy":
            continue
        status = s.get("Status", "") or ""
        if _HEALTHY_RE.search(status):
            continue
        return False
    return True
```

Replace the inline substring check in `post_launch` with `all_healthy = _is_all_healthy(existing_services)`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py::TestAllHealthyRegex -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): strict all_healthy — no false positives on unhealthy (B7)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+119 passed.

---

### Task 42: post_launch builds pipeline image

**Files:**
- Modify: `setup/main.py::post_launch`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append:

```python
def test_launch_builds_pipeline_profile(tmp_path, monkeypatch):
    from setup import main as mod
    recorded = []
    async def fake_run(args, cwd, on_output, env_extra=None):
        recorded.append(args)
        return 0
    monkeypatch.setattr(mod, "run_command", fake_run)

    async def fake_exec(*args, **kwargs):
        class P:
            returncode = 0
            async def communicate(self):
                return (b"", b"")
        return P()
    monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_exec)

    env = tmp_path / ".env"
    env.write_text(f"DATA_HOST_PATH={tmp_path}\n")
    monkeypatch.setattr(mod, "ENV_PATH", str(env))

    from fastapi.testclient import TestClient
    client = TestClient(mod.app)
    resp = client.post("/api/launch", headers={"X-CSRF-Token": mod.CSRF_TOKEN})
    assert resp.status_code == 200
    # At least one recorded run_command must include "--profile" and "pipeline"
    # and the term "build".
    has_pipeline_build = any(
        "--profile" in " ".join(c) and "pipeline" in " ".join(c) and "build" in c
        for c in recorded
    )
    assert has_pipeline_build, f"No pipeline build: {recorded}"
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Update post_launch**

Before the `up -d` call, short-circuit the build when the image already exists (second launches shouldn't wait 2 minutes to confirm nothing has changed). Use `docker image inspect` as the presence check — it's fast (< 100ms) and doesn't require a daemon round-trip for pulls:

```python
    # Check if pipeline image already exists; skip build if so.
    img_check = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", "geographica-pipeline",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        cwd=cwd,
    )
    await img_check.wait()
    if img_check.returncode != 0:
        # Image missing — build it.
        build = await asyncio.create_subprocess_exec(
            "docker", "compose", "--profile", "pipeline", "build",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await build.communicate()
        if build.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Pipeline image build failed: {stderr.decode()[:500]}")
```

Note: the existing test `test_launch_builds_pipeline_profile` expects the build to always run. Update the test to either (a) patch `asyncio.create_subprocess_exec` such that `docker image inspect` returns non-zero (image missing), or (b) add a second test `test_launch_skips_build_when_image_exists` asserting `image inspect` is called and no `compose build` is invoked when the former returns 0.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): /api/launch builds the pipeline profile image (B4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+120 passed.

---

### Task 43: progress_buffer maxlen=5000

**Files:**
- Modify: `setup/main.py:79`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Append:

```python
def test_progress_buffer_maxlen_is_5000():
    from setup.main import progress_buffer
    assert progress_buffer.maxlen == 5000
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix maxlen**

Change `progress_buffer: deque = deque(maxlen=100)` to `deque(maxlen=5000)`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): bump progress_buffer maxlen to 5000 (B43)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+121 passed.

---

### Task 44: main.py __main__ binds 127.0.0.1

**Files:**
- Modify: `setup/main.py:596-598`
- Test: extend `tests/test_setup_main.py`

**TDD preamble:** Read TDD skill. Pitfall reference: `docs/pitfalls/implementation-pitfalls.md` — "Config panel localhost-only" entry (the wizard is authenticated only by CSRF token in the same browser session; exposing it on 0.0.0.0 would let any peer on the LAN/AREDN mesh POST to /api/launch and take over the stack).

- [ ] **Step 1: Write failing test**

Append:

```python
def test_main_entrypoint_binds_loopback():
    from setup import main as mod
    import inspect
    # Read the source of the __main__ guard
    src = Path(mod.__file__).read_text()
    # Find the final uvicorn.run(...) call
    assert 'host="127.0.0.1"' in src or "host='127.0.0.1'" in src
    assert 'host="0.0.0.0"' not in src and "host='0.0.0.0'" not in src
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: FAIL.

- [ ] **Step 3: Fix __main__**

Change `uvicorn.run(app, host="0.0.0.0", port=8099)` to `uvicorn.run(app, host="127.0.0.1", port=8099)`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_setup_main.py -v`
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add setup/main.py tests/test_setup_main.py
git commit -m "$(cat <<'MSG'
fix(setup): __main__ binds 127.0.0.1 only (B36)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+122 passed.

**After Phase 8 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 9.

---

## Phase 9 — CI harness (LXD + Playwright)

### Task 45: dev/harness/wizard-ci.sh — LXD lifecycle + smoke harness

**Files:**
- Create: `dev/harness/wizard-ci.sh`
- Test: `tests/test_wizard_ci_script.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_wizard_ci_script.py`:

```python
import os
from pathlib import Path
SCRIPT = Path(__file__).parent.parent / "dev" / "harness" / "wizard-ci.sh"


def test_script_exists_and_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)


def test_script_uses_lxc_launch():
    text = SCRIPT.read_text()
    assert "lxc launch" in text
    assert "images:debian/trixie/cloud" in text or "debian/trixie" in text


def test_script_waits_for_setup_port():
    text = SCRIPT.read_text()
    assert "8099" in text
    # Must poll until port opens (not a raw sleep)
    assert "curl" in text or "wget" in text


def test_script_invokes_drive_wizard_mjs():
    text = SCRIPT.read_text()
    assert "drive-wizard.mjs" in text


def test_script_accepts_smoke_or_full():
    text = SCRIPT.read_text()
    assert "--smoke" in text
    assert "--full" in text


def test_script_exits_with_status_on_health_check():
    text = SCRIPT.read_text()
    assert "exit 0" in text or 'exit "$RC"' in text or "exit $RC" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_wizard_ci_script.py -v`
Expected: 6 FAIL.

- [ ] **Step 3: Create script**

Create `dev/harness/wizard-ci.sh` as a bash script with `set -euo pipefail`:

1. Parse `--smoke` / `--full` flag (default smoke).
2. Generate container name: `geographica-wizard-ci-$(date +%s)`.
3. `lxc launch images:debian/trixie/cloud <name>`; wait for cloud-init.
4. `lxc file push -r <repo_root> <name>/root/geographica`.
5. `lxc exec <name> -- bash -c "cd /root/geographica && sudo ./bootstrap.sh"`.
6. `lxc exec <name> -- bash -c "cd /root/geographica && nohup ./setup.sh >/tmp/setup.log 2>&1 &"`.
7. Poll `curl http://<container-ip>:8099/` with backoff until HTTP 200 (timeout 120s).
8. Inside the container, run `node dev/harness/drive-wizard.mjs --<mode>`.
9. In `--full` mode, wait up to 10 min for `docker compose ps` to report all services healthy.
10. On success `exit 0`; on failure print logs and `exit 1`.
11. Always `lxc delete --force <name>` in trap EXIT.

Make executable: `chmod +x dev/harness/wizard-ci.sh`.

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_wizard_ci_script.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add dev/harness/wizard-ci.sh tests/test_wizard_ci_script.py
git commit -m "$(cat <<'MSG'
ci(setup): LXD wizard harness entrypoint (D8/O3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+128 passed.

---

### Task 46: dev/harness/drive-wizard.mjs — Playwright automation

**Files:**
- Create: `dev/harness/drive-wizard.mjs`
- Create: `dev/harness/package.json`
- Test: `tests/test_drive_wizard_script.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_drive_wizard_script.py`:

```python
from pathlib import Path
MJS = Path(__file__).parent.parent / "dev" / "harness" / "drive-wizard.mjs"
PKG = Path(__file__).parent.parent / "dev" / "harness" / "package.json"


def test_mjs_exists():
    assert MJS.exists()


def test_mjs_imports_playwright():
    text = MJS.read_text()
    assert "import" in text and "playwright" in text


def test_mjs_handles_smoke_and_full():
    text = MJS.read_text()
    assert "--smoke" in text
    assert "--full" in text


def test_mjs_drives_all_five_steps():
    text = MJS.read_text()
    for step in ("step-1", "step-2", "step-3", "step-4", "step-5"):
        # Either selector-based or numeric tab-click — just ensure all exist
        assert step in text or f"data-step=\"{step[-1]}\"" in text


def test_package_json_has_playwright_devdep():
    import json
    assert PKG.exists()
    data = json.loads(PKG.read_text())
    assert "playwright" in (data.get("devDependencies") or {})
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_drive_wizard_script.py -v`
Expected: 5 FAIL.

- [ ] **Step 3: Create files**

`dev/harness/package.json`:

```json
{
  "name": "geographica-wizard-harness",
  "version": "0.1.0",
  "type": "module",
  "private": true,
  "devDependencies": {
    "playwright": "^1.48.0"
  }
}
```

`dev/harness/drive-wizard.mjs`:

```javascript
// Playwright-driven Geographica wizard walkthrough.
// Usage: node drive-wizard.mjs --smoke | --full [--url http://host:8099]
import { chromium } from 'playwright';

const args = new Set(process.argv.slice(2));
const mode = args.has('--full') ? 'full' : 'smoke';
const urlArg = [...args].find(a => a.startsWith('--url='));
const baseUrl = urlArg ? urlArg.slice(6) : 'http://localhost:8099';

async function run() {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  page.on('console', m => console.log('[browser]', m.text()));
  await page.goto(baseUrl);
  await page.waitForSelector('#step-1');

  // Step 1: accept detected drive, keep default subpath, TLS http
  await page.selectOption('#tls-mode', 'http');
  await page.waitForTimeout(500); // debounced validate-path
  await page.click('#btn-next');
  await page.waitForSelector('#step-2');

  // Step 2: choose Arizona preset
  await page.selectOption('#preset-select', 'arizona');
  await page.click('button.source-btn[data-layer="detail_imagery"][data-value="skip"]');
  await page.click('#btn-next');

  // Step 3: skip credentials (detail_imagery=skip, no creds required)
  await page.waitForSelector('#step-3');
  await page.click('#btn-skip-creds');

  // Step 4: preflight + (smoke: stop here; full: run pipeline)
  await page.waitForSelector('#step-4');
  if (mode === 'smoke') {
    console.log('SMOKE: reached Step 4, exiting clean');
    await browser.close();
    return;
  }
  await page.click('#btn-next');
  // Wait up to 8 hours for pipeline_done (realistic for full run)
  await page.waitForSelector('#step-5', { timeout: 8 * 60 * 60 * 1000 });

  // Step 5: wait for all services healthy
  await page.waitForSelector('#completion-msg:not([style*="display:none"])', {
    timeout: 10 * 60 * 1000,
  });
  console.log('FULL: all services healthy');
  await browser.close();
}

run().catch(err => {
  console.error('[drive-wizard] FAIL:', err);
  process.exit(1);
});
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_drive_wizard_script.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add dev/harness/drive-wizard.mjs dev/harness/package.json tests/test_drive_wizard_script.py
git commit -m "$(cat <<'MSG'
ci(setup): Playwright wizard walkthrough (D8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+133 passed.

---

### Task 47: dev/harness/README.md — usage + relation to lxd-validation skill

**Files:**
- Create: `dev/harness/README.md`
- Test: `tests/test_harness_readme.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_harness_readme.py`:

```python
from pathlib import Path
R = Path(__file__).parent.parent / "dev" / "harness" / "README.md"


def test_readme_exists():
    assert R.exists()


def test_readme_covers_setup_and_usage():
    text = R.read_text()
    assert "npm install" in text or "playwright install" in text
    assert "./wizard-ci.sh" in text or "wizard-ci.sh" in text


def test_readme_mentions_lxd_validation_skill():
    text = R.read_text()
    assert "lxd-validation" in text.lower()
    assert "deterministic" in text.lower() or "complementary" in text.lower()
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_harness_readme.py -v`
Expected: FAIL.

- [ ] **Step 3: Create dev/harness/README.md**

Sections:

- What this is: "deterministic LXD+Playwright walkthrough of the browser wizard".
- Setup: `cd dev/harness && npm install && npx playwright install chromium`.
- Usage: `./wizard-ci.sh --smoke` (short-circuit at Step 4) vs `--full` (runs the real pipeline).
- Relation to the `lxd-validation` skill: "The skill is agent-driven and exploratory — it dispatches multi-persona AI testers to catch usability gaps. This harness is deterministic and regression-focused — it pinpoints whether a known-good sequence of clicks still produces a healthy stack. Use both: skill catches new classes of problems, harness catches regressions."

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_harness_readme.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add dev/harness/README.md tests/test_harness_readme.py
git commit -m "$(cat <<'MSG'
docs(ci): wizard-ci harness usage + relation to lxd-validation skill

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+136 passed.

---

### Task 48: .github/workflows/wizard-ci.yml — manual dispatch workflow

**Files:**
- Create: `.github/workflows/wizard-ci.yml`
- Test: `tests/test_wizard_ci_workflow.py` (NEW)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_wizard_ci_workflow.py`:

```python
from pathlib import Path
WF = Path(__file__).parent.parent / ".github" / "workflows" / "wizard-ci.yml"


def test_workflow_exists():
    assert WF.exists()


def test_workflow_is_manual_dispatch_only():
    text = WF.read_text()
    assert "workflow_dispatch" in text
    # Must not be scheduled yet (explicit choice for this cycle)
    # Schedule block absent or commented
    assert "schedule:" not in text or "# schedule:" in text


def test_workflow_runs_harness():
    text = WF.read_text()
    assert "wizard-ci.sh" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_wizard_ci_workflow.py -v`
Expected: 3 FAIL.

- [ ] **Step 3: Create workflow**

Create `.github/workflows/wizard-ci.yml`:

```yaml
name: wizard-ci

# Manual dispatch only for now. To add a nightly schedule later, uncomment the
# schedule block below (cron: 7 AM UTC = midnight Pacific).
#
# schedule:
#   - cron: '0 7 * * *'

on:
  workflow_dispatch:
    inputs:
      mode:
        description: 'Harness mode (smoke runs ~3 min, full runs ~8 hr)'
        required: true
        default: 'smoke'
        type: choice
        options: [smoke, full]

jobs:
  wizard-ci:
    runs-on: self-hosted   # LXD requires root + local kernel; self-hosted Pi
    steps:
      - uses: actions/checkout@v4
      - name: Install harness deps
        working-directory: dev/harness
        run: |
          npm install
          npx playwright install chromium --with-deps
      - name: Run wizard harness
        run: ./dev/harness/wizard-ci.sh --${{ github.event.inputs.mode }}
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_wizard_ci_workflow.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/wizard-ci.yml tests/test_wizard_ci_workflow.py
git commit -m "$(cat <<'MSG'
ci(setup): manual-dispatch wizard-ci GitHub Actions workflow

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+139 passed.

**After Phase 9 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Then proceed to Phase 10.

---

## Phase 10 — Finalize

### Task 49: Add implementation-log entry

**Files:**
- Modify: `dev/implementation-log.md` (insert reverse-chronological entry at top)

**TDD preamble:** No code to test; we assert the entry is present.

- [ ] **Step 1: Write failing test**

Create `tests/test_implementation_log_entry.py`:

```python
from pathlib import Path
LOG = Path(__file__).parent.parent / "dev" / "implementation-log.md"


def test_log_has_today_setup_entry():
    text = LOG.read_text()
    assert "2026-04-18" in text
    assert "setup process remediation" in text.lower() or \
           "setup remediation" in text.lower()
    assert "B1" in text or "48 bugs" in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_implementation_log_entry.py -v`
Expected: FAIL if no entry yet.

- [ ] **Step 3: Insert entry**

Insert at the top of `dev/implementation-log.md`:

```markdown
## 2026-04-18 — Setup process remediation (v1.2 cycle)

**Scope:** 48 confirmed bugs (B1-B48) + 8 design decisions (D1-D8) + 3
out-of-scope items (O1-O3) across setup/main.py, setup/config.py,
setup/runner.py, setup/static/*, bootstrap.sh, docker-compose.yml,
nginx/entrypoint.sh, README.md.

**Outcome:** Wizard path is now end-to-end working on a fresh Debian
Trixie LXD container (verified via dev/harness/wizard-ci.sh --smoke).
Every .env VAR that docker-compose.yml references is emitted by
generate_env. TLS vocabulary canonicalized to http|https|tailscale.
Credentials flow through the keyring Unix socket (no more JSON
plaintext). PIPELINE_STEPS lifted to a frozen dataclass registry with
per-step command builders. Install-location UI finally wired through
to the running stack via symlink re-target on launch.

**Highlights:**
- New dev/harness/{wizard-ci.sh, drive-wizard.mjs} for regression
  testing the full setup flow in LXD.
- tools/build-tippecanoe.sh + bootstrap asset-download to eliminate
  the public-lands CAPTCHA + tippecanoe-from-source blockers.
- Shared showError helper in setup.js; all saves now awaited before
  navigation.
- Preflight now covers tippecanoe, python pipeline deps, keyring
  agent socket, cgroup memory, openssl. No more /api/fix-dependency
  (users re-run sudo ./bootstrap.sh with copy-paste).

**Deferred to v1.2 appendix (B44-B48):** response-shape unification,
preflight row-level UI nit, stderr color coding, tls-scan tool-missing
signal, post_credentials empty-field semantics (partially covered
already by skip-empty in Task 23).

**Pitfalls added to dev/testing-pitfalls.md:** TOCTOU in async
endpoints (from Task 30). The 11 pre-existing hunter-added pitfalls
all have at least one test in this cycle that would have caught the
bug.
```

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_implementation_log_entry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/implementation-log.md tests/test_implementation_log_entry.py
git commit -m "$(cat <<'MSG'
docs: implementation-log entry for setup remediation cycle

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+140 passed.

---

### Task 50: Deferred-bugs appendix in the plan

**Files:**
- Modify: `docs/superpowers/plans/2026-04-18-setup-process-remediation.md` (append appendix)

**TDD preamble:** Read TDD skill.

- [ ] **Step 1: Write failing test**

Create `tests/test_plan_has_deferred_appendix.py`:

```python
from pathlib import Path
PLAN = Path(__file__).parent.parent / "docs" / "superpowers" / "plans" / \
       "2026-04-18-setup-process-remediation.md"


def test_plan_has_deferred_section():
    text = PLAN.read_text()
    assert "## Deferred bugs" in text or "## Appendix" in text
    for b in ("B44", "B45", "B46", "B47", "B48"):
        assert b in text
```

- [ ] **Step 2: Run to verify FAIL**

Run: `python -m pytest tests/test_plan_has_deferred_appendix.py -v`
Expected: FAIL.

- [ ] **Step 3: Append appendix**

(See the "Deferred bugs (v1.2 appendix)" section appended below this task.)

- [ ] **Step 4: Run to verify PASS**

Run: `python -m pytest tests/test_plan_has_deferred_appendix.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-04-18-setup-process-remediation.md tests/test_plan_has_deferred_appendix.py
git commit -m "$(cat <<'MSG'
docs(plan): document deferred minor bugs (B44-B48)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Completion check:** Expect baseline+141 passed.

**After Phase 10 review loop:**
Carefully review the batch of work from multiple perspectives and revise/refine as appropriate.
Repeat review (minimum three rounds; if substantive issues remain in round 3, continue).
Update your private journal. Plan complete.

---

## Deferred bugs (v1.2 appendix)

These minor bugs are documented here but not fixed in this cycle. They are safe to defer because each is either cosmetic, user-invisible under normal operation, or already partially mitigated by a broader change in Phases 0-9.

- **B44 — Inconsistent response shapes across /api/fix-dependency, /api/tls/generate, /api/launch.**
  Location: `setup/main.py:261, 331, 574-579` (original lines).
  Why deferred: two of the three endpoints are deleted in this cycle (Tasks 14 and 38). The one remaining inconsistency (`/api/launch` returns `{exit_code, output, state, existing_count}` vs `/api/credentials` returns `{ok}`) is consumed correctly by the current frontend. A unification pass is nice-to-have, not blocking.
  Pick-up cost: 1-2 hours including frontend field-reads.

- **B45 — fixDependency re-renders entire preflight list on success.**
  Location: `setup/static/setup.js:604-605` (original lines).
  Why deferred: `fixDependency` + Install buttons are deleted in Task 38. Bug is moot.

- **B46 — Subprocess stderr warnings indistinguishable from stdout in log viewer.**
  Location: `setup/main.py:501-506`; `setup/static/setup.js:732-734`.
  Why deferred: cosmetic. Color-coding by `event.source` is a one-CSS-rule change plus a two-line JS change. Defer until the next UX polish cycle.
  Pick-up cost: 30 minutes.

- **B47 — /api/tls/scan swallows openssl errors.**
  Location: `setup/main.py:347-368`.
  Why deferred: `/api/tls/scan` endpoint is deleted in Task 14.

- **B48 — post_credentials writes empty-string fields.**
  Location: `setup/main.py:302-314`; `setup/static/setup.js:511-528`.
  Why deferred: partially fixed in Task 23 — the new keyring-socket handler skips empty values entirely. If the user clears a previously-set field in the UI and re-saves, the old keyring entry persists (the socket protocol has a `delete` action that isn't wired). That's a narrow edge case; document and defer.
  Pick-up cost: 30 minutes (add a delete-on-empty branch in `saveCredentials`).

- **O1 — Scripts module-level constants vs env vars.**
  Location: `scripts/acquire_imagery.py` module-level `M2M_BATCH_SIZE` et al.
  Why deferred: touches scripts/ territory, out of setup-subsystem scope. Part of the broader B30 remediation.
  Pick-up cost: 2-3 hours with regression tests.

- **B42 — INACTIVITY_TIMEOUT defined but never enforced.**
  Location: `setup/main.py:74-84, 110-111, 460, 499, 503`.
  Why deferred: The wizard is localhost-bound (Task 44 confirms 127.0.0.1) and invoked manually by an authenticated user. The timeout is minor risk — a user who walks away from the wizard exposes only their own session. Implementing requires a background asyncio task that sys.exit()s on idle, which adds complexity not warranted for the beta tester unblock. Deferred to v1.2.
  Pick-up cost: 1-2 hours.

> **Plan review history:**
> - Round 1 (2026-04-18): three parallel reviewers found ~40 issues; this plan file reflects Round 2 fixes for all blocking and moderate items.
> - Unresolved items are listed in the deferred appendix with pick-up-cost estimates.

---
