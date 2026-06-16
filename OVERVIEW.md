# Architecture Overview

## Purpose

`interesting` is a Model Context Protocol (MCP) server that gives chat clients persistent, cross-session tracking of news topics. A chat client uses the server's tools to add, list, update, and remove topics, and to pull a rotating batch for a news roundup. The server is stateless between tool calls; all state lives in a SQLite database.

## Technology Stack

| Layer | Technology |
|---|---|
| MCP server framework | [FastMCP](https://github.com/jlowin/fastmcp) (`mcp.server.fastmcp`) |
| Database | SQLite via Python stdlib `sqlite3` |
| Transport | `stdio` (subprocess) or `streamable-http` (persistent HTTP) |
| Language | Python 3.11+ |
| Testing | pytest + pytest-anyio |
| Lint / Format | Ruff |
| Type checking | mypy (strict, `src/` only) |

## File Layout

```
src/interesting/
    __init__.py       empty package marker
    config.py         runtime configuration -- env var parsing, typed module-level values
    storage.py        database layer -- pure functions over a sqlite3.Connection
    server.py         MCP server -- tool definitions, validation, connection lifecycle

tests/
    test_config.py    unit tests for config.py parsing
    test_server.py    integration tests via MCP client/server session
    test_db_path.py   unit tests for path resolution logic

interesting-mcp-reference.md   tool reference and operational workflows (also served
                                as the interesting://instructions MCP resource)
```

## Architecture

The codebase has two layers with a strict dependency direction: `server.py` depends on `storage.py`; `storage.py` has no knowledge of the server.

### Storage layer (`storage.py`)

All database access is through plain functions that take a `sqlite3.Connection` as their first argument. The module holds no global state. Functions are:

| Function | Purpose |
|---|---|
| `init_db(db_path)` | Opens/creates the database, runs schema migrations, returns the connection |
| `add_topic(conn, title, scope, notes, cadence)` | Inserts a new topic, returns a `Topic` |
| `list_topics(conn, scope, roundup, include_archived)` | Queries topics with optional scope filter, roundup logic (cadence-eligibility filter + rotation), and archived filter |
| `update_topic(conn, topic_id, title, scope, notes, update_notes, cadence)` | Updates fields, returns the updated `Topic` or `None` |
| `archive_topic(conn, topic_id, archived)` | Sets status to `"archived"` or `"active"`, returns the updated `Topic` or `None` |
| `remove_topic(conn, topic_id)` | Deletes by ID, returns success bool |
| `get_scope_hierarchy()` | Returns the containment map; no database access |

### Server layer (`server.py`)

Defines a `FastMCP` instance with seven tools and one resource. It owns the `sqlite3.Connection` lifecycle:

- `_conn: sqlite3.Connection | None` -- module-level connection, `None` until the server starts.
- `_lifespan` -- async context manager registered with FastMCP. On startup it resolves the database path, calls `storage.init_db`, and stores the returned connection. On shutdown it closes the connection.
- `_get_conn()` -- guard that raises `RuntimeError` if called before the lifespan has run.

Tool functions are synchronous; FastMCP handles the async boundary. Each tool validates its inputs, calls the appropriate storage function via `_get_conn()`, and returns a JSON string.

## Data Model

### `Topic` (NamedTuple)

```python
class Topic(NamedTuple):
    id: str               # UUID4, server-generated
    title: str            # printable ASCII, 1-128 chars
    scope: str            # one of KNOWN_SCOPES
    added_at: str | None  # ISO 8601 UTC; null for pre-migration rows
    last_checked_at: str | None  # ISO 8601 UTC; null until first roundup inclusion
    notes: str | None     # optional search guidance, printable ASCII <=512 chars; null if unset
    status: str           # "active" (default) or "archived"
    cadence: str          # one of KNOWN_CADENCES; "regular" default for new topics
```

`Topic.to_dict()` produces the canonical JSON-serializable dict returned by all tools.

### Database Schema

```sql
CREATE TABLE schema_version (version INTEGER NOT NULL);

CREATE TABLE topics (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    scope           TEXT NOT NULL,
    added_at        TEXT,                              -- added in migration 1
    last_checked_at TEXT,                              -- added in migration 2
    notes           TEXT,                              -- added in migration 3
    status          TEXT NOT NULL DEFAULT 'active',    -- added in migration 3
    cadence         TEXT NOT NULL DEFAULT 'frequent'   -- added in migration 4
);
```

`schema_version` holds a single row with the current migration level. `init_db` compares this value against `_SCHEMA_VERSION = 4` and applies any outstanding `ALTER TABLE` migrations. Legacy databases that pre-date version tracking are detected by column inspection on the first run and stamped with the highest migration level whose columns are all present.

The `cadence` column's column-level default of `'frequent'` only fires for rows pre-existing at v3-to-v4 migration time; new rows inserted by `add_topic` use `DEFAULT_CADENCE = 'regular'` from the application layer.

SQLite is opened in WAL mode (`PRAGMA journal_mode=WAL`) to allow concurrent reads alongside writes.

When `init_db` detects that a pre-existing database file needs migration (version < current schema), it creates a point-in-time backup via `VACUUM INTO '<db_path>.pre-migration-v<N>-<YYYYMMDDTHHMMSSZ>.db'` before applying any `ALTER TABLE` statements. The backup is logged at INFO level. If the `VACUUM INTO` statement fails, `init_db` raises immediately without applying any migrations. Brand-new databases and already up-to-date databases are not backed up. No retention or pruning is performed -- managing old backups is the operator's responsibility.

## Scope System

Scopes are a fixed, server-defined hierarchy stored in `storage.py`:

```python
_CONTAINED_SCOPES = {
    "us":  {"us", "pdx"},
    "pdx": {"pdx"},
}
KNOWN_SCOPES = frozenset({"world", "us", "pdx"})
```

`DEFAULT_SCOPE = "world"` means "no filter" -- a `list_topics` call scoped to `world` returns all topics regardless of their stored scope. Narrower scopes filter to only the topics contained within them. The hierarchy is intentionally hardcoded; adding a scope requires modifying `_CONTAINED_SCOPES` and bumping `_SCHEMA_VERSION` if a migration is needed.

## Roundup Rotation

`list_topics(roundup=True)` implements topic rotation so that successive roundup calls distribute attention across all tracked topics rather than always returning the same ones. Only `status = 'active'` topics participate; archived topics are never returned in roundup mode.

Eligibility runs as a SQL filter before rotation: a topic is eligible when its cadence is `'always'`, when `last_checked_at IS NULL`, or when `datetime(last_checked_at) <= datetime('now', '-N days')` for the cadence's minimum-interval `N`. The clause is built per-call inside `list_topics` from the `cadence_days` parameter (defaulting to `_CADENCE_DAYS`) by `_build_cadence_eligibility_clause(cadence_days)`, and appended to the WHERE conditions only when `roundup=True`. The `days` values are f-string-interpolated into the SQL (not bound parameters); the `int >= 1` validation in `config.py` is the guard between the env input and the query. Wrapping the stored value in `datetime()` is required because `last_checked_at` is written as a Python isoformat string (e.g. `2026-06-11T16:57:46.495858+00:00`, using a `T` separator and `+00:00` offset), whereas SQLite's `datetime('now', ...)` produces `2026-06-11 21:57:46` (space separator, no offset). Because `'T' > ' '`, a bare string comparison would wrongly report same-day timestamps as ineligible; `datetime()` on both sides normalizes to SQLite's canonical `YYYY-MM-DD HH:MM:SS` format, making the comparison correct.

After eligibility filtering, the query orders by `last_checked_at ASC, RANDOM()` and applies a `LIMIT` equal to `roundup_limit` (a parameter of `list_topics`, defaulting to `_ROUNDUP_LIMIT = 6`). SQLite sorts `NULL` first in ascending order, so unchecked topics are naturally prioritized without an explicit `NULLS FIRST` clause. After the SELECT, `last_checked_at` is written for every returned row in a single batch UPDATE; if eligibility filtering returns zero rows, the update is skipped. The batch size is configurable via `INTERESTING_ROUNDUP_LIMIT` (parsed by `config.py`); see the Configuration section below.

The cadence values exposed to clients (`rare`, `occasional`, `regular`, `frequent`, `always`) and their day mappings live in `_CADENCE_DAYS`; `KNOWN_CADENCES` is the validation set, `DEFAULT_CADENCE = "regular"` is the application-layer default for new topics, and `_MIGRATION_CADENCE = "frequent"` is the column-level default applied to rows already in the database when migration 4 runs. The day values (not the keys) are configurable via `INTERESTING_CADENCE_DAYS`; see the Configuration section below.

## Connection Lifecycle and Testing

In production, `_lifespan` opens one connection for the life of the server process.

FastMCP dispatches synchronous tool functions on worker threads, so concurrent HTTP requests can reach the same `sqlite3.Connection` simultaneously. A module-level `_db_lock = threading.Lock()` in `server.py` serializes all storage calls: each tool acquires the lock around its `storage.*` call before touching the connection. The lock lives in `server.py`, not `storage.py`, to keep the storage layer thread-agnostic.

In tests, `monkeypatch.setattr(server_module, "_db_path", db_file)` points the lifespan at a per-test `tmp_path` file. Each test wraps its tool calls in `async with create_connected_server_and_client_session(mcp)`, which runs the full lifespan, giving each session a fresh connection to an isolated database.

## Transport Modes

| Mode | How to run | Use case |
|---|---|---|
| `stdio` (default) | MCP client spawns the process | Claude Desktop subprocess integration |
| `streamable-http` | `python -m interesting.server --transport streamable-http` | Persistent server, network access |

Transport is selected via the `--transport` CLI argument or `MCP_TRANSPORT` environment variable, with CLI taking precedence. In HTTP mode the server binds to `0.0.0.0:8000`.

## Authentication

HTTP mode supports OAuth 2.0 Authorization Code + PKCE, opt-in via two environment variables. Auth is disabled when either is absent, which is the correct default for stdio mode and local dev.

### Token flow

1. Claude discovers the OAuth server metadata and redirects to the server's `/authorize` endpoint to initiate the Authorization Code + PKCE flow.
2. The server auto-approves the request (security relies on network-level access control, e.g. Tailscale) and redirects back to Claude's callback URL with a short-lived authorization code (TTL: 5 minutes).
3. Claude POSTs the authorization code and PKCE verifier to `/token` and receives a static bearer token (TTL: 24 hours).
4. Claude includes `Authorization: Bearer <token>` on every subsequent MCP request.
5. `_SingleUserOAuthProvider.load_access_token()` validates the token using `secrets.compare_digest` (constant-time comparison).

`_SingleUserOAuthProvider` is registered with FastMCP via the `auth_server_provider` constructor parameter. Auth credentials (`_client_id`, `_access_token_value`) are read from environment variables at import time -- no filesystem I/O, safe to import in tests.

### Metadata patch: advertising `token_endpoint_auth_methods_supported: "none"`

The MCP library hardcodes `token_endpoint_auth_methods_supported` to `["client_secret_post", "client_secret_basic"]` in `mcp.server.auth.routes.build_metadata`. Claude registers as a public client and completes the token exchange with PKCE alone (no client secret), and the Client ID Metadata Document (CIMD) connector path *requires* the server to advertise `"none"`. At import time `server.py` wraps `build_metadata` to prepend `"none"` to that list. The registered client also uses `token_endpoint_auth_method="none"`; the token endpoint no longer validates a client secret, since PKCE plus the redirect URI locked to `https://claude.ai/api/mcp/auth_callback` already prevent an intercepted code from being exchanged by anyone else.

### Known claude.ai OAuth limitations (web custom connector)

The claude.ai **web** custom connector has a class of open, server-independent bugs where the OAuth flow completes `/authorize` but the connector never POSTs to `/token` (or obtains the token and then fails to attach it), surfacing as "Authorization with the MCP server failed" with an `ofid_...` reference. See anthropics/claude-ai-mcp issues #155, #250, #313. Notably #250: claude.ai rejects an `/authorize` redirect that uses HTTP **307** instead of 302/303, with a misleading "Method Not Allowed" error. This server's `/authorize` already returns **302** (FastMCP's `AuthorizationHandler`), so it is not subject to #250 -- but as defensive hardening against claude.ai's brittleness toward 307s, the streamable-http app is run with Starlette's `redirect_slashes` **disabled** (see `_run_streamable_http_no_redirect`) so no trailing-slash route (e.g. `/.well-known/oauth-authorization-server/`) ever emits a 307; non-canonical paths return 404 instead.

Because these limitations are claude.ai-side, the reliable way to use the server when the web connector fails is to **bypass OAuth with a static bearer header**. The server's `load_access_token` accepts any request whose token matches `INTERESTING_ACCESS_TOKEN`, regardless of how the client obtained it, so a client that can set a header works without the OAuth dance -- e.g. `claude mcp add --transport http interesting <base-url>/ --header "Authorization: Bearer <INTERESTING_ACCESS_TOKEN>"`.

## Configuration

| Source | Precedence | Variables / flags |
|---|---|---|
| CLI arguments | Highest | `--transport`, `--db` |
| Environment variables | Middle | `MCP_TRANSPORT`, `INTERESTING_DB_PATH`, `INTERESTING_ALLOWED_HOSTS`, `INTERESTING_CLIENT_ID`, `INTERESTING_ACCESS_TOKEN`, `INTERESTING_BASE_URL`, `INTERESTING_ROUNDUP_LIMIT`, `INTERESTING_CADENCE_DAYS` |
| Defaults | Lowest | `stdio`, `data/interesting.db`, `localhost,127.0.0.1` (allowed hosts), auth disabled, roundup limit 6, cadence days as in `_CADENCE_DAYS` |

### Behavior tunables (`config.py`)

`src/interesting/config.py` owns all env reads for behavior tunables and exposes typed, validated module-level values. It is safe to import in tests -- no filesystem I/O at import, and bad values raise `ValueError` at import time (fail fast). `server.py` imports `config` and passes its values into storage calls as parameters.

Guiding rule: **tune behavior, never tune stored-data semantics.** The following are intentionally hardcoded and cannot be overridden: `KNOWN_CADENCES` keys, `_MIGRATION_CADENCE`, status constants, `_SCHEMA_VERSION`, `DEFAULT_SCOPE`, `_CONTAINED_SCOPES`, and `_DATA_DIR`.

| Variable | Default | Description |
|---|---|---|
| `INTERESTING_ROUNDUP_LIMIT` | `6` | Maximum topics returned per roundup call. Must be a positive integer (`>= 1`). |
| `INTERESTING_CADENCE_DAYS` | `rare:14,occasional:7,regular:3,frequent:1` | Comma-separated `key:days` pairs overriding cadence cooldown intervals. Unknown keys, the `always` key, non-integer values, and values `<= 0` are rejected. Unspecified cadences fall back to their defaults. `always` cannot be overridden (its interval is `None`, not a day count). |

### Database path resolution

`_db_path` is `None` at import time and resolved inside `_lifespan` at startup, so importing the module for tests or tooling does not trigger environment variable reads or filesystem access.

Database paths are resolved relative to the `data/` directory; absolute paths and paths containing `..` segments are rejected.
