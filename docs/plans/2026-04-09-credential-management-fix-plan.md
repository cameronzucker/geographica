# Credential Management Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 bugs in credential CRUD: type-specific DELETE endpoints, asyncio lock, robust error handling, hardened M2M pipeline check.

**Architecture:** Add type-specific DELETE routes that read-modify-write credentials.json under an asyncio lock. Fix frontend handlers to check r.ok, use formatApiError for all error shapes, and only call fetchAll on success.

**Tech Stack:** FastAPI, Pydantic, vanilla JS

**Spec:** `docs/superpowers/specs/2026-04-09-credential-management-fix-design.md`

---

## File Structure

### Modified files
| File | Changes |
|------|---------|
| `services/search/main.py` | Add asyncio lock, type-specific DELETE endpoints, harden M2M check, sanitize error messages |
| `frontend/config/index.html` | Fix M2M delete URL, add formatApiError, add r.ok checks + error handling to all 4 handlers |

---

### Task 1: Backend — Type-specific DELETE + asyncio lock + hardened checks

BEFORE starting work:
1. Read docs/pitfalls/testing-pitfalls.md
2. Read docs/pitfalls/implementation-pitfalls.md — NOTE Pitfall #10: Config panel is localhost-only.

**Files:**
- Modify: `services/search/main.py:840-913` (credential endpoints), `:1040-1043` (M2M check)

- [ ] **Step 1: Add asyncio lock and shared helper**

Read `services/search/main.py`. Near the top of the credential management section (around line 842), add:

```python
_credential_lock = asyncio.Lock()
```

Then add the shared helper function before the existing endpoints:

```python
async def _remove_credential_keys(keys_to_remove: list[str]) -> dict:
    """Remove specific credential keys from credentials.json.

    Returns {"status": "deleted"}. Idempotent — succeeds even if file
    or keys don't exist. Preserves remaining credentials.
    """
    async with _credential_lock:
        existing = {}
        if CREDENTIALS_PATH.exists():
            try:
                existing = json.loads(CREDENTIALS_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        for key in keys_to_remove:
            existing.pop(key, None)

        # Check if any known credential keys remain
        known_keys = {"m2m_username", "m2m_token", "copernicus_username", "copernicus_password"}
        has_creds = any(k in existing for k in known_keys)

        if has_creds:
            cred_data = json.dumps(existing)
            fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
            try:
                os.write(fd, cred_data.encode())
            finally:
                os.close(fd)
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            os.replace(tmp_path, str(CREDENTIALS_PATH))
        else:
            # No credentials remain — delete the file
            CREDENTIALS_PATH.unlink(missing_ok=True)

    return {"status": "deleted"}
```

- [ ] **Step 2: Wrap existing save_credentials with the lock**

In the `save_credentials` function (line 845), wrap the body with `async with _credential_lock:`. The function should look like:

```python
@app.post("/admin/credentials", dependencies=[Depends(require_config_source)])
async def save_credentials(body: CredentialBody):
    """Store API credentials securely. Supports M2M and/or Copernicus credentials."""
    has_m2m = body.m2m_username.strip() and body.m2m_token.strip()
    has_copernicus = body.copernicus_username.strip() and body.copernicus_password.strip()

    if not has_m2m and not has_copernicus:
        raise HTTPException(status_code=422, detail="Provide m2m_username+m2m_token and/or copernicus_username+copernicus_password")

    async with _credential_lock:
        existing = {}
        if CREDENTIALS_PATH.exists():
            try:
                existing = json.loads(CREDENTIALS_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        if has_m2m:
            existing["m2m_username"] = body.m2m_username
            existing["m2m_token"] = body.m2m_token
        if has_copernicus:
            existing["copernicus_username"] = body.copernicus_username
            existing["copernicus_password"] = body.copernicus_password

        cred_data = json.dumps(existing)

        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
            try:
                os.write(fd, cred_data.encode())
            finally:
                os.close(fd)
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            os.replace(tmp_path, str(CREDENTIALS_PATH))
        except Exception as e:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            log.error("Failed to save credentials: %s", e)
            raise HTTPException(status_code=500, detail="Failed to save credentials. Check server logs.")

    return {"status": "saved"}
```

Note: the error detail no longer includes the raw exception (F6 fix).

- [ ] **Step 3: Add type-specific DELETE endpoints**

After the existing `delete_credentials` function, add two new endpoints:

