"""
Shared pytest configuration for the Geographica test suite.

Problem: test_osm_poi_search.py and test_spatial_osm.py use
asyncio.get_event_loop().run_until_complete(...) in synchronous fixtures.
In Python 3.13 + pytest-asyncio strict mode, the per-test event loop is
closed after each async test, leaving no current loop for the next sync
fixture that calls asyncio.get_event_loop().

Fix: autouse function-scoped fixture that re-sets a fresh event loop after
every test, ensuring synchronous callers of asyncio.get_event_loop() always
find a usable loop.
"""
import asyncio
import pytest


@pytest.fixture(autouse=True)
def _restore_event_loop():
    """Ensure a new event loop is current before and after each test.

    Prevents RuntimeError('There is no current event loop') in synchronous
    fixtures that call asyncio.get_event_loop() (pre-3.10 style) when they
    run after an async test that closed the previous loop.
    """
    # Before: ensure a loop exists
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop closed")
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    yield

    # After: if the current loop is closed/absent, install a fresh one
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            asyncio.set_event_loop(asyncio.new_event_loop())
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
