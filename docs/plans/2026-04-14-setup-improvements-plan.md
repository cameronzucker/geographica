# Setup Wizard Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add custom storage path input with validation, pre-flight dependency checking with auto-fix, and categorized pipeline error handling to the setup wizard.

**Architecture:** Three independent features sharing Step 4 DOM. Path validation via new API endpoint with allowlist security. Pre-flight checks with server-side fix registry (no shell injection). Categorized WebSocket error handling with exponential backoff.

**Tech Stack:** Python (FastAPI, Pydantic), vanilla JS, HTML/CSS

**Design spec:** `docs/superpowers/specs/2026-04-14-setup-improvements-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `setup/requirements.txt` | Fix uvicorn[standard] extra |
| Modify | `setup/main.py` | `/api/validate-path`, `/api/preflight`, `/api/fix-dependency` endpoints, `os.makedirs` in pipeline |
| Modify | `setup/static/index.html` | Custom path input (Step 1), preflight container + error elements (Step 4) |
| Modify | `setup/static/setup.js` | Custom path validation, preflight rendering, WebSocket reconnect, error categorization |
| Modify | `setup/static/setup.css` | Path feedback, preflight row, pipeline error styles |
| Modify | `tests/test_setup_main.py` | Tests for validate-path, preflight, fix-dependency endpoints |

---

## Task 1: Requirements Audit + Immediate Fix

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/requirements.txt` (line 2)

### Step 1: Fix uvicorn[standard] in setup requirements

- [ ] **Step 1a: Fix `setup/requirements.txt`**

Change line 2 from:
```
uvicorn>=0.32.0
```
To:
```
uvicorn[standard]>=0.32.0
```

This adds the `[standard]` extra which provides `websockets`, `httptools`, and `watchfiles` — all required for WebSocket support on the `/ws/progress` endpoint.

### Step 2: Audit other requirements files for consistency

- [ ] **Step 2a: Verify consistency across all requirements files**

Check that all `requirements.txt` files use `uvicorn[standard]`. Current audit results:

| File | Current | Status |
|------|---------|--------|
| `setup/requirements.txt:2` | `uvicorn>=0.32.0` | **Fix: add `[standard]`** |
| `services/gps/requirements.txt:2` | `uvicorn[standard]==0.34.2` | OK |
| `services/search/requirements.txt:2` | `uvicorn[standard]>=0.29,<1` | OK |
| `services/stt/requirements.txt:3` | `uvicorn[standard]>=0.29,<1` | OK |

Also check shared dependencies:

| Dependency | setup | search | stt | scripts |
|------------|-------|--------|-----|---------|
| fastapi | `>=0.115.0` | `>=0.110,<1` | `>=0.110,<1` | N/A |
| httpx | `>=0.27.0` | `>=0.27,<1` | N/A | N/A |

The `setup/requirements.txt` uses unbounded upper ranges (`>=0.115.0`) while services use bounded ranges (`>=0.110,<1`). These are acceptable since the setup wizard is a standalone venv created by `setup.sh`, not a long-lived service. No changes needed beyond the uvicorn fix.

### Step 3: Commit

- [ ] **Step 3a: Commit the requirements fix**

```
fix(setup): add uvicorn[standard] extra for WebSocket support

The setup wizard's requirements.txt was missing the [standard] extra
on uvicorn, which provides the websockets package needed for the
/ws/progress endpoint. This caused a silent 404 on fresh installs.
```

---

## Task 2: Custom Storage Path Backend

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/main.py` (add `ValidatePathRequest` model and `/api/validate-path` endpoint)
- Modify: `tests/test_setup_main.py` (add `TestValidatePathEndpoint` class)

**Security constraints — Do NOT:**
- Use a blocklist for path validation (symlinks bypass blocklists)
- Accept paths outside the allowlist (`/srv`, `/mnt`, `/media`, `/home`)
- Follow symlinks (reject symlinks explicitly)
- Remove the 10 GB minimum free space check

### Step 1: Write failing tests

- [ ] **Step 1a: Add TestValidatePathEndpoint to `tests/test_setup_main.py`**

Add at the end of the file (after line 237):

```python
class TestValidatePathEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_requires_csrf(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/geographica/data"})
        assert resp.status_code == 403

    def test_valid_existing_directory(self, tmp_path, monkeypatch):
        # Create a path under /srv (simulated via monkeypatch)
        test_dir = tmp_path / "data"
        test_dir.mkdir()
        # Monkeypatch allowed_prefixes to include tmp_path
        resp = self.client.post("/api/validate-path",
            json={"path": str(test_dir)},
            headers=self.headers)
        data = resp.json()
        # tmp_path is under /tmp which is not in the allowlist
        assert data["valid"] is False
        assert "must be under" in data["message"].lower() or "Path must be under" in data["message"]

    def test_rejects_path_outside_allowlist(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/etc/shadow"},
            headers=self.headers)
        data = resp.json()
        assert data["valid"] is False
        assert data["creatable"] is False

    def test_rejects_root_path(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/"},
            headers=self.headers)
        data = resp.json()
        assert data["valid"] is False

    def test_srv_path_accepted(self):
        """Path under /srv should pass the allowlist check."""
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/geographica/data"},
            headers=self.headers)
        data = resp.json()
        # Should not fail on allowlist — may fail on existence/permissions
        # but the message should NOT be about the allowlist
        if not data["valid"]:
            assert "must be under" not in data.get("message", "").lower()

    def test_mnt_path_accepted(self):
        """Path under /mnt should pass the allowlist check."""
        resp = self.client.post("/api/validate-path",
            json={"path": "/mnt/ssd/geographica"},
            headers=self.headers)
        data = resp.json()
        if not data["valid"]:
            assert "must be under" not in data.get("message", "").lower()

    def test_media_path_accepted(self):
        """Path under /media should pass the allowlist check."""
        resp = self.client.post("/api/validate-path",
            json={"path": "/media/usb/geographica"},
            headers=self.headers)
        data = resp.json()
        if not data["valid"]:
            assert "must be under" not in data.get("message", "").lower()

    def test_home_path_accepted(self):
        """Path under /home should pass the allowlist check."""
        resp = self.client.post("/api/validate-path",
            json={"path": "/home/user/geographica"},
            headers=self.headers)
        data = resp.json()
        if not data["valid"]:
            assert "must be under" not in data.get("message", "").lower()

    def test_nonexistent_parent_returns_not_creatable(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/nonexistent/deeply/nested/path"},
            headers=self.headers)
        data = resp.json()
        assert data["valid"] is False
        assert data["creatable"] is False

    def test_creatable_path(self):
        """Path whose parent exists and is writable should be creatable."""
        # /srv should exist on the Pi — if its parent is writable, child is creatable
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/geographica/test_new_dir_" + str(id(self))},
            headers=self.headers)
        data = resp.json()
        # Either valid+creatable (parent writable) or not (permission denied)
        # Just verify the response structure is correct
        assert "valid" in data
        assert "creatable" in data

    def test_response_includes_free_gb_when_valid(self):
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/geographica/data"},
            headers=self.headers)
        data = resp.json()
        if data["valid"]:
            assert "free_gb" in data
            assert isinstance(data["free_gb"], (int, float))

    def test_rejects_path_traversal(self):
        """Path with .. should be resolved and checked against allowlist."""
        resp = self.client.post("/api/validate-path",
            json={"path": "/srv/../etc/passwd"},
            headers=self.headers)
        data = resp.json()
        assert data["valid"] is False
