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
