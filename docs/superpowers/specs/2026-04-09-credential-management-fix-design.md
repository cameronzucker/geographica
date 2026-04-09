# Credential Management Fix Design

**Date:** 2026-04-09
**Status:** Approved
**Scope:** Fix 8 bugs in credential CRUD: type-specific DELETE endpoints, error handling, UI consistency

## Problem

The credential management system was built for M2M credentials only, then Copernicus credentials were bolted on. The result is 8 bugs:

| # | Bug | Severity |
|---|-----|----------|
| 1 | Copernicus delete calls `/admin/credentials/copernicus` — route doesn't exist (404) | HIGH |
| 2 | M2M delete calls `/admin/credentials` which `unlink()`s entire file — destroys Copernicus creds | HIGH |
| 3 | No error handling in delete handlers — no `.catch()`, no status message | MEDIUM |
| 4 | No status message display for delete errors | MEDIUM |
| 5 | M2M delete uses generic endpoint instead of type-specific | HIGH |
| 6 | Error `detail` may be Pydantic array, rendered as `[object Object]` | MEDIUM |
| 7 | No HTTP status code checking (`r.ok`) in fetch responses | MEDIUM |
| 8 | UI state not restored after failed delete — `fetchAll()` called regardless | HIGH |

## Solution

Type-specific DELETE endpoints + robust frontend error handling.

### Backend changes (`services/search/main.py`)

#### New endpoint: `DELETE /admin/credentials/m2m`

Reads `credentials.json`, removes `m2m_username` and `m2m_token` keys, writes back. If no credential keys remain after removal, deletes the file entirely.

```python
@app.delete("/admin/credentials/m2m", dependencies=[Depends(require_config_source)])
async def delete_m2m_credentials():
    """Remove only M2M credentials, preserving Copernicus."""
    # Read existing, remove m2m keys, write back or delete if empty
```

Returns `{"status": "deleted"}` on success.

#### New endpoint: `DELETE /admin/credentials/copernicus`

Same pattern — removes `copernicus_username` and `copernicus_password` keys, preserves M2M.

```python
@app.delete("/admin/credentials/copernicus", dependencies=[Depends(require_config_source)])
async def delete_copernicus_credentials():
    """Remove only Copernicus credentials, preserving M2M."""
```

Returns `{"status": "deleted"}` on success.

#### Existing `DELETE /admin/credentials` — kept as "delete all"

Unchanged behavior (deletes entire file). Not called by the UI but available as an API for clearing everything.

#### Shared helper: `_remove_credential_keys(keys_to_remove)`

Both type-specific DELETE endpoints share this logic:
1. Read credentials.json
2. Remove specified keys
3. If remaining dict has any of the 4 known credential keys (`m2m_username`, `m2m_token`, `copernicus_username`, `copernicus_password`), write back atomically
4. If none of those 4 keys remain, delete the file
5. Return `{"status": "deleted"}`

Atomic write uses the same tmp + `os.replace()` pattern as the save endpoint.

### Frontend changes (`frontend/config/index.html`)

#### Fix M2M delete button

Change from:
```js
cfgFetch('/admin/credentials', {method: 'DELETE'})
```
To:
```js
cfgFetch('/admin/credentials/m2m', {method: 'DELETE'})
```

#### Error display helper

Add a utility function that normalizes error responses:
```js
function formatApiError(detail) {
    if (Array.isArray(detail)) {
        return detail.map(function(e) { return e.msg || JSON.stringify(e); }).join('; ');
    }
    return String(detail || 'Unknown error');
}
```

#### Fix both delete handlers (M2M + Copernicus)

Replace fire-and-forget pattern with proper error handling:
```js
cfgFetch('/admin/credentials/m2m', {method: 'DELETE'})
    .then(function(r) {
        if (!r.ok) return r.json().then(function(d) { throw new Error(formatApiError(d.detail)); });
        return r.json();
    })
    .then(function(d) {
        statusMsg.textContent = 'Credentials deleted';
        statusMsg.style.color = '#a6e3a1';
        fetchAll();
    })
    .catch(function(err) {
        statusMsg.textContent = 'Error: ' + err.message;
        statusMsg.style.color = '#f38ba8';
    });
```

Same pattern for Copernicus delete.

#### Fix both save handlers (M2M + Copernicus)

Add `r.ok` check before parsing success response:
```js
.then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(formatApiError(d.detail)); });
    return r.json();
})
```

Replace inline error formatting with `formatApiError()`.