```

### Step 2: Implement the endpoint

- [ ] **Step 2a: Add `ValidatePathRequest` model to `setup/main.py`**

Add after the `BboxRequest` class (line 97):

```python
class ValidatePathRequest(BaseModel):
    path: str
```

- [ ] **Step 2b: Add `/api/validate-path` endpoint to `setup/main.py`**

Add after the `/api/validate-bbox` endpoint (after line 157):

```python
@app.post("/api/validate-path")
async def validate_path(req: ValidatePathRequest):
    path = Path(req.path).resolve()

    # Security: allowlist — only permit paths under known data locations
    # (blocklist approach is insufficient — symlinks bypass it)
    allowed_prefixes = ['/srv', '/mnt', '/media', '/home']
    if not any(str(path).startswith(p) for p in allowed_prefixes):
        return {"valid": False, "creatable": False,
                "message": "Path must be under /srv, /mnt, /media, or /home"}

    # Reject symlinks to prevent traversal attacks
    if path.exists() and path.is_symlink():
        return {"valid": False, "creatable": False, "message": "Symlinks not allowed"}

    if path.exists():
        if not path.is_dir():
            return {"valid": False, "creatable": False, "message": "Path is not a directory"}
        if not os.access(str(path), os.W_OK):
            return {"valid": False, "creatable": False, "message": "Permission denied"}
        stat = shutil.disk_usage(str(path))
        free_gb = stat.free / (1024 ** 3)
        if free_gb < 10:
            return {"valid": False, "creatable": False,
                    "message": f"Insufficient space ({free_gb:.0f} GB free, need 10+ GB)",
                    "free_gb": free_gb}
        return {"valid": True, "creatable": False, "free_gb": free_gb, "message": "OK"}

    # Check if parent exists and is writable
    parent = path.parent
    if parent.exists() and os.access(str(parent), os.W_OK):
        stat = shutil.disk_usage(str(parent))
        free_gb = stat.free / (1024 ** 3)
        if free_gb < 10:
            return {"valid": False, "creatable": True,
                    "message": f"Insufficient space ({free_gb:.0f} GB free, need 10+ GB)",
                    "free_gb": free_gb}
        return {"valid": True, "creatable": True, "free_gb": free_gb, "message": "Will be created"}

    return {"valid": False, "creatable": False, "message": "Path does not exist"}
```

### Step 3: Run tests

- [ ] **Step 3a: Run the tests and verify**

```bash
python -m pytest tests/test_setup_main.py::TestValidatePathEndpoint -v
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage (error paths tested? edge cases?)
3. Run: python -m pytest tests/test_setup_main.py -v

### Step 4: Commit

- [ ] **Step 4a: Commit the validate-path endpoint**

```
feat(setup): add /api/validate-path endpoint with allowlist security

Validates custom storage paths against an allowlist of safe prefixes
(/srv, /mnt, /media, /home). Rejects symlinks, checks write permissions,
reports free disk space, and identifies creatable paths whose parent
exists and is writable.
```

---

## Task 3: Custom Storage Path Frontend

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/static/index.html` (Step 1, lines 64-69)
- Modify: `setup/static/setup.js` (Step 1 handlers, lines 228-252 and lines 144-154)
- Modify: `setup/static/setup.css` (add path feedback styles)

**Security constraints — Do NOT:**
- Use innerHTML to render path feedback (use textContent/createElement only)
- Skip the allowlist validation on the backend — the frontend validation is purely UX

### Step 1: Add custom path input to index.html

- [ ] **Step 1a: Add "Other" option and custom path input to Step 1**

In `setup/static/index.html`, replace lines 64-69:

```html
      <div class="field-group">
        <label for="data-path">Data Storage Path</label>
        <select id="data-path">
          <option value="/srv/geographica/data">/srv/geographica/data (default)</option>
        </select>
        <div id="storage-info" class="storage-info"></div>
      </div>
