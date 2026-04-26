# Wake-lock JS unit tests

Run from repo root:

```bash
node --test frontend/tests/wake-lock/
```

Uses Node's built-in `node:test` module (stable since Node 20). No other dependencies.

Directory is deliberately named with a hyphen (`wake-lock`) so pytest does NOT attempt to collect files here as Python tests.

See `docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md` §6.2 for the test inventory and mock factory specification.
