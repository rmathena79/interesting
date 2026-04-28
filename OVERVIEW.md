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

## File Layout

```
src/interesting/
    __init__.py       empty package marker
    storage.py        database layer — pure functions over a sqlite3.Connection
    server.py         MCP server — tool definitions, validation, connection lifecycle

tests/
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
| `add_topic(conn, title, scope)` | Inserts a new topic, returns a `Topic` |
| `list_topics(conn, scope, roundup)` | Queries topics with optional scope filter and roundup logic |
| `update_topic(conn, topic_id, title, scope)` | Updates fields, returns the updated `Topic` or `None` |
| `remove_topic(conn, topic_id)` | Deletes by ID, returns success bool |
| `get_scope_hierarchy()` | Returns the containment map; no database access |

### Server layer (`server.py`)

Defines a `FastMCP` instance with six tools and one resource. It owns the `sqlite3.Connection` lifecycle:

- `_conn: sqlite3.Connection | None` — module-level connection, `None` until the server starts.
- `_lifespan` — async context manager registered with FastMCP. On startup it resolves the database path, calls `storage.init_db`, and stores the returned connection. On shutdown it closes the connection.
- `_get_conn()` — guard that raises `RuntimeError` if called before the lifespan has run.

Tool functions are synchronous; FastMCP handles the async boundary. Each tool validates its inputs, calls the appropriate storage function via `_get_conn()`, and returns a JSON string.

## Data Model

### `Topic` (NamedTuple)

```python
class Topic(NamedTuple):
    id: str               # UUID4, server-generated
    title: str            # ASCII, 1–128 chars
    scope: str            # one of KNOWN_SCOPES
    added_at: str | None  # ISO 8601 UTC; null for pre-migration rows
    last_checked_at: str | None  # ISO 8601 UTC; null until first roundup inclusion
```

`Topic.to_dict()` produces the canonical JSON-serializable dict returned by all tools.

### Database Schema

```sql
CREATE TABLE schema_version (version INTEGER NOT NULL);

CREATE TABLE topics (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    scope           TEXT NOT NULL,
    added_at        TEXT,          -- added in migration 1
    last_checked_at TEXT           -- added in migration 2
);
```

`schema_version` holds a single row with the current migration level. `init_db` compares this value against `_SCHEMA_VERSION = 2` and applies any outstanding `ALTER TABLE` migrations. Legacy databases that pre-date version tracking are detected by column inspection on the first run and stamped with the current version.

SQLite is opened in WAL mode (`PRAGMA journal_mode=WAL`) to allow concurrent reads alongside writes.

## Scope System

Scopes are a fixed, server-defined hierarchy stored in `storage.py`:

```python
_CONTAINED_SCOPES = {
    "us":  {"us", "pdx"},
    "pdx": {"pdx"},
}
KNOWN_SCOPES = frozenset({"world", "us", "pdx"})
```

`DEFAULT_SCOPE = "world"` means "no filter" — a `list_topics` call scoped to `world` returns all topics regardless of their stored scope. Narrower scopes filter to only the topics contained within them. The hierarchy is intentionally hardcoded; adding a scope requires modifying `_CONTAINED_SCOPES` and bumping `_SCHEMA_VERSION` if a migration is needed.

## Roundup Rotation

`list_topics(roundup=True)` implements topic rotation so that successive roundup calls distribute attention across all tracked topics rather than always returning the same ones. The query orders by `last_checked_at ASC NULLS FIRST, RANDOM()` and applies a `LIMIT 6`. After the SELECT, `last_checked_at` is written for every returned row in a single batch UPDATE. The `_ROUNDUP_LIMIT = 6` constant controls the batch size.

## Connection Lifecycle and Testing

In production, `_lifespan` opens one connection for the life of the server process.

In tests, `monkeypatch.setattr(server_module, "_db_path", db_file)` points the lifespan at a per-test `tmp_path` file. Each test wraps its tool calls in `async with create_connected_server_and_client_session(mcp)`, which runs the full lifespan, giving each session a fresh connection to an isolated database.

## Transport Modes

| Mode | How to run | Use case |
|---|---|---|
| `stdio` (default) | MCP client spawns the process | Claude Desktop subprocess integration |
| `streamable-http` | `python -m interesting.server --transport streamable-http` | Persistent server, network access |

Transport is selected via the `--transport` CLI argument or `MCP_TRANSPORT` environment variable, with CLI taking precedence. In HTTP mode the server binds to `0.0.0.0:8000`.

## Authentication

HTTP mode supports OAuth 2.0 Client Credentials authentication, opt-in via three environment variables. Auth is disabled when any of the three are absent, which is the correct default for stdio mode and local dev.

### Token flow

1. Claude POSTs `grant_type=client_credentials` + `client_id` + `client_secret` to `/token`.
2. The server validates the credentials and returns a static bearer token.
3. Claude sends `Authorization: Bearer <token>` with every subsequent MCP request.
4. `_StaticTokenVerifier.verify_token()` validates the token; the SDK's `BearerAuthBackend` + `RequireAuthMiddleware` enforce it on the MCP endpoint.

The `/token` route is registered via `@mcp.custom_route` (always public, as required by the OAuth flow). The MCP route at `"/"` is wrapped by `RequireAuthMiddleware` when a `token_verifier` is configured.

Auth credentials (`_client_id`, `_client_secret`, `_access_token_value`) are read from environment variables at import time — no filesystem I/O, safe to import in tests.

## Configuration

| Source | Precedence | Variables / flags |
|---|---|---|
| CLI arguments | Highest | `--transport`, `--db` |
| Environment variables | Middle | `MCP_TRANSPORT`, `INTERESTING_DB_PATH`, `INTERESTING_CLIENT_ID`, `INTERESTING_CLIENT_SECRET`, `INTERESTING_ACCESS_TOKEN`, `INTERESTING_BASE_URL` |
| Defaults | Lowest | `stdio`, `data/interesting.db`, auth disabled |

`_db_path` is `None` at import time and resolved inside `_lifespan` at startup, so importing the module for tests or tooling does not trigger environment variable reads or filesystem access.

Database paths are resolved relative to the `data/` directory; absolute paths are rejected.