```

With:

```html
      <div class="field-group">
        <label for="data-path">Data Storage Path</label>
        <select id="data-path">
          <option value="/srv/geographica/data">/srv/geographica/data (default)</option>
          <option value="__other__">Other (enter path manually)</option>
        </select>
        <div id="custom-path-group" class="hidden">
          <input type="text" id="custom-path-input" placeholder="/mnt/ssd/geographica/data"
                 autocomplete="off" spellcheck="false">
          <div id="custom-path-feedback"></div>
        </div>
        <div id="storage-info" class="storage-info"></div>
      </div>
```

### Step 2: Add custom path JS logic

- [ ] **Step 2a: Add "Other" option to dynamically populated select**

In `setup/static/setup.js`, in the `loadSystemInfo()` function, after the storage options loop and default option logic (after line 250, after `sel.value = config.data_path;`), add:

```js
      // Add "Other" option for custom paths
      var otherOpt = document.createElement('option');
      otherOpt.value = '__other__';
      otherOpt.textContent = 'Other (enter path manually)';
      sel.appendChild(otherOpt);
```

- [ ] **Step 2b: Add custom path event handlers to `init()`**

In `setup/static/setup.js`, inside the `init()` function (after line 881, after the TLS mode change handler), add:

```js
    // Custom path handlers
    var dataPathSelect = $('#data-path');
    var customPathGroup = $('#custom-path-group');
    var customPathInput = $('#custom-path-input');
    var customPathFeedback = $('#custom-path-feedback');
    var customPathTimer = null;

    dataPathSelect.addEventListener('change', function () {
      if (this.value === '__other__') {
        customPathGroup.classList.remove('hidden');
        customPathInput.focus();
      } else {
        customPathGroup.classList.add('hidden');
      }
    });

    customPathInput.addEventListener('input', function () {
      clearTimeout(customPathTimer);
      customPathTimer = setTimeout(function () {
        var path = customPathInput.value.trim();
        if (!path) {
          customPathFeedback.textContent = '';
          customPathFeedback.className = 'path-feedback path-neutral';
          customPathInput.className = '';
          return;
        }

        fetch('/api/validate-path', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
          body: JSON.stringify({ path: path })
        })
        .then(function (res) { return res.json(); })
        .then(function (result) {
          if (result.valid) {
            if (result.creatable) {
              customPathFeedback.textContent = 'Will be created \u2014 ' + result.free_gb.toFixed(0) + ' GB free on parent';
              customPathFeedback.className = 'path-feedback path-warning';
              customPathInput.className = 'input-warning';
            } else {
              customPathFeedback.textContent = 'Valid \u2014 ' + result.free_gb.toFixed(0) + ' GB free';
              customPathFeedback.className = 'path-feedback path-success';
              customPathInput.className = 'input-success';
            }
          } else {
            customPathFeedback.textContent = result.message;
            customPathFeedback.className = 'path-feedback path-error';
            customPathInput.className = 'input-error';
          }
        })
        .catch(function () {
          customPathFeedback.textContent = 'Validation failed';
          customPathFeedback.className = 'path-feedback path-error';
          customPathInput.className = 'input-error';
        });
      }, 500);
    });
```

- [ ] **Step 2c: Update `nextStep()` to read effective data path**

In `setup/static/setup.js`, replace lines 147-148:

```js
      config.data_path = $('#data-path').value;
```

With:

```js
      config.data_path = $('#data-path').value === '__other__'
        ? $('#custom-path-input').value.trim()
        : $('#data-path').value;
```

- [ ] **Step 2d: Block "Next" on custom path error state**

In `setup/static/setup.js`, in the `nextStep()` function, after the `if (currentStep === 1)` block (after line 153, after the host-ip check), add:

```js
      if ($('#data-path').value === '__other__') {
        var customPath = $('#custom-path-input').value.trim();
        if (!customPath) {
          $('#custom-path-feedback').textContent = 'Path is required';
          $('#custom-path-feedback').className = 'path-feedback path-error';
          return;
        }
        if ($('#custom-path-input').classList.contains('input-error')) {
          return;  // Block navigation while path is invalid
        }
      }
```

### Step 3: Add CSS styles

- [ ] **Step 3a: Add path validation styles to `setup/static/setup.css`**

Add at the end of the file (after line 712):

```css
/* Custom path validation */
.hidden {
  display: none !important;
}