```python
@app.delete("/admin/credentials/m2m", dependencies=[Depends(require_config_source)])
async def delete_m2m_credentials():
    """Remove only M2M credentials, preserving Copernicus."""
    try:
        return await _remove_credential_keys(["m2m_username", "m2m_token"])
    except Exception as e:
        log.error("Failed to delete M2M credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete credentials. Check server logs.")


@app.delete("/admin/credentials/copernicus", dependencies=[Depends(require_config_source)])
async def delete_copernicus_credentials():
    """Remove only Copernicus credentials, preserving M2M."""
    try:
        return await _remove_credential_keys(["copernicus_username", "copernicus_password"])
    except Exception as e:
        log.error("Failed to delete Copernicus credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete credentials. Check server logs.")
```

- [ ] **Step 4: Sanitize existing generic DELETE error message**

In the existing `delete_credentials` function (line 906-913), change:
```python
        raise HTTPException(status_code=500, detail=f"Failed to delete credentials: {e}")
```
To:
```python
        log.error("Failed to delete credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete credentials. Check server logs.")
```

- [ ] **Step 5: Harden M2M credential check in pipeline_start**

At line 1040-1043, replace:
```python
    if body.mode == "m2m":
        if not CREDENTIALS_PATH.exists():
            raise HTTPException(status_code=422, detail="M2M credentials not configured. POST to /admin/credentials first.")
```
With:
```python
    if body.mode == "m2m":
        if not CREDENTIALS_PATH.exists():
            raise HTTPException(status_code=422, detail="M2M credentials not configured. POST to /admin/credentials first.")
        try:
            creds = json.loads(CREDENTIALS_PATH.read_text())
            if not creds.get("m2m_username") or not creds.get("m2m_token"):
                raise HTTPException(status_code=422, detail="M2M credentials not configured. POST to /admin/credentials first.")
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="Credentials file is corrupted.")
```

- [ ] **Step 6: Run tests**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/ -v`
Expected: All 286 tests PASS (no new tests needed — these are endpoint changes tested via manual/integration)

- [ ] **Step 7: Quick manual verification**

```bash
# Save Copernicus creds
curl -s -X POST http://localhost:8096/admin/credentials \
  -H "Content-Type: application/json" -H "X-Config-Source: internal" -H "X-Geographica: 1" \
  -d '{"copernicus_username": "test@test.com", "copernicus_password": "testpass"}'
# Expected: {"status":"saved"}

# Check status
curl -s http://localhost:8096/admin/credentials/status
# Expected: {"m2m_configured":false,"copernicus_configured":true}

# Delete only Copernicus
curl -s -X DELETE http://localhost:8096/admin/credentials/copernicus \
  -H "X-Config-Source: internal" -H "X-Geographica: 1"
# Expected: {"status":"deleted"}

# Check status again
curl -s http://localhost:8096/admin/credentials/status
# Expected: {"m2m_configured":false,"copernicus_configured":false}

# Delete when no file exists (idempotent)
curl -s -X DELETE http://localhost:8096/admin/credentials/m2m \
  -H "X-Config-Source: internal" -H "X-Geographica: 1"
# Expected: {"status":"deleted"}
```

- [ ] **Step 8: Commit**

```bash
git add services/search/main.py
git commit -m "fix: type-specific credential DELETE + asyncio lock + hardened checks

Add DELETE /admin/credentials/m2m and /copernicus for independent
deletion. Asyncio lock prevents read-modify-write races. Harden M2M
pipeline check from file-existence to key-presence. Sanitize error
messages to not leak file paths."
```

BEFORE marking this task complete:
1. Verify _remove_credential_keys uses chmod 0600
2. Verify M2M pipeline check now validates key presence
3. Verify error messages don't contain raw exceptions
4. Run tests and confirm green

---

### Task 2: Frontend — Error handling + formatApiError + delete URL fix

BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md — NOTE Pitfall #10: Config panel is localhost-only.

**Files:**
- Modify: `frontend/config/index.html:1413-1493` (credential handlers)

- [ ] **Step 1: Add formatApiError helper**

Near the top of the script section in `config/index.html` (after the `cfgFetch` function), add:

```js
    function formatApiError(detail) {
        if (!detail) return 'Unknown error';
        if (typeof detail === 'string') return detail;
        if (Array.isArray(detail)) return detail.map(function(e) { return e.msg || JSON.stringify(e); }).join('; ');
        if (typeof detail === 'object') return detail.msg || JSON.stringify(detail);
        return String(detail);
    }
```

- [ ] **Step 2: Fix M2M save handler (lines 1416-1441)**

Replace the entire M2M save handler:

```js
    document.getElementById('m2m-save-btn').addEventListener('click', function() {
        var statusMsg = document.getElementById('m2m-status-msg');
        cfgFetch('/admin/credentials', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                m2m_username: document.getElementById('cfg-m2m-user').value,
                m2m_token: document.getElementById('cfg-m2m-token').value
            })
        }).then(function(r) {
            if (!r.ok) return r.text().then(function(text) {
                try { var d = JSON.parse(text); throw new Error(formatApiError(d.detail)); }
                catch(e) { if (e instanceof SyntaxError) throw new Error('Server error: ' + r.status); throw e; }
            });
            return r.json();
        }).then(function(d) {
            statusMsg.textContent = 'Credentials saved';
            statusMsg.style.color = '#a6e3a1';
            document.getElementById('cfg-m2m-user').value = '';
            document.getElementById('cfg-m2m-token').value = '';
            fetchAll();
        }).catch(function(err) {
            statusMsg.textContent = 'Error: ' + err.message;
            statusMsg.style.color = '#f38ba8';
        });
    });
