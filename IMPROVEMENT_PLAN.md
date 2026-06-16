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

## Completed (configurable constants review, 2026-06-16)

- Task 9 - Introduce `config.py` and make the roundup limit configurable (DONE)
- Task 10 - Make cadence interval days configurable (DONE)

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
