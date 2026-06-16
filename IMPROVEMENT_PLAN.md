# Improvement Plan

Prioritized, actionable work items. Execute in order; each task is independently
committable. After any code change, follow the project rules in `CLAUDE.md`: keep
`interesting-mcp-reference.md` in sync with tool changes, update `OVERVIEW.md` where
behavior it documents changes, and run the verification commands.

**Verification for every task** (from repo root, using the project venv):

```
pytest
ruff check src tests
ruff format src tests
mypy
```

---

## Completed (reliability/maintainability review, 2026-06-12)

- Task 1 - Fix cadence eligibility timestamp comparison (DONE - commit a4ec6e0)
- Task 2 - Reject `..` traversal in `_resolve_db_path` (DONE - commit 918723f)
- Task 3 - Serialize database access with a lock (DONE - commit b7f1679)
- Task 4 - Drop the unused `INTERESTING_CLIENT_SECRET` (DONE - commit 1c07edd)
- Task 5 - Add `clear_notes` flag to `update_topic` (DONE - commit 379248e)
- Task 6 - Back up the database before applying migrations (DONE - commit a45151c)
- Task 7 - Add a type checker (mypy) (DONE - commit d962c6f)
- Task 8 - Minor cleanups (DONE - commit 5cb3f08)

---

## Configurable constants (review 2026-06-16)

Pull a small set of behavior-tuning constants out of the code and into env-driven
configuration. **Guiding rule: tune behavior, never tune stored-data semantics.** Anything a
stored row's value or a past migration depends on stays hardcoded. Specifically, leave alone:
`_CADENCE_DAYS` *keys* / `KNOWN_CADENCES`, `_MIGRATION_CADENCE`, `_STATUS_ACTIVE/_ARCHIVED`,
`_SCHEMA_VERSION`, `DEFAULT_SCOPE`, `_CONTAINED_SCOPES`, and `_DATA_DIR` (the path-confinement
root - making it configurable reopens the traversal surface closed in the previous review).

Architectural constraints (carry through every task below):

- **`storage.py` stays pure.** It must not read environment variables. Tunables enter storage
  functions as **parameters with module-level defaults** (the existing constants), so storage
  remains standalone-testable and the `server -> storage` dependency direction is preserved.
- **Env reads live in one place.** Add `src/interesting/config.py` that reads and validates
  env vars **once at import**, exposing typed, frozen values - matching the existing
  import-time env pattern (auth, allowed hosts, base URL). `server.py` imports `config` and
  passes the configured values into storage calls.
- **Fail fast on bad input** at import/startup with a clear `ValueError`, mirroring
  `_resolve_db_path` - never silently coerce.

---

## Task 9 - Introduce `config.py` and make the roundup limit configurable

**Problem.** `_ROUNDUP_LIMIT = 6` (`storage.py:11`) is the roundup batch size - pure query
behavior with no data coupling - but is not tunable per deployment. There is also no single
home for parsed/validated runtime config.

**Fix.**
- Add `src/interesting/config.py`. It owns all env reads for tunables and exposes typed,
  validated module-level values. No filesystem I/O at import (safe to import in tests).
- Add `INTERESTING_ROUNDUP_LIMIT`: parse to `int`, require `>= 1`, default `6`. Reject
  non-integer or `<= 0` with a `ValueError` naming the variable and the bad value.
- Add a `roundup_limit: int = _ROUNDUP_LIMIT` parameter to `storage.list_topics`
  (`storage.py:229`); use it for the `LIMIT` instead of the bare constant. The module-level
  default preserves standalone behavior.
- In the `list_topics` tool (`server.py:376`), pass `roundup_limit=config.ROUNDUP_LIMIT`
  into the storage call (inside the existing `_db_lock` block).

**Tests.**
- New `tests/test_config.py` (pure parsing, no DB): default is `6`; a valid override parses;
  non-int, `0`, and negative each raise `ValueError`.
- Behavioral test via the existing `monkeypatch.setattr` pattern used for `_db_path`: set the
  limit to `2`, seed 5+ active topics, assert `list_topics(roundup=True)` returns at most 2.
- Storage-layer test: call `storage.list_topics(conn, roundup=True, roundup_limit=2)`
  directly (no env) and assert the cap - exercises the defaulting/param path.
- Default-preservation regression: with no env set, `_ROUNDUP_LIMIT == 6`.

**Docs.** README.md Environment Variables table; `.env.example` (commented entry);
`OVERVIEW.md` "Roundup Rotation" + "Configuration" (note the limit is env-tunable and
describe the new `config.py` layer and the "tune behavior, not stored-data semantics"
boundary). `interesting-mcp-reference.md` - replace any specific mention of the batch size
with "up to N topics (default: 6)".

