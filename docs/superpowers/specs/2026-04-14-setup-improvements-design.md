# Setup Wizard Improvements — Design Spec

**Date:** 2026-04-14
**Scope:** 3 issues from beta testing: custom storage path, missing WebSocket dependency, pipeline error handling
**Files:** `setup/main.py`, `setup/config.py`, `setup/static/setup.js`, `setup/static/index.html`, `setup/static/setup.css`, `setup/requirements.txt`
**Source:** `docs/bugs_and_changes_20260414.md` (Setup section)

---

## Summary

A beta tester attempted setup and hit three blockers: no way to specify a custom storage path, a missing WebSocket dependency that caused a silent 404 on the progress endpoint, and no error feedback when the pipeline failed. The fixes add a custom path input with validation, a pre-flight dependency checker, and categorized error handling.

---

## Feature 1: Custom Storage Path

### Problem

The current dropdown (`#data-path`) shows auto-detected mount points from `/proc/mounts`. Users who want a custom path (e.g., a subdirectory on an external drive) have no way to enter one.

### Implementation

1. **`setup/static/index.html`** — Add an "Other" option to the `#data-path` dropdown and a hidden text input below it:
   ```html
   <!-- Inside the data-path select, after auto-populated options -->
   <option value="__other__">Other (enter path manually)</option>

   <!-- Below the select -->
   <div id="custom-path-group" class="hidden">
     <input type="text" id="custom-path-input" placeholder="/mnt/ssd/geographica/data"
            autocomplete="off" spellcheck="false">
     <div id="custom-path-feedback"></div>
   </div>
   ```

2. **`setup/static/setup.js`** — Handle the "Other" selection:
   ```js
   // In Step 1 initialization
   var dataPathSelect = document.getElementById('data-path');
   var customPathGroup = document.getElementById('custom-path-group');
   var customPathInput = document.getElementById('custom-path-input');
   var customPathFeedback = document.getElementById('custom-path-feedback');
   var customPathTimer = null;

   dataPathSelect.addEventListener('change', function () {
     if (this.value === '__other__') {
       customPathGroup.classList.remove('hidden');
       customPathInput.focus();
     } else {
       customPathGroup.classList.add('hidden');
     }
   });

   // Validate on input with 500ms debounce
   customPathInput.addEventListener('input', function () {
     clearTimeout(customPathTimer);
     customPathTimer = setTimeout(validateCustomPath, 500);
   });

   function validateCustomPath() {
     var path = customPathInput.value.trim();
     if (!path) {
       setPathFeedback('', 'neutral');
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
         setPathFeedback('Valid — ' + result.free_gb.toFixed(0) + ' GB free', 'success');
       } else if (result.creatable) {
         setPathFeedback('Will be created — ' + result.free_gb.toFixed(0) + ' GB free on parent', 'warning');
       } else {
         setPathFeedback(result.message, 'error');
       }
     })
     .catch(function () {
       setPathFeedback('Validation failed', 'error');
     });
   }

   function setPathFeedback(msg, level) {
     customPathFeedback.textContent = msg;
     customPathFeedback.className = 'path-feedback path-' + level;
     customPathInput.className = level === 'error' ? 'input-error' :
                                 level === 'warning' ? 'input-warning' :
                                 level === 'success' ? 'input-success' : '';
   }
   ```

   When collecting config for submission, read the effective path:
   ```js
   var dataPath = dataPathSelect.value === '__other__'
     ? customPathInput.value.trim()
     : dataPathSelect.value;
   ```

   Block "Next" if the custom path is in an error state.

