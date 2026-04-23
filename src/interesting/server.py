import argparse
import json
import logging
import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from interesting import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "interesting",
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
    if len(scope) > 32:
        raise ValueError("scope must be 32 characters or fewer")
    if not scope.isascii():
        raise ValueError("scope must be ASCII only")


@mcp.tool(description="Verify connectivity with the server.")
def ping(ctx: Context) -> str:
    logger.info("ping called")
    ctx.info("ping called")
    return "pong"


@mcp.tool(description="Adds a topic of interest and returns the created entry.")
def add_topic(title: str, scope: str = "") -> str:
    logger.info("add_topic called title=%r scope=%r", title, scope)
    _validate_title(title)
    resolved_scope = scope if scope else storage.DEFAULT_SCOPE
    _validate_scope(resolved_scope)
    topic = storage.add_topic(title, resolved_scope)
    return json.dumps({"id": topic.id, "title": topic.title, "scope": topic.scope})


@mcp.tool(description="Returns all topics.")
def list_topics() -> str:
    logger.info("list_topics called")
    topics = storage.list_topics()
    return json.dumps([{"id": t.id, "title": t.title, "scope": t.scope} for t in topics])


@mcp.tool(description="Removes a topic by ID.")
def remove_topic(id: str) -> str:
    logger.info("remove_topic called id=%r", id)
    if not id:
        raise ValueError("id must not be empty")
    found = storage.remove_topic(id)
    if not found:
        raise ValueError(f"topic not found: {id}")
    return "OK"


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

    transport: str = args.transport or os.environ.get("MCP_TRANSPORT", "stdio")
    db_path: str = args.db or os.environ.get("INTERESTING_DB_PATH", "interesting.db")

    logger.info("Starting interesting MCP server with transport=%s db=%s", transport, db_path)
    storage.init_db(db_path)
    mcp.run(transport=transport)  # type: ignore[arg-type]
