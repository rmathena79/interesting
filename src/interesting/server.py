import argparse
import json
import logging
import os
import pathlib
import sqlite3
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal, cast

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from interesting import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_DATA_DIR = "data"
_Transport = Literal["stdio", "streamable-http"]


def _resolve_db_path(name: str) -> str:
    """Resolve a DB name/path to a path under the data/ directory.

    Both forward and backward slashes are treated as path separators so that
    Windows-style paths work on any platform, including when passed through
    JSON configs where backslash escaping may vary.
    """
    normalized = name.replace("\\", "/")
    return str(pathlib.Path(_DATA_DIR) / normalized)


# Overridden by __main__ before mcp.run(); resolved from env/default in _lifespan if still None.
_db_path: str | None = None
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized; server lifespan has not started")
    return _conn


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    global _conn
    path = _db_path or _resolve_db_path(os.environ.get("INTERESTING_DB_PATH", "interesting.db"))
    _conn = storage.init_db(path)
    try:
        yield
    finally:
        _conn.close()
        _conn = None


mcp = FastMCP(
    "interesting",
    lifespan=_lifespan,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=["soliboy.tail52f9f8.ts.net", "localhost", "127.0.0.1"]
    ),
)


def _validate_title(title: str) -> None:
    if not title:
        raise ValueError("title must not be empty")
    if len(title) > 128:
        raise ValueError("title must be 128 characters or fewer")
    if not title.isascii():
        raise ValueError("title must be ASCII only")


def _validate_scope(scope: str) -> None:
    if scope not in storage.KNOWN_SCOPES:
        raise ValueError(f"unknown scope {scope!r}; call list_scopes for valid options")


@mcp.tool(
    description=(
        "Returns the valid scopes and their containment relationships. "
        "Call this to discover which scope values are accepted by add_topic, update_topic, "
        "and list_topics."
    )
)
def list_scopes() -> str:
    logger.info("list_scopes called")
    return json.dumps(
        {
            "scopes": sorted(storage.KNOWN_SCOPES),
            "default": storage.DEFAULT_SCOPE,
            "containment": storage.get_scope_hierarchy(),
        }
    )


_REFERENCE_DOC = pathlib.Path(__file__).parents[2] / "interesting-mcp-reference.md"


@mcp.resource("interesting://instructions")
def get_instructions() -> str:
    logger.info("get_instructions resource read")
    return _REFERENCE_DOC.read_text(encoding="utf-8")


@mcp.tool(
    description=(
        "Returns usage instructions for this MCP server: tool reference, scope semantics, "
        "title conventions, and operational workflows. Call this at the start of a session "
        "before using any other tools."
    )
)
def get_instructions_tool() -> str:
    logger.info("get_instructions_tool called")
    return _REFERENCE_DOC.read_text(encoding="utf-8")


@mcp.tool(description="Adds a topic of interest and returns the created entry.")
def add_topic(title: str, scope: str = "") -> str:
    logger.info("add_topic called title=%r scope=%r", title, scope)
    _validate_title(title)
    resolved_scope = scope if scope else storage.DEFAULT_SCOPE
    _validate_scope(resolved_scope)
    topic = storage.add_topic(_get_conn(), title, resolved_scope)
    return json.dumps(topic.to_dict())


@mcp.tool(
    description=(
        "Returns tracked topics. "
        "Pass scope to filter by geographic containment (pdx is contained in us, us in world); "
        "omit or pass empty string to return all topics regardless of scope. "
        "Set roundup=true when calling as part of a news roundup — the server returns at most "
        "6 topics, prioritizing those least recently checked (null last_checked_at first, then "
        "oldest), with random tiebreaking, and records last_checked_at for each returned topic. "
        "Without roundup=true, all matching topics are returned sorted by title. "
        "Use list_scopes to see valid scope values."
    )
)
def list_topics(scope: str = "", roundup: bool = False) -> str:
    logger.info("list_topics called scope=%r roundup=%r", scope, roundup)
    if scope:
        _validate_scope(scope)
    resolved = scope if scope else None
    topics = storage.list_topics(_get_conn(), scope=resolved, roundup=roundup)
    return json.dumps([t.to_dict() for t in topics])


@mcp.tool(description="Removes a topic by ID.")
def remove_topic(id: str) -> str:
    logger.info("remove_topic called id=%r", id)
    if not id:
        raise ValueError("id must not be empty")
    found = storage.remove_topic(_get_conn(), id)
    if not found:
        raise ValueError(f"topic not found: {id}")
    return "OK"


@mcp.tool(
    description=(
        "Updates the title and/or scope of an existing topic. "
        "Pass only the fields you want to change; omit or pass empty string to leave unchanged. "
        "At least one of title or scope must be provided. "
        "The topic ID, added_at, and last_checked_at are never changed by this call."
    )
)
def update_topic(id: str, title: str = "", scope: str = "") -> str:
    logger.info("update_topic called id=%r title=%r scope=%r", id, title, scope)
    if not id:
        raise ValueError("id must not be empty")
    if not title and not scope:
        raise ValueError("at least one of title or scope must be provided")
    new_title: str | None = None
    new_scope: str | None = None
    if title:
        _validate_title(title)
        new_title = title
    if scope:
        _validate_scope(scope)
        new_scope = scope
    topic = storage.update_topic(_get_conn(), id, new_title, new_scope)
    if topic is None:
        raise ValueError(f"topic not found: {id}")
    return json.dumps(topic.to_dict())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="interesting MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Transport to use (overrides MCP_TRANSPORT env var)",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to the SQLite database file (overrides INTERESTING_DB_PATH env var)",
    )
    args = parser.parse_args()

    transport = cast(
        _Transport, args.transport or os.environ.get("MCP_TRANSPORT", "stdio")
    )
    _db_path = _resolve_db_path(args.db or os.environ.get("INTERESTING_DB_PATH", "interesting.db"))

    logger.info("Starting interesting MCP server with transport=%s db=%s", transport, _db_path)
    mcp.run(transport=transport)
