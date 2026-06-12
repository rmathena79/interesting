# Improvement Plan

Prioritized, actionable work items from a reliability/maintainability review (2026-06-12).
Execute in order; each task is independently committable. After any code change, follow the
project rules in `CLAUDE.md`: keep `interesting-mcp-reference.md` in sync with tool changes,
update `OVERVIEW.md` where behavior it documents changes, and run the verification commands.

**Verification for every task** (from repo root, using the project venv):

```
pytest
ruff check src tests
ruff format src tests
```

Note: the working tree already contains uncommitted changes to `src/interesting/server.py`
(OAuth logging, `token_endpoint_auth_method="none"`) and `tests/test_server.py`. Task 4
builds on those changes; do not revert them.

---

## Task 1 — Fix cadence eligibility timestamp comparison (BUG, highest priority)

**Problem.** `_build_cadence_eligibility_clause()` in `src/interesting/storage.py` (~line 51)
compares `last_checked_at <= datetime('now', '-N days')` as strings. The application writes
`last_checked_at` via `datetime.now(timezone.utc).isoformat()`, producing
`2026-06-11T16:57:46.495858+00:00`, but SQLite's `datetime()` produces
`2026-06-11 21:57:46` (space separator, no offset). Because `'T' > ' '`, any same-date
comparison evaluates to "not eligible", so every cadence cooldown runs up to ~24 hours long.
Confirmed by repro: a `frequent` (1-day) topic checked 29 hours ago is reported ineligible.

**Fix.** In the generated SQL clause, normalize the stored value before comparing:

```sql
(cadence = '<cadence>' AND datetime(last_checked_at) <= datetime('now', '-<days> days'))
```

SQLite's `datetime()` parses the `T` separator and the `+00:00` offset correctly, and both
sides then share SQLite's canonical `YYYY-MM-DD HH:MM:SS` format, making lexicographic
comparison equivalent to chronological comparison. Keep the `last_checked_at IS NULL` and
`cadence = 'always'` branches as they are.

**Tests.**
1. Fix the root cause of the test blind spot: `_backdate_last_checked` in
   `tests/test_server.py` (~line 852) currently writes stamps with SQLite's
   `datetime('now', ?)`, i.e. the format production never writes. Change it to compute the
   backdated timestamp in Python and write `datetime.now(timezone.utc) - timedelta(days=...)`
   `.isoformat()`, so the suite exercises the production format. The existing cadence tests
   then become regression coverage for this bug.
2. Add one explicit regression test for the same-date boundary: a `frequent` topic whose
   Python-isoformat `last_checked_at` is 25 hours ago (same effort: > 1 day but cutoff and
   stamp can share a calendar date) must appear in `list_topics(roundup=True)`.

**Docs.** `OVERVIEW.md` (Roundup Rotation section, ~line 121) currently asserts the
lexicographic comparison is correct. Rewrite that sentence to describe the `datetime()`
normalization and why it is needed.

---

## Task 2 — Reject `..` traversal in `_resolve_db_path`

**Problem.** `_resolve_db_path` in `src/interesting/server.py` (~line 145) rejects absolute
paths but accepts `..` segments, so `--db ../../foo.db` escapes the `data/` directory the
function exists to confine paths to.

**Fix.** After normalizing separators, split the path and raise `ValueError` if any segment
is `..` (message should parallel the existing absolute-path error, e.g.
`"parent-directory segments are not supported; pass a filename or relative path (got {name!r})"`).
Rejecting bare `..` segments is sufficient; do not try to resolve/canonicalize.

**Tests.** Add cases to `tests/test_db_path.py`:
- `_resolve_db_path("../foo.db")` raises `ValueError`
- `_resolve_db_path("a/../../foo.db")` raises `ValueError`
- `_resolve_db_path("..\\foo.db")` raises `ValueError` (backslash form)
- `_resolve_db_path("a..b/foo.db")` succeeds (only exact `..` segments are rejected)

**Docs.** Add one line to `OVERVIEW.md` Configuration section (it already documents that
absolute paths are rejected).

---

## Task 3 — Serialize database access with a lock

**Problem.** `server.py` shares one `sqlite3.Connection` (opened with
`check_same_thread=False`) across all tool calls. FastMCP runs the synchronous tool functions
on worker threads, so concurrent requests (HTTP mode) can interleave. The roundup path in
`storage.list_topics` (SELECT, then UPDATE, then commit, ~lines 238-258) is not atomic: two
concurrent roundup calls can return the same topics or stamp rows they did not return.

**Fix.** Add a module-level `threading.Lock` in `server.py` and acquire it around every
storage call inside the tool functions. The simplest clean shape: have `_get_conn()` remain
as-is and add a small helper or `with _db_lock:` block in each tool around the
`storage.*(...)` call. Do not add locking inside `storage.py` — it is a pure-function layer
over a connection and should stay thread-agnostic (this also keeps tests, which open their
own connections, unaffected).

**Tests.** A deterministic concurrency test is not practical here; rely on code review. Do
not add a flaky timing-based test.

**Docs.** Update `OVERVIEW.md` "Connection Lifecycle and Testing" to state that tool-level
access is serialized by a lock and why.

---

## Task 4 — Drop the unused `INTERESTING_CLIENT_SECRET` (decision: confirmed by owner)

**Problem.** The working tree already switched `token_endpoint_auth_method` to `"none"`, so
the client secret no longer participates in authentication, yet `_auth_enabled`
(`server.py` ~line 45) still requires `INTERESTING_CLIENT_SECRET` and the startup warning
in `__main__` tells users to set it.