---

## Task 10 - Make cadence interval days configurable

**Problem.** The day values in `_CADENCE_DAYS` (`storage.py:26`) are eligibility tuning only,
but are hardcoded. `_CADENCE_ELIGIBILITY_CLAUSE` is additionally **precomputed at module load**
(`storage.py:64`), so it cannot reflect runtime config.

**Fix.**
- Add `INTERESTING_CADENCE_DAYS` to `config.py` as comma-separated `key:days` pairs (e.g.
  `rare:14,occasional:7,regular:3,frequent:1`). Validation:
  - each key must be in `KNOWN_CADENCES` **and not** `always` (whose interval is `None` =
    no minimum; it is not a day count and cannot be overridden);
  - `days` must parse to `int >= 1`;
  - unknown key, the `always` key, malformed pair, or bad `days` -> `ValueError`;
  - unspecified keys fall back to the defaults, so a deployment can override just one.
  The validated result is a full `dict[str, int | None]` merged over the defaults.
- Add a `cadence_days: dict[str, int | None] = _CADENCE_DAYS` parameter to
  `storage.list_topics`. **Move clause construction into `list_topics`** (build from the
  passed-in map per call) and delete the module-level `_CADENCE_ELIGIBILITY_CLAUSE` /
  precompute. Per-call rebuild of a short SQL string is negligible and removes hidden
  module-level state. Keep `_build_cadence_eligibility_clause` as a helper that takes the map.
  - **Note:** `days` is f-string-interpolated into SQL (not a bound parameter), so the
    `int >= 1` validation in `config.py` is the only thing standing between input and the
    query - keep it strict.
- In the `list_topics` tool, pass `cadence_days=config.CADENCE_DAYS`.

**Tests.**
- `tests/test_config.py`: single override; partial override leaves other keys at default;
  rejects non-int days, `0`/negative, unknown key, `always` override, and malformed pairs.
- Behavioral: with `regular:1`, a 25-hour-old `regular` topic appears in
  `list_topics(roundup=True)` where the default 3-day interval would exclude it.
- Default-preservation regression: with no env set, the effective map equals today's
  `_CADENCE_DAYS` (guards against default drift).

**Docs.** README.md + `.env.example` (format/fallback notes); `OVERVIEW.md` "Roundup
Rotation" (clause now built per-call from configurable days) + "Configuration".
`interesting-mcp-reference.md` - replace specific day counts with "N days (default: X)"
wherever cadence intervals appear; the reference doc is consumed by the AI client as the
`interesting://instructions` resource, so it must stay correct across deployments.

---

## Deferred - flag the tradeoff before implementing

- **Tier 2/3 tunables** (`INTERESTING_TITLE_MAX`, `INTERESTING_NOTES_MAX`,
  `INTERESTING_HTTP_PORT`, auth TTLs `_AUTH_CODE_TTL` / `_TOKEN_TTL` / `_AUTH_CODE_BYTES`).
  Same `config.py` pattern. `128` and `512` appear as literal numbers in
  `interesting-mcp-reference.md` (the `interesting://instructions` resource consumed by the AI
  client) and tool descriptions; if made configurable, replace them with "up to N characters
  (default: 128/512)" - same approach as Task 10's cadence intervals. The HTTP port is
  currently not even a named constant (FastMCP default + `_DEFAULT_BASE_URL`); promote to a
  named constant first if it becomes configurable.
- **`DEFAULT_CADENCE` / `DEFAULT_SCOPE` as env vars.** Safe-ish but low demand; defer unless
  a concrete need appears. `DEFAULT_SCOPE` in particular is woven into the scope-hierarchy
  logic - treat as stored-data-adjacent and keep hardcoded.

---

## Deferred - needs analysis and discussion first; do NOT implement

These were reviewed but the owner wants a design discussion before choosing a solution.

- **`_REFERENCE_DOC` cwd dependence** (`server.py`). The reference doc resolves from
  `Path.cwd()` at import time; a test (`test_reference_doc_path_is_cwd_relative`) asserts this
  is intentional. Candidate options: fail fast at startup if missing; ship the doc as package
  data via `importlib.resources`; resolve relative to a configurable root. Leave as-is for now.
- **CI setup.** No automated checks run on PRs. Candidate shape: GitHub Actions workflow
  running `pytest`, `ruff check`, `ruff format --check`, and `mypy` on Windows and Linux.
  Needs discussion (runner choice, uv vs pip, branch protection).