#### Key principle: `fetchAll()` only on success

All handlers must follow: success path calls `fetchAll()` to refresh UI, error path displays message but does NOT call `fetchAll()` (preserves current UI state).

## Adversarial review fixes

The following issues were identified by 5 adversarial reviewers (Haiku, 2x Opus, Codex/GPT-5.4, UX specialist) and must be addressed in implementation:

### F1 (CRITICAL): File permissions in `_remove_credential_keys`

The helper must call `os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)` (0600) on the temp file BEFORE `os.replace()`. Otherwise the temp file inherits default umask (typically 0644), making credentials world-readable after a type-specific delete.

### F2 (HIGH): Harden M2M credential check in `pipeline_start`

The existing M2M credential check at `pipeline_start()` only checks `CREDENTIALS_PATH.exists()`. After a type-specific delete (which may leave the file with only Copernicus keys), this check passes but the pipeline fails mid-run with missing M2M keys. Fix: change to check for key presence in the file, matching the Sentinel pattern:

```python
if body.mode == "m2m":
    if not CREDENTIALS_PATH.exists():
        raise HTTPException(status_code=422, detail="M2M credentials not configured.")
    try:
        creds = json.loads(CREDENTIALS_PATH.read_text())
        if "m2m_username" not in creds or "m2m_token" not in creds:
            raise HTTPException(status_code=422, detail="M2M credentials not configured.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Credentials file is corrupted.")
```

### F3 (MEDIUM): Handle missing file in `_remove_credential_keys`

If `credentials.json` doesn't exist when a DELETE is called, the helper must return `{"status": "deleted"}` (idempotent) rather than raising `FileNotFoundError`.

### F4 (MEDIUM): Serialize credential file access with asyncio lock

Add `_credential_lock = asyncio.Lock()` and use it in both save and delete handlers to prevent read-modify-write races. Single-user Pi deployment makes this unlikely but correctness matters:

```python
_credential_lock = asyncio.Lock()

async def save_credentials(body):
    async with _credential_lock:
        # read, modify, write
```

### F5 (MEDIUM): Robust `formatApiError` for all error shapes

Handle object-shaped `detail`, non-JSON responses, and missing `detail` field:

```js
function formatApiError(detail) {
    if (!detail) return 'Unknown error';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map(function(e) { return e.msg || JSON.stringify(e); }).join('; ');
    if (typeof detail === 'object') return detail.msg || JSON.stringify(detail);
    return String(detail);
}
```

Also: wrap the `r.json()` call in the error path with a try/catch for non-JSON responses (e.g., NGINX 502 HTML pages):

```js
.then(function(r) {
    if (!r.ok) {
        return r.text().then(function(text) {
            try { var d = JSON.parse(text); throw new Error(formatApiError(d.detail)); }
            catch(e) { if (e instanceof SyntaxError) throw new Error('Server error: ' + r.status); throw e; }
        });
    }
    return r.json();
})
```

### F6 (MEDIUM): Sanitize error messages — no raw Python exceptions

Replace raw `f"Failed to save credentials: {e}"` and `f"Failed to delete credentials: {e}"` with generic messages that don't leak file paths or exception details:

```python
raise HTTPException(status_code=500, detail="Failed to save credentials. Check server logs.")
```

Log the actual exception server-side with `log.error(...)`.

## Files modified

| File | Changes |
|------|---------|
| `services/search/main.py` | Add `DELETE /admin/credentials/m2m` and `DELETE /admin/credentials/copernicus` endpoints, add `_remove_credential_keys()` helper |
| `frontend/config/index.html` | Fix M2M delete URL, add `formatApiError()` helper, add error handling to all 4 credential handlers (2 save + 2 delete), add `r.ok` checks |

## Testing

### Backend tests
- `DELETE /admin/credentials/m2m` with both credential types present — only M2M removed, Copernicus preserved
- `DELETE /admin/credentials/copernicus` with both present — only Copernicus removed, M2M preserved
- `DELETE /admin/credentials/m2m` with only M2M present — file deleted entirely
- `DELETE /admin/credentials/copernicus` when Copernicus not configured — returns success (idempotent)
- `DELETE /admin/credentials` — still deletes everything (backward compat)

### Frontend manual tests
- Save M2M creds, save Copernicus creds, delete only Copernicus — M2M still shows as configured
- Save both, delete only M2M — Copernicus still shows as configured
- Try to save with empty fields — error displayed cleanly (not `[object Object]`)
- Delete with server down — error message shown, UI state unchanged