3. **`setup/main.py`** — Add the validation endpoint:
   ```python
   class ValidatePathRequest(BaseModel):
       path: str

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

4. **`setup/static/setup.css`** — Validation feedback styles:
   ```css
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
   ```

---

## Feature 2: Pre-Flight Dependency Check

### Problem

The setup wizard's `setup/requirements.txt` specifies `uvicorn>=0.32.0` without the `[standard]` extra, which provides WebSocket support. This caused a 404 on `/ws/progress` with an unhelpful error. LXD testing didn't catch it because the test container may have had `websockets` installed as a transitive dependency. The real fix is proactive dependency checking at wizard startup.

### Immediate Fix

**`setup/requirements.txt`** — Change:
```
uvicorn>=0.32.0
```
To:
```
uvicorn[standard]>=0.32.0
```

### Requirements Audit

Audit all `requirements.txt` files for consistency. Current state:

| File | uvicorn spec | Issue |
|------|-------------|-------|
| `setup/requirements.txt` | `uvicorn>=0.32.0` | **Missing `[standard]`** |
| `services/gps/requirements.txt` | `uvicorn[standard]==0.34.2` | OK |
| `services/search/requirements.txt` | `uvicorn[standard]>=0.29,<1` | OK |
| `services/stt/requirements.txt` | `uvicorn[standard]>=0.29,<1` | OK |

Also audit `scripts/requirements.txt` — the pipeline scripts' own dependency file. This is the primary consumer of `aiohttp`, `aiosqlite`, `tqdm`, `shapely`.

Check all other shared dependencies (fastapi, httpx, pydantic) for version range consistency across all requirement files. Fix any discrepancies found.

### Pre-Flight Check Implementation

1. **`setup/main.py`** — Add the preflight endpoint:
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

       # Docker daemon running (timeout=5 to avoid hanging if daemon is starting)
       docker_info = subprocess.run(["docker", "info"],
                                     capture_output=True, text=True, timeout=5)
       if docker_info.returncode == 0:
           checks.append({"category": "system", "name": "Docker daemon",
                         "status": "running", "severity": "ok"})
       else:
           checks.append({"category": "system", "name": "Docker daemon",
                         "status": "not running",
                         "fix": "sudo systemctl start docker", "severity": "error"})

       passed = all(c["severity"] != "error" for c in checks)
       return {"passed": passed, "checks": checks}
   ```

2. **`setup/main.py`** — Add the fix endpoint. **SECURITY: Use a server-side command registry — never pass user-supplied strings to subprocess.** The frontend sends a `fix_id` (e.g., `"httpx"`), the backend maps it to a pre-tokenized command list:
   ```python
   # Server-side command registry — the ONLY commands that can be executed
   FIX_REGISTRY = {
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

   class FixRequest(BaseModel):
       fix_id: str

   @app.post("/api/fix-dependency")
   async def fix_dependency(req: FixRequest):
       if req.fix_id not in FIX_REGISTRY:
           raise HTTPException(400, f"Unknown fix: {req.fix_id}")

       cmd = FIX_REGISTRY[req.fix_id]
       result = subprocess.run(
           cmd, capture_output=True, text=True, timeout=120
       )
       return {"success": result.returncode == 0,
               "output": result.stdout, "error": result.stderr}
   ```

   **Do NOT:**
   - Use `shell=True` — command injection risk
   - Accept freeform command strings from the client
   - Add entries to `FIX_REGISTRY` without reviewing what they execute

3. **`setup/static/setup.js`** — When entering Step 4, run preflight before showing pipeline controls:
   ```js
   function enterStep4() {
     showPreflightChecks();
     fetch('/api/preflight')
       .then(function (res) { return res.json(); })
       .then(function (result) {
         renderPreflightResults(result);
         if (result.passed) {
           enablePipelineControls();
         }
       });
   }

   function renderPreflightResults(result) {
     var container = document.getElementById('preflight-checks');
     // Clear using safe DOM method
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
               fixBtn.textContent = 'Failed — Retry';
               fixBtn.disabled = false;
             }
           });
         });
         row.appendChild(fixBtn);
       }

       container.appendChild(row);
     });
   }
   ```

4. **`setup/static/index.html`** — Add preflight container to Step 4, before the pipeline controls:
   ```html
   <div id="preflight-section">
     <h3>Pre-flight Checks</h3>
     <div id="preflight-checks">
       <p class="muted">Checking dependencies...</p>
     </div>
   </div>
   ```

5. **`setup/static/setup.css`** — Preflight styles:
   ```css
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
   .btn-fix {
     padding: 2px 12px;
     font-size: 0.8rem;
     border-radius: 3px;
     cursor: pointer;
   }
   ```