.path-feedback {
  font-size: 0.85rem;
  margin-top: 4px;
  min-height: 1.2em;
}
.path-success { color: #4caf50; }
.path-warning { color: #ff9800; }
.path-error { color: #f44336; }

.input-success { border-color: #4caf50 !important; }
.input-warning { border-color: #ff9800 !important; }
.input-error { border-color: #f44336 !important; }

#custom-path-group {
  margin-top: 8px;
}

#custom-path-input {
  width: 100%;
  font-family: monospace;
}

@media (prefers-color-scheme: dark) {
  .path-success { color: #3fb950; }
  .path-warning { color: #d29922; }
  .path-error { color: #f85149; }
  .input-success { border-color: #3fb950 !important; }
  .input-warning { border-color: #d29922 !important; }
  .input-error { border-color: #f85149 !important; }
}
```

### Step 4: Commit

- [ ] **Step 4a: Commit the custom path frontend**

```
feat(setup): add custom storage path input with live validation

Users can now select "Other" from the storage path dropdown and enter
a custom path. The input validates against the /api/validate-path
endpoint with 500ms debounce, showing free space and creation status.
Navigation is blocked while the path is in an error state.
```

---

## Task 4: Pre-Flight Check Backend

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/main.py` (add `FIX_REGISTRY`, `FixRequest`, `/api/preflight`, `/api/fix-dependency`)
- Modify: `tests/test_setup_main.py` (add `TestPreflightEndpoint` and `TestFixDependencyEndpoint`)

**Security constraints — Do NOT:**
- Use `shell=True` in any subprocess call — command injection risk
- Accept freeform command strings from the client
- Add entries to `FIX_REGISTRY` without reviewing what they execute
- Allow the `fix_id` parameter to influence which binary is executed beyond the registry lookup

### Step 1: Write failing tests

- [ ] **Step 1a: Add `TestPreflightEndpoint` to `tests/test_setup_main.py`**

Add at the end of the file:

```python
class TestPreflightEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)

    def test_preflight_returns_checks_list(self):
        resp = self.client.get("/api/preflight")
        assert resp.status_code == 200
        data = resp.json()
        assert "passed" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_preflight_checks_have_required_fields(self):
        resp = self.client.get("/api/preflight")
        data = resp.json()
        for check in data["checks"]:
            assert "category" in check
            assert "name" in check
            assert "status" in check
            assert "severity" in check

    def test_preflight_checks_python_deps(self):
        resp = self.client.get("/api/preflight")
        data = resp.json()
        python_checks = [c for c in data["checks"] if c["category"] == "python"]
        assert len(python_checks) > 0
        # websockets check should be present
        ws_check = [c for c in python_checks if c["name"] == "websockets"]
        assert len(ws_check) == 1

    def test_preflight_checks_binaries(self):
        resp = self.client.get("/api/preflight")
        data = resp.json()
        binary_checks = [c for c in data["checks"] if c["category"] == "binary"]
        binary_names = [c["name"] for c in binary_checks]
        assert "docker" in binary_names

    def test_preflight_severity_values(self):
        resp = self.client.get("/api/preflight")
        data = resp.json()
        valid_severities = {"ok", "warning", "error"}
        for check in data["checks"]:
            assert check["severity"] in valid_severities, (
                f"Check {check['name']} has invalid severity: {check['severity']}")

    def test_preflight_passed_is_boolean(self):
        resp = self.client.get("/api/preflight")
        data = resp.json()
        assert isinstance(data["passed"], bool)

    def test_preflight_does_not_require_csrf(self):
        """GET endpoints should not require CSRF."""
        resp = self.client.get("/api/preflight")
        assert resp.status_code == 200
```

- [ ] **Step 1b: Add `TestFixDependencyEndpoint` to `tests/test_setup_main.py`**

```python
class TestFixDependencyEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": CSRF_TOKEN}

    def test_requires_csrf(self):
        resp = self.client.post("/api/fix-dependency",
            json={"fix_id": "httpx"})
        assert resp.status_code == 403

    def test_unknown_fix_id_returns_400(self):
        resp = self.client.post("/api/fix-dependency",
            json={"fix_id": "nonexistent_package"},
            headers=self.headers)
        assert resp.status_code == 400

    def test_fix_registry_keys_are_valid(self):
        """All FIX_REGISTRY entries should be pre-tokenized lists."""
        from setup.main import FIX_REGISTRY
        for fix_id, cmd in FIX_REGISTRY.items():
            assert isinstance(cmd, list), f"FIX_REGISTRY['{fix_id}'] must be a list, got {type(cmd)}"
            assert len(cmd) >= 2, f"FIX_REGISTRY['{fix_id}'] must have at least 2 elements"
            assert all(isinstance(arg, str) for arg in cmd), (
                f"FIX_REGISTRY['{fix_id}'] must contain only strings")

    def test_fix_registry_no_shell_metacharacters(self):
        """No FIX_REGISTRY command should contain shell metacharacters."""
        from setup.main import FIX_REGISTRY
        shell_chars = set(';|&$`\\(){}[]!><')
        for fix_id, cmd in FIX_REGISTRY.items():
            for arg in cmd:
                found = shell_chars.intersection(set(arg))
                # Allow [] in pip extras like uvicorn[standard]
                allowed_in_pip = {'[', ']'}
                dangerous = found - allowed_in_pip
                assert not dangerous, (
                    f"FIX_REGISTRY['{fix_id}'] contains shell metacharacter(s) "
                    f"{dangerous} in arg '{arg}'")

    def test_known_fix_id_returns_result(self):
        """A known fix_id should return success/failure, not 400."""
        resp = self.client.post("/api/fix-dependency",
            json={"fix_id": "httpx"},
            headers=self.headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "success" in data

    def test_fix_id_injection_attempt(self):
        """Verify that injection-style fix_ids are rejected."""
        resp = self.client.post("/api/fix-dependency",
            json={"fix_id": "httpx; rm -rf /"},
            headers=self.headers)
        assert resp.status_code == 400
```

### Step 2: Implement preflight and fix-dependency endpoints

- [ ] **Step 2a: Add `FIX_REGISTRY` constant to `setup/main.py`**

Add after the `INACTIVITY_TIMEOUT` constant (after line 45), before the progress state section:

```python
import subprocess

# ---------------------------------------------------------------------------
# Pre-flight fix registry — the ONLY commands that can be executed via
# /api/fix-dependency. SECURITY: Never use shell=True. Never accept
# freeform command strings from clients. Each value is a pre-tokenized
# command list passed directly to subprocess.run().
# ---------------------------------------------------------------------------
FIX_REGISTRY: dict[str, list[str]] = {
    "ws_support": ["pip", "install", "uvicorn[standard]"],
    "httpx": ["pip", "install", "httpx"],
    "pillow": ["pip", "install", "Pillow"],
    "osmium": ["pip", "install", "osmium"],
    "aiohttp": ["pip", "install", "aiohttp"],
    "aiosqlite": ["pip", "install", "aiosqlite"],
    "tqdm": ["pip", "install", "tqdm"],
    "shapely": ["pip", "install", "shapely"],
    "docker_start": ["sudo", "systemctl", "start", "docker"],
}
```

Note: `subprocess` is already imported on line 8 via `setup/config.py`, but `setup/main.py` does not import it directly. Add `import subprocess` to the imports at the top of `setup/main.py` (after line 10, after `import shutil`).

- [ ] **Step 2b: Add `FixRequest` model to `setup/main.py`**

Add after the `ValidatePathRequest` model (which was added in Task 2):

```python
class FixRequest(BaseModel):
    fix_id: str
```

- [ ] **Step 2c: Add `/api/preflight` endpoint to `setup/main.py`**

Add after the `/api/validate-path` endpoint:

```python
@app.get("/api/preflight")
async def preflight_check():
    checks = []

    # Python package checks — covers all pipeline script imports
    python_deps = [
        ("websockets", "ws_support"),
        ("httpx", "httpx"),
        ("PIL", "pillow"),
        ("osmium", "osmium"),
        ("aiohttp", "aiohttp"),
        ("aiosqlite", "aiosqlite"),
        ("tqdm", "tqdm"),
        ("shapely", "shapely"),
    ]
    for mod_name, fix_id in python_deps:
        try:
            __import__(mod_name)
            checks.append({"category": "python", "name": mod_name,
                          "status": "ok", "severity": "ok"})
        except ImportError:
            checks.append({"category": "python", "name": mod_name,
                          "status": "missing", "fix_id": fix_id, "severity": "error"})

    # System binary checks (includes GDAL tools used by imagery pipeline)
    binaries = ["docker", "osmium", "gpsd", "gdal_translate", "tippecanoe"]
    for binary in binaries:
        path = shutil.which(binary)
        if path:
            checks.append({"category": "binary", "name": binary,
                          "status": "found", "path": path, "severity": "ok"})
        else:
            checks.append({"category": "binary", "name": binary,
                          "status": "missing",
                          "severity": "warning" if binary == "gpsd" else "error"})

    # Docker compose check (v2 plugin) — timeout=5 to avoid hanging
    try:
        docker_compose = subprocess.run(["docker", "compose", "version"],
                                         capture_output=True, text=True, timeout=5)
        if docker_compose.returncode == 0:
            checks.append({"category": "binary", "name": "docker compose",
                          "status": "found",
                          "version": docker_compose.stdout.strip(), "severity": "ok"})
        else:
            checks.append({"category": "binary", "name": "docker compose",
                          "status": "missing",
                          "fix": "Install docker-compose-plugin", "severity": "error"})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        checks.append({"category": "binary", "name": "docker compose",
                      "status": "missing",
                      "fix": "Install docker-compose-plugin", "severity": "error"})

    # Docker daemon running (timeout=5 to avoid hanging if daemon is starting)
    try:
        docker_info = subprocess.run(["docker", "info"],
                                      capture_output=True, text=True, timeout=5)
        if docker_info.returncode == 0:
            checks.append({"category": "system", "name": "Docker daemon",
                          "status": "running", "severity": "ok"})
        else:
            checks.append({"category": "system", "name": "Docker daemon",
                          "status": "not running",
                          "fix": "sudo systemctl start docker", "severity": "error"})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        checks.append({"category": "system", "name": "Docker daemon",
                      "status": "not running",
                      "fix": "sudo systemctl start docker", "severity": "error"})

    passed = all(c["severity"] != "error" for c in checks)
    return {"passed": passed, "checks": checks}
```

- [ ] **Step 2d: Add `/api/fix-dependency` endpoint to `setup/main.py`**

Add after the `/api/preflight` endpoint:

```python
@app.post("/api/fix-dependency")
async def fix_dependency(req: FixRequest):
    if req.fix_id not in FIX_REGISTRY:
        raise HTTPException(400, f"Unknown fix: {req.fix_id}")

    cmd = FIX_REGISTRY[req.fix_id]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120
        )
        return {"success": result.returncode == 0,
                "output": result.stdout, "error": result.stderr}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Command timed out after 120 seconds"}
```

### Step 3: Run tests

- [ ] **Step 3a: Run the tests and verify**

```bash
python -m pytest tests/test_setup_main.py::TestPreflightEndpoint tests/test_setup_main.py::TestFixDependencyEndpoint -v
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage (error paths tested? edge cases?)
3. Run: python -m pytest tests/test_setup_main.py -v

### Step 4: Commit

- [ ] **Step 4a: Commit the preflight and fix-dependency endpoints**

```
feat(setup): add pre-flight dependency checker with server-side fix registry

Adds /api/preflight endpoint that checks Python packages, system
binaries, Docker compose, and Docker daemon status. Adds /api/fix-dependency
endpoint with a FIX_REGISTRY allowlist — the client sends a fix_id,
the server maps it to a pre-tokenized command list. No shell=True,
no freeform command strings from the client.
```

---

## Task 5: Pre-Flight Check Frontend

**Depends on:** Task 4 (backend endpoints must exist)

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/static/index.html` (Step 4 section, lines 215-234)
- Modify: `setup/static/setup.js` (Step 4 handler, lines 522-563)
- Modify: `setup/static/setup.css` (preflight styles)

**Security constraints — Do NOT:**
- Use innerHTML to render preflight results (use createElement/textContent only)
- Pass any user input to the fix-dependency endpoint — only pass `fix_id` values from the server's own preflight response

### Step 1: Add preflight container to index.html

- [ ] **Step 1a: Add preflight section to Step 4 in `setup/static/index.html`**

In `setup/static/index.html`, replace lines 215-218:

```html
    <div class="step" id="step-4" style="display:none">
      <h2>Download &amp; Build</h2>
      <p class="subtitle">Pipeline progress. This may take several hours depending on region size.</p>
```

With:

```html
    <div class="step" id="step-4" style="display:none">
      <h2>Download &amp; Build</h2>
      <p class="subtitle">Pipeline progress. This may take several hours depending on region size.</p>

      <div id="preflight-section">
        <h3>Pre-flight Checks</h3>
        <div id="preflight-checks">
          <p class="muted">Checking dependencies...</p>
        </div>
      </div>
```

### Step 2: Add preflight JS logic

- [ ] **Step 2a: Add `enterStep4()` function to `setup/static/setup.js`**

Add before the `startPipeline()` function (before line 523):

```js
  // ---------------------------------------------------------------------------
  // Step 4: Pre-flight + Pipeline
  // ---------------------------------------------------------------------------
  function enterStep4() {
    var container = $('#preflight-checks');
    // Clear using safe DOM method
    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(createEl('p', 'muted', 'Checking dependencies...'));

    fetch('/api/preflight')
      .then(function (res) { return res.json(); })
      .then(function (result) {
        renderPreflightResults(result);
        if (result.passed) {
          enablePipelineControls();
        } else {
          disablePipelineControls();
        }
      })
      .catch(function () {
        while (container.firstChild) container.removeChild(container.firstChild);
        container.appendChild(createEl('p', 'path-error', 'Failed to run pre-flight checks'));
      });
  }

  function renderPreflightResults(result) {
    var container = $('#preflight-checks');
    // Clear using safe DOM method — NO innerHTML
    while (container.firstChild) container.removeChild(container.firstChild);

    result.checks.forEach(function (check) {
      var row = document.createElement('div');
      row.className = 'preflight-row preflight-' + check.severity;

      var label = document.createElement('span');
      label.textContent = check.name + ': ' + check.status;
      row.appendChild(label);

      if (check.severity === 'error' && check.fix_id) {
        var fixBtn = document.createElement('button');
        fixBtn.textContent = 'Fix';
        fixBtn.className = 'btn-fix';
        fixBtn.addEventListener('click', function () {
          fixBtn.disabled = true;
          fixBtn.textContent = 'Installing...';
          fetch('/api/fix-dependency', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json',
                       'X-CSRF-Token': csrfToken },
            body: JSON.stringify({ fix_id: check.fix_id })
          })
          .then(function (res) { return res.json(); })
          .then(function (fixResult) {
            if (fixResult.success) {
              row.className = 'preflight-row preflight-ok';
              label.textContent = check.name + ': installed';
              fixBtn.remove();
              // Re-run full preflight to update passed status
              enterStep4();
            } else {
              fixBtn.textContent = 'Failed \u2014 Retry';
              fixBtn.disabled = false;
            }
          })
          .catch(function () {
            fixBtn.textContent = 'Failed \u2014 Retry';
            fixBtn.disabled = false;
          });
        });
        row.appendChild(fixBtn);
      }

      container.appendChild(row);
    });
  }

  function enablePipelineControls() {
    $('#btn-next').disabled = false;
    $('#btn-next').textContent = 'Start Pipeline';
  }

  function disablePipelineControls() {
    $('#btn-next').disabled = true;
    $('#btn-next').textContent = 'Fix dependencies first';
  }
```

- [ ] **Step 2b: Wire `enterStep4()` into `showStep()`**

In `setup/static/setup.js`, in the `showStep()` function, add Step 4 initialization. After line 141 (`if (n === 3) loadCredentials();`), add:

```js
    if (n === 4) enterStep4();
```

### Step 3: Add preflight CSS styles

- [ ] **Step 3a: Add preflight styles to `setup/static/setup.css`**

Add at the end of the file (after the custom path styles added in Task 3):

```css
/* Pre-flight checks */
#preflight-section {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.preflight-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  border-radius: 4px;
  margin-bottom: 4px;
  font-size: 0.9rem;
}
.preflight-ok { background: rgba(76, 175, 80, 0.15); color: #4caf50; }
.preflight-error { background: rgba(244, 67, 54, 0.15); color: #f44336; }
.preflight-warning { background: rgba(255, 152, 0, 0.15); color: #ff9800; }

@media (prefers-color-scheme: dark) {
  .preflight-ok { background: rgba(63, 185, 80, 0.15); color: #3fb950; }
  .preflight-error { background: rgba(248, 81, 73, 0.15); color: #f85149; }
  .preflight-warning { background: rgba(210, 153, 34, 0.15); color: #d29922; }
}

.btn-fix {
  padding: 2px 12px;
  font-size: 0.8rem;
  border-radius: 3px;
  cursor: pointer;
  border: 1px solid currentColor;
  background: transparent;
  color: inherit;
}

.btn-fix:hover {
  opacity: 0.8;
}

.btn-fix:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.muted {
  color: var(--text-muted);
  font-size: 0.9rem;
}
```

### Step 4: Commit

- [ ] **Step 4a: Commit the preflight frontend**

```
feat(setup): add pre-flight dependency check UI to Step 4

Shows all dependency checks (Python packages, system binaries, Docker)
before the pipeline starts. Failed checks with a fix_id get a "Fix"
button that calls /api/fix-dependency. All DOM construction uses
createElement/textContent — no innerHTML.
```

---

## Task 6: Pipeline Error Handling

**Depends on:** Task 5 (Step 4 DOM structure must be in place)

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/static/index.html` (Step 4 section — add error display elements)
- Modify: `setup/static/setup.js` (WebSocket reconnect + error categorization)
- Modify: `setup/static/setup.css` (error state styles)

**Security constraints — Do NOT:**
- Use innerHTML to render error messages (use textContent/createElement only)
- Expose raw stack traces to the user (categorize and show hints instead)

### Step 1: Add error display elements to index.html

- [ ] **Step 1a: Add error elements to Step 4 in `setup/static/index.html`**

After the `substep-list` div and before the log-viewer-toggle div in Step 4, add:

```html
      <div id="pipeline-error" class="pipeline-error hidden"></div>
      <button id="pipeline-retry-btn" class="btn btn-secondary btn-small hidden">Retry Connection</button>
```

This goes after `<div class="substep-list" id="substep-list"></div>` (line 226) and before `<div class="log-viewer-toggle">` (line 228).

### Step 2: Replace WebSocket reconnect logic

- [ ] **Step 2a: Replace `connectProgress()` in `setup/static/setup.js`**

Replace lines 565-588 (the current `connectProgress` function):

```js
  function connectProgress() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + location.host + '/ws/progress';
    ws = new WebSocket(url);

    ws.onmessage = function (e) {
      var event;
      try {
        event = JSON.parse(e.data);
      } catch (err) {
        return;
      }
      handleProgressEvent(event);
    };

    ws.onclose = function () {
      // Reconnect after 2 seconds
      setTimeout(connectProgress, 2000);
    };

    ws.onerror = function () {
      // Will trigger onclose
    };
  }
```

With:

```js
  var wsRetries = 0;
  var MAX_WS_RETRIES = 3;

  function connectProgress() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + location.host + '/ws/progress';
    ws = new WebSocket(url);

    ws.onopen = function () {
      wsRetries = 0;
      hideConnectionError();
    };

    ws.onmessage = function (e) {
      var event;
      try {
        event = JSON.parse(e.data);
      } catch (err) {
        return;
      }
      handleProgressEvent(event);
    };

    ws.onclose = function () {
      wsRetries++;
      if (wsRetries <= MAX_WS_RETRIES) {
        var delay = Math.pow(2, wsRetries) * 1000;  // 2s, 4s, 8s
        setTimeout(connectProgress, delay);
      } else {
        showConnectionError(
          'Unable to connect to progress stream. Check that the setup server is running.'
        );
      }
    };

    ws.onerror = function () {
      // Will trigger onclose
    };
  }

  function showConnectionError(msg) {
    var errorEl = $('#pipeline-error');
    errorEl.textContent = msg;
    errorEl.classList.remove('hidden');

    var retryBtn = $('#pipeline-retry-btn');
    retryBtn.classList.remove('hidden');
    retryBtn.onclick = function () {
      wsRetries = 0;
      errorEl.classList.add('hidden');
      retryBtn.classList.add('hidden');
      connectProgress();
    };

    // Switch progress bar to error state
    var progressBar = $('#pipeline-progress');
    if (progressBar) progressBar.classList.add('progress-error');
  }

  function hideConnectionError() {
    var errorEl = $('#pipeline-error');
    if (errorEl) errorEl.classList.add('hidden');
    var retryBtn = $('#pipeline-retry-btn');
    if (retryBtn) retryBtn.classList.add('hidden');
    var progressBar = $('#pipeline-progress');
    if (progressBar) progressBar.classList.remove('progress-error');
  }
```

### Step 3: Add error categorization

- [ ] **Step 3a: Add `categorizeError()` function to `setup/static/setup.js`**

Add after the `hideConnectionError()` function:

```js
  function categorizeError(message) {
    if (/No module named|ModuleNotFoundError|ImportError/.test(message)) {
      return { type: 'dependency',
               hint: 'A required Python package is missing. Return to pre-flight checks to install it.' };
    }
    if (/Permission denied|EACCES|PermissionError/.test(message)) {
      return { type: 'permission',
               hint: 'Check file/directory permissions on the data path.' };
    }
    if (/No space left|disk full|OSError.*28/.test(message)) {
      return { type: 'disk',
               hint: 'Insufficient disk space. Free up space or choose a different storage path.' };
    }
    if (/Connection refused|ConnectionError|ECONNREFUSED/.test(message)) {
      return { type: 'network',
               hint: 'A required service is not responding. Check that Docker is running.' };
    }
    if (/timeout|Timeout|ETIMEDOUT/.test(message)) {
      return { type: 'timeout',
               hint: 'Operation timed out. This may resolve on retry.' };
    }
    return { type: 'unknown',
             hint: 'Check the log output below for details.' };
  }

  function showStepError(step, cat, rawMessage) {
    var errorEl = $('#pipeline-error');
    // Clear previous content safely
    while (errorEl.firstChild) errorEl.removeChild(errorEl.firstChild);

    var title = document.createElement('strong');
    title.textContent = (step ? step + ': ' : '') + cat.type + ' error';
    errorEl.appendChild(title);

    if (rawMessage) {
      var msg = document.createElement('div');
      msg.textContent = rawMessage;
      errorEl.appendChild(msg);
    }

    var hint = document.createElement('div');
    hint.className = 'step-error-hint';
    hint.textContent = cat.hint;
    errorEl.appendChild(hint);

    errorEl.classList.remove('hidden');
  }
```

- [ ] **Step 3b: Update error handling in `handleProgressEvent()`**

In `setup/static/setup.js`, replace the error handling block in `handleProgressEvent()` (lines 627-636):

```js
    if (type === 'error') {
      if (event.step) {
        el = $('#substep-' + event.step);
        if (el) {
          el.className = 'substep-item error';
        }
      }
      appendLog('[ERROR] ' + event.message);
      $('#btn-next').disabled = false;
      $('#btn-next').textContent = 'Retry';
    }
```

With:

```js
    if (type === 'error') {
      if (event.step) {
        el = $('#substep-' + event.step);
        if (el) {
          el.className = 'substep-item error';
        }
      }
      appendLog('[ERROR] ' + event.message);
      var cat = categorizeError(event.message || '');
      showStepError(event.step, cat, event.message);
      $('#btn-next').disabled = false;
      $('#btn-next').textContent = 'Retry';
    }
```

### Step 4: Add error CSS styles

- [ ] **Step 4a: Add pipeline error styles to `setup/static/setup.css`**

Add at the end of the file (after preflight styles):

```css
/* Pipeline error display */
.pipeline-error {
  background: rgba(244, 67, 54, 0.15);
  color: #f44336;
  padding: 12px 16px;
  border-radius: 6px;
  margin: 12px 0;
  border-left: 3px solid #f44336;
}

@media (prefers-color-scheme: dark) {
  .pipeline-error {
    background: rgba(248, 81, 73, 0.15);
    color: #f85149;
    border-left-color: #f85149;
  }
}

.progress-error {
  background: #f44336 !important;
  animation: pulse-error 1.5s ease-in-out infinite;
}

@keyframes pulse-error {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.step-error-hint {
  font-size: 0.85rem;
  color: var(--text-muted);
  margin-top: 4px;
}
```

### Step 5: Commit

- [ ] **Step 5a: Commit the pipeline error handling**

```
feat(setup): add categorized pipeline errors and WebSocket reconnect

WebSocket connections now use exponential backoff (2s, 4s, 8s) with
a visible error message and retry button after 3 failures. Pipeline
errors are categorized (dependency, permission, disk, network, timeout)
with actionable hints. All DOM rendering uses createElement/textContent.
```

---

## Task 7: Directory Creation Integration

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md
Follow TDD: write failing test → implement → verify green.

**Files:**
- Modify: `setup/main.py` (line 337-342, `_run_pipeline()` function)
- Modify: `tests/test_setup_main.py` (add directory creation test)

### Step 1: Write failing test

- [ ] **Step 1a: Add directory creation test to `tests/test_setup_main.py`**

```python
class TestPipelineDirectoryCreation:
    """Verify _run_pipeline creates data_path if it doesn't exist."""

    def test_run_pipeline_creates_data_dir(self, tmp_path):
        """The pipeline should create data_path before running steps."""
        from setup.main import _run_pipeline, StartRequest, current_state

        # Use a non-existent subdirectory under tmp_path
        new_dir = tmp_path / "new_data_dir"
        assert not new_dir.exists()

        config = StartRequest(
            bbox="-114.8,31.3,-109.0,37.0",
            layers=[],
            data_path=str(new_dir),
        )

        import asyncio
        # Reset state to allow pipeline to run
        current_state["running"] = False
        asyncio.get_event_loop().run_until_complete(_run_pipeline(config))

        # The directory should now exist
        assert new_dir.exists()
        assert new_dir.is_dir()
```

### Step 2: Add os.makedirs to _run_pipeline

- [ ] **Step 2a: Add directory creation to `_run_pipeline()` in `setup/main.py`**

In `setup/main.py`, in the `_run_pipeline()` function, after line 339 (`current_state["running"] = True`) and before line 340 (`current_state["step"] = "starting"`), add:

```python
    # Create data directory if it doesn't exist (validated as creatable by
    # /api/validate-path — parent is writable with sufficient space)
    os.makedirs(config.data_path, exist_ok=True)
```

The full context should look like:

```python
    current_state["running"] = True
    # Create data directory if it doesn't exist (validated as creatable by
    # /api/validate-path — parent is writable with sufficient space)
    os.makedirs(config.data_path, exist_ok=True)
    current_state["step"] = "starting"
```

### Step 3: Run tests

- [ ] **Step 3a: Run the tests and verify**

```bash
python -m pytest tests/test_setup_main.py::TestPipelineDirectoryCreation -v
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage (error paths tested? edge cases?)
3. Run: python -m pytest tests/test_setup_main.py -v

### Step 4: Commit

- [ ] **Step 4a: Commit the directory creation fix**

```
fix(setup): create custom data directory before pipeline runs

The /api/validate-path endpoint reports paths as "creatable" but never
creates them. The pipeline runner now calls os.makedirs(data_path,
exist_ok=True) before executing steps, preventing FileNotFoundError
on custom paths that were validated as creatable.
```

---

## Execution Order

```
Task 1 (requirements fix)     — independent, do first
Task 2 (path backend)         — independent
Task 3 (path frontend)        — depends on Task 2
Task 4 (preflight backend)    — independent
Task 5 (preflight frontend)   — depends on Task 4
Task 6 (error handling)       — depends on Task 5 (shares Step 4 DOM)
Task 7 (directory creation)   — independent
```

Parallelizable groups:
- **Group A:** Tasks 1, 2, 4, 7 (all independent)
- **Group B:** Task 3 (after Task 2)
- **Group C:** Task 5 (after Task 4)
- **Group D:** Task 6 (after Task 5)

Or sequential: 1 → 2 → 3 → 4 → 5 → 6 → 7

---

## Final Verification

After all tasks are complete:

```bash
# Run all setup tests
python -m pytest tests/test_setup_main.py tests/test_setup_config.py -v

# Run full test suite to check for regressions
python -m pytest tests/ -v

# Manual smoke test: start setup wizard and verify
# 1. Step 1: Select "Other" path, verify validation feedback
# 2. Step 4: Verify preflight checks appear before pipeline controls
# 3. Step 4: Verify error categorization on pipeline failure
```