```

- [ ] **Step 3: Fix M2M delete handler (lines 1443-1447)**

Replace with:

```js
    document.getElementById('m2m-delete-btn').addEventListener('click', function() {
        if (!confirm('Delete M2M credentials?')) return;
        var statusMsg = document.getElementById('m2m-status-msg');
        cfgFetch('/admin/credentials/m2m', {method: 'DELETE'}).then(function(r) {
            if (!r.ok) return r.text().then(function(text) {
                try { var d = JSON.parse(text); throw new Error(formatApiError(d.detail)); }
                catch(e) { if (e instanceof SyntaxError) throw new Error('Server error: ' + r.status); throw e; }
            });
            return r.json();
        }).then(function() {
            statusMsg.textContent = 'Credentials deleted';
            statusMsg.style.color = '#a6e3a1';
            fetchAll();
        }).catch(function(err) {
            statusMsg.textContent = 'Error: ' + err.message;
            statusMsg.style.color = '#f38ba8';
        });
    });
```

- [ ] **Step 4: Fix Copernicus save handler (lines 1457-1482)**

Replace with the same pattern as M2M save but with Copernicus fields:

```js
    document.getElementById('copernicus-save-btn').addEventListener('click', function() {
        var statusMsg = document.getElementById('copernicus-status-msg');
        cfgFetch('/admin/credentials', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                copernicus_username: document.getElementById('cfg-copernicus-user').value,
                copernicus_password: document.getElementById('cfg-copernicus-pass').value
            })
        }).then(function(r) {
            if (!r.ok) return r.text().then(function(text) {
                try { var d = JSON.parse(text); throw new Error(formatApiError(d.detail)); }
                catch(e) { if (e instanceof SyntaxError) throw new Error('Server error: ' + r.status); throw e; }
            });
            return r.json();
        }).then(function(d) {
            statusMsg.textContent = 'Credentials saved';
            statusMsg.style.color = '#a6e3a1';
            document.getElementById('cfg-copernicus-user').value = '';
            document.getElementById('cfg-copernicus-pass').value = '';
            fetchAll();
        }).catch(function(err) {
            statusMsg.textContent = 'Error: ' + err.message;
            statusMsg.style.color = '#f38ba8';
        });
    });
```

- [ ] **Step 5: Fix Copernicus delete handler (lines 1484-1488)**

Replace with:

```js
    document.getElementById('copernicus-delete-btn').addEventListener('click', function() {
        if (!confirm('Delete Copernicus credentials?')) return;
        var statusMsg = document.getElementById('copernicus-status-msg');
        cfgFetch('/admin/credentials/copernicus', {method: 'DELETE'}).then(function(r) {
            if (!r.ok) return r.text().then(function(text) {
                try { var d = JSON.parse(text); throw new Error(formatApiError(d.detail)); }
                catch(e) { if (e instanceof SyntaxError) throw new Error('Server error: ' + r.status); throw e; }
            });
            return r.json();
        }).then(function() {
            statusMsg.textContent = 'Credentials deleted';
            statusMsg.style.color = '#a6e3a1';
            fetchAll();
        }).catch(function(err) {
            statusMsg.textContent = 'Error: ' + err.message;
            statusMsg.style.color = '#f38ba8';
        });
    });
```

- [ ] **Step 6: Commit**

```bash
git add frontend/config/index.html
git commit -m "fix: robust credential error handling + type-specific delete URLs

Add formatApiError for all error shapes (string, array, object, non-JSON).
Add r.ok checks to all 4 handlers. M2M delete now calls /credentials/m2m.
fetchAll only on success. Status messages for delete success/failure."
```

BEFORE marking this task complete:
1. M2M delete calls /admin/credentials/m2m (not generic /admin/credentials)
2. Copernicus delete calls /admin/credentials/copernicus
3. All 4 handlers have r.ok check + .catch() + status message
4. formatApiError handles string, array, object, and fallback

---

After both tasks, review:

After every logical group of tasks:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

## Execution Recommendation

**Recommended: Subagent-Driven (Option 1)**

Only 2 sequential tasks (they modify different files, could run in parallel). Quick fix — 15-20 minutes total. Subagent per task keeps context clean and the review gates catch any issues.
