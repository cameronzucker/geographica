# Testing Pitfalls

Patterns observed during bug hunts that tests should guard against.

## Exception type mismatches in except clauses
When calling functions that operate on values that could be None, `except (ValueError, TypeError)` is insufficient -- `AttributeError` from calling methods on None (e.g., `None.split(",")`) slips through. Tests should verify error paths with actual None inputs, not just malformed strings.
*Found in:* `services/search/main.py:1175-1181` -- `_parse_bbox(None)` raises AttributeError, not caught by except.

## Resource lifecycle in multi-phase functions
When a function acquires a resource (e.g., Docker client), closes it, then conditionally uses it again later, the closed resource may appear truthy but fail silently. Tests that mock the resource should verify it's called in the right lifecycle phase.
*Found in:* `services/search/main.py:1140,1156` -- Docker client used after close, logs silently lost.
