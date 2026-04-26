# Testing Pitfalls

Common testing mistakes in the Geographica codebase.

## 1. Mocking what should be tested

Don't mock SQLite queries when the test is about query correctness. Use an in-memory SQLite database with real schema and data. Mocking the database hides schema mismatches, FTS5 query syntax errors, and index behavior differences.

## 2. FTS5 query syntax assumptions

FTS5 phrase queries (`"word1 word2"`) require words in sequence within a single column. Token queries (`word1 OR word2`) match across columns. Tests must use the same query construction method as production code.

## 3. Path-dependent test fixtures

Don't hardcode absolute paths to test fixtures. Use `Path(__file__).parent / "fixtures" / "file.ext"` for portable fixture paths.

## 4. Haversine precision at edge cases

The haversine dedup uses a 100m threshold. At the equator, 0.001 degrees of longitude is ~111m; at 49N latitude, it's ~73m. Tests near the northern edge of the Western US bbox may produce different dedup results than tests near the southern edge.

## 5. Async test isolation

FastAPI TestClient handles async automatically, but tests that directly call async functions need `@pytest.mark.asyncio` and proper event loop handling. Don't mix sync and async test patterns.

## 6. Docker-dependent tests

Tests that require running Docker containers (integration tests) must be clearly marked and skipped when Docker is unavailable. Use `pytest.mark.skipif` with a Docker socket check.

## 7. Audio fixture format sensitivity

WAV files must be exactly 16kHz, mono, 16-bit PCM, little-endian. Tests that generate WAV data programmatically must set these parameters explicitly — don't rely on defaults from audio libraries.

## 8. Environment variable pollution

Tests that modify environment variables (`STT_BACKEND`, `MODEL_PATH`) must restore the original values after the test. Use `monkeypatch` fixture, not `os.environ` directly.

## 9. Unrecoverable async state

When an async operation (fetch, WebSocket, timer) can fail, the state machine MUST have a recovery path. Test the failure case explicitly: trigger the async operation, force it to fail, and assert the system recovers to a valid state within a bounded time. The bug pattern: state transitions to "waiting" before the async call, the call fails, and nothing transitions back. The state machine is permanently stuck.

## 10. JS truthiness for numeric zero

`value || fallback` skips zero because `0` is falsy in JavaScript. When testing code that handles numeric values (headings, coordinates, indices, counts), always include a test case with the value `0`. Use explicit null checks (`value != null ? value : fallback`) instead of `||` for nullable numbers.

## 11. Duplicated logic across modules

When two modules independently compute the same derived value (e.g., "is GPS heading valid?"), they will drift over time. Tests should verify that both modules produce the same result for the same inputs, or better yet, the code should be refactored so only one module computes the value and the other consumes it.

## 12. Tests that hit real endpoints can spawn orphaned processes (OOM risk)

Any test that sends a POST to an endpoint like `/api/pipelines/start` without mocking the orchestrator will launch a real pipeline subprocess. That subprocess may spawn children (rasterio reproject, SQLite merge). When pytest exits, the orchestrator's `cancel_all()` is never called. The child processes become orphans and run indefinitely, consuming hundreds of MB each. On a 16 GB Pi, three orphaned processes can trigger the Linux OOM killer, which may kill Claude Code — losing all unsaved session context.

**This has happened three times in one session.** Each time it was a different test hitting `/api/pipelines/start`:
1. `test_start_noaa_pipeline` — launched real NOAA pipeline, spawned `gdal_translate` children
2. `test_start_basemap_pipeline` — same pattern
3. `test_post_with_valid_csrf_token` — CSRF test that passed the token check and reached the orchestrator

**Prevention:**
- Every test that hits `/api/pipelines/start` MUST mock the orchestrator or mock GDAL detection to block the request before subprocess launch
- CSRF validation tests should use harmless endpoints (`/cancel`, `/state`) that don't spawn subprocesses
- After writing or modifying tests, run `ps aux | grep -E "acquire_|gdal_|download_elev"` to verify no orphans escaped
- After running the test suite, check `free -h` — if available memory dropped significantly, orphaned processes may be running
- Consider adding a pytest fixture or conftest.py cleanup hook that kills any child processes from test temp directories

**Detection in code review:** Search for `"/api/pipelines/start"` in test files. Any hit without a `patch("companion.get_orchestrator")` or `patch("companion.gdal_env.detect_gdal", return_value=None)` is a potential OOM bomb.

## 13. subprocess.run blocks signal handlers

`subprocess.run()` blocks the Python thread. If you register a SIGTERM handler that sets a flag, the flag is set but Python never returns from `subprocess.run()` to check it. For interruptible subprocesses, use `subprocess.Popen` with process group management (`preexec_fn=os.setsid`) and forward signals via `os.killpg()`. Test the signal path: mock a long-running subprocess, send SIGTERM, assert termination within a bounded time.

## 14. Don't pin numeric output mappings without auditing the input source

When a test asserts `someFormatter(X) === "literal output Y"`, also audit *why X is what it is*. If X is sourced from a tunable constant elsewhere in the code (a floor, a threshold, a magic number), the test pins the bucket-rounding *and* implicitly pins the constant — every passing run rubber-stamps the constant's choice instead of validating the user-experience consequence.

Symptom: tests pass but the feature feels wrong in field testing because the output is mechanically correct given the input but the input was the wrong choice. Hit this on the 2026-04-25 nav voice floor-fire bug — `formatDistancePrefix(75, true) === "In 200 feet, "` was asserted as correct, but 75m was the bug; the assertion locked it in.

Defence: where a test asserts a numeric mapping, add a comment linking the input value to the originating constant + spec rationale, so a future reviewer can audit "is X still the right input?" alongside "does the function correctly map X → Y?"