**Fix.**
- Remove `_client_secret` and its env read.
- `_auth_enabled = bool(_client_id and _access_token_value)`.
- Update the HTTP-without-auth startup warning to mention only `INTERESTING_CLIENT_ID` and
  `INTERESTING_ACCESS_TOKEN`.
- Remove `INTERESTING_CLIENT_SECRET` from `.env.example`, `README.md`, and the `OVERVIEW.md`
  Configuration table and Authentication section.

**Tests.** None required (auth is exercised only indirectly today); just ensure the suite
still passes and grep the repo for `CLIENT_SECRET` to confirm no stragglers.

---

## Task 5 — Add `clear_notes` flag to `update_topic` (decision: confirmed by owner)

**Problem.** The storage layer already supports clearing notes
(`update_topic(..., notes=None, update_notes=True)`), but the server tool treats empty
string as "leave unchanged", so once set, notes can never be removed.

**Fix.** In the `update_topic` tool in `server.py`:
- Add parameter `clear_notes: bool = False`.
- Validation: `clear_notes=True` together with a non-empty `notes` value is a `ValueError`
  ("pass either notes or clear_notes, not both").
- `clear_notes=True` counts toward the "at least one field provided" check.
- When set, call storage with `notes=None, update_notes=True`.
- Extend the tool description to document the flag.

**Tests.** Add to `tests/test_server.py`:
- Set notes, call `update_topic` with `clear_notes=True`, verify `notes` is `null` in the
  response and in a subsequent `list_topics`.
- `clear_notes=True` plus non-empty `notes` fails.
- `clear_notes=True` as the only field succeeds (satisfies "at least one").
- `clear_notes=False` (default) leaves existing notes unchanged (already covered, keep).

**Docs.** This is a tool-contract change: update `interesting-mcp-reference.md` (single
source of truth for the `interesting://instructions` resource — required by `CLAUDE.md`)
and the `OVERVIEW.md` storage-function table if wording there needs it.

---

## Task 6 — Back up the database before applying migrations

**Problem.** `storage.init_db` auto-migrates the production database on startup with no
backup; current backups are manual folder copies (`data/production - Copy (2)` etc.).

**Fix.** In `init_db`, after computing the effective `version` but before applying any
migration block, if `version < _SCHEMA_VERSION` **and** the database file already exists
with content (skip for brand-new databases), create a backup:

```sql
VACUUM INTO '<db_path>.pre-migration-v<version>-<YYYYMMDDTHHMMSSZ>.db'
```

Use a UTC timestamp, log the backup path at INFO level, and raise (do not proceed with
migrations) if the backup statement fails. Do not implement retention/pruning — old backups
are the operator's concern.

**Tests.** Reuse the v3-database builder pattern from
`test_migration_v3_to_v4_backfills_frequent` in `tests/test_server.py`: open a v3 database,
run `init_db`, assert exactly one `*.pre-migration-v3-*.db` file exists next to it. Also
assert that opening a fresh database creates no backup file, and that re-opening an
up-to-date database creates no backup file.

**Docs.** Add a short paragraph to `OVERVIEW.md` Database Schema section.

---

## Task 7 — Add a type checker (mypy)

**Problem.** `CLAUDE.md` mandates strict type annotations but nothing enforces them.

**Fix.**
- Add `mypy>=1.14` to the `dev` dependency group in `pyproject.toml`.
- Add a `[tool.mypy]` section: `python_version = "3.11"`, `strict = true`,
  `files = ["src"]`. Run it over `src` only at first; tests use intentional
  `# type: ignore[union-attr]` patterns and can be brought under checking later.
- Fix whatever `mypy` reports in `src/` (expected to be small; annotations are already
  thorough). If a finding requires a behavioral decision, leave a `# type: ignore[<code>]`
  with the specific error code rather than restructuring.
- Add a row to the `CLAUDE.md` Commands table: `Type check | mypy`.

**Verification.** `mypy` exits 0.

---

## Task 8 — Minor cleanups (single commit)

1. **Delete `tests/test_placeholder.py`** — dead file.
2. **Prune expired OAuth codes.** In `_SingleUserOAuthProvider.authorize`
   (`server.py` ~line 82), before storing the new code, drop entries from
   `self._pending_codes` whose `expires_at < time.time()`. Keeps the dict bounded across
   abandoned auth attempts in a long-lived process.
3. **Comment the static-token TTL mismatch.** In `exchange_authorization_code`, add a brief
   comment noting that `expires_in=_TOKEN_TTL` is advisory only: `load_access_token` never
   expires the static token; expiry merely prompts the client to redo the auth flow. This is
   a constraint the code cannot otherwise show.

---

## Deferred — needs analysis and discussion first; do NOT implement

These were reviewed but the owner wants a design discussion before choosing a solution.
Do not change behavior in these areas beyond what the tasks above require.

- **`_REFERENCE_DOC` cwd dependence** (`server.py` ~line 270). The reference doc resolves
  from `Path.cwd()` at import time; a test (`test_reference_doc_path_is_cwd_relative`)
  asserts this is intentional. Candidate options to discuss: fail fast at startup if
  missing; ship the doc as package data via `importlib.resources`; resolve relative to a
  configurable root. Leave as-is for now.
- **CI setup.** No automated checks run on PRs. Candidate shape: GitHub Actions workflow
  running `pytest`, `ruff check`, `ruff format --check` (plus `mypy` after Task 7) on
  Windows and Linux. Needs discussion (runner choice, uv vs pip, branch protection).