---

## Feature 3: Generic Pipeline Error Handling

### Problem

When the WebSocket connection to `/ws/progress` fails, the progress bar sits at 0% with no user feedback. Errors dump to the browser console only.

### Implementation

1. **WebSocket connection errors — `setup/static/setup.js`:**

   Replace the current reconnect logic (lines 580-587) with exponential backoff and user feedback:
   ```js
   var wsRetries = 0;
   var MAX_WS_RETRIES = 3;

   function connectProgress() {
     var ws = new WebSocket(wsUrl);

     ws.onopen = function () {
       wsRetries = 0;  // reset on successful connection
       hideConnectionError();
     };

     ws.onmessage = function (evt) {
       var event = JSON.parse(evt.data);
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
     var errorEl = document.getElementById('pipeline-error');
     errorEl.textContent = msg;
     errorEl.classList.remove('hidden');

     var retryBtn = document.getElementById('pipeline-retry-btn');
     retryBtn.classList.remove('hidden');
     retryBtn.onclick = function () {
       wsRetries = 0;
       errorEl.classList.add('hidden');
       retryBtn.classList.add('hidden');
       connectProgress();
     };

     // Switch progress bar to error state
     var progressBar = document.getElementById('progress-bar');
     if (progressBar) progressBar.classList.add('progress-error');
   }

   function hideConnectionError() {
     var errorEl = document.getElementById('pipeline-error');
     if (errorEl) errorEl.classList.add('hidden');
     var progressBar = document.getElementById('progress-bar');
     if (progressBar) progressBar.classList.remove('progress-error');
   }
   ```

2. **Pipeline step error categorization — `setup/static/setup.js`:**

   In the `handleProgressEvent` function, enhance the `error` event type handling:
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
   ```

   When an error event arrives:
   ```js
   case 'error':
     var cat = categorizeError(event.message || '');
     showStepError(event.step, cat, event.message);
     break;
   ```

   `showStepError` renders the categorized error with message, hint, and retry button using safe DOM construction (createElement/textContent, no innerHTML).

3. **`setup/static/index.html`** — Add error display elements to Step 4:
   ```html
   <div id="pipeline-error" class="pipeline-error hidden"></div>
   <button id="pipeline-retry-btn" class="hidden">Retry Connection</button>
   ```

4. **`setup/static/setup.css`** — Error state styles:
   ```css
   .pipeline-error {
     background: rgba(244, 67, 54, 0.15);
     color: #f44336;
     padding: 12px 16px;
     border-radius: 6px;
     margin: 12px 0;
     border-left: 3px solid #f44336;
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
     color: #aaa;
     margin-top: 4px;
   }
   ```

5. **`setup/main.py`** — Pipeline error events already send raw error messages. The frontend handles categorization — the backend sends the raw error message. This keeps the categorization logic in one place (frontend) rather than duplicating it.

---

## Execution Dependencies

The three features are independent within this spec:

1. **Custom storage path** — touches `index.html` (Step 1 section), `setup.js` (Step 1 handler), `main.py` (new endpoint), `setup.css`
2. **Pre-flight dependency check** — touches `index.html` (Step 4 section), `setup.js` (Step 4 handler), `main.py` (new endpoints), `setup.css`, `requirements.txt`
3. **Error handling** — touches `setup.js` (WebSocket handler, Step 4 handler), `index.html` (Step 4 section), `setup.css`

Features 2 and 3 both modify Step 4 in `index.html` and `setup.js`, so they should be in the same task or explicitly sequenced (preflight first, then error handling, since preflight adds DOM elements to Step 4 that error handling should be aware of).

---

## Critical Integration: Directory Creation

The `/api/validate-path` endpoint reports paths as "creatable" but never creates them. The pipeline runner (`main.py:_run_pipeline`) assumes `data_path` exists — it will crash with `FileNotFoundError` on a custom path that was validated as "creatable" but never created.

**Fix in `main.py`:** In `_run_pipeline()`, before any pipeline step executes, add:
```python
os.makedirs(config.data_path, exist_ok=True)
```

This is safe because `validate-path` already confirmed the parent is writable and has sufficient space.
