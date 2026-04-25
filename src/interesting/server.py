import argparse
import json
import logging
import os
import pathlib
from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from interesting import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_DATA_DIR = "data"


def _resolve_db_path(name: str) -> str:
    """Resolve a DB name/path to a path under the data/ directory.

    Both forward and backward slashes are treated as path separators so that
    Windows-style paths work on any platform, including when passed through
    JSON configs where backslash escaping may vary.
    """
    normalized = name.replace("\\", "/")
    return str(pathlib.Path(_DATA_DIR) / normalized)


# Set before mcp.run(); overridden in __main__ when --db or INTERESTING_DB_PATH is provided.
_db_path: str = _resolve_db_path(os.environ.get("INTERESTING_DB_PATH", "interesting.db"))


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[None]:
    storage.init_db(_db_path)
    yield


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
    if len(scope) > 32:
        raise ValueError("scope must be 32 characters or fewer")
    if not scope.isascii():
        raise ValueError("scope must be ASCII only")


_INSTRUCTIONS = """\
interesting MCP Server — Usage Instructions

OVERVIEW
The interesting server provides persistent, cross-session tracking of news topics.
Use it to record stories the user wants to follow and to drive news roundups.

TOOLS

`add_topic(title, scope="")`
  Returns: {"id": "...", "title": "...", "scope": "...", "added_at": "..."}
  - `title` (required): ASCII only, non-empty, max 128 characters. Must name the
    specific story or event — not a subject area, person, or vague description.
  - `scope` (optional): ASCII only, max 32 characters. Defaults to "world". Pick
    the narrowest known scope that contains the story.
  After adding, confirm the scope to the user so they can correct it. Do not
  surface the UUID unless asked.

`list_topics(scope="", roundup=False)`
  Returns: JSON array of {id, title, scope, added_at, last_checked_at}
  - `scope`: filters by containment hierarchy (see SCOPE HIERARCHY). Omit or pass
    empty string to return all topics regardless of scope.
  - `roundup`: set to true when calling as part of a news roundup; the server
    records `last_checked_at` for each returned topic.
  - `last_checked_at`: ISO 8601 UTC timestamp of the last roundup=true call that
    included this topic. Records when the topic was last queried in a roundup —
    NOT whether new information was found. A recent timestamp does not mean the
    topic is fully up to date.
  - `added_at`: ISO 8601 UTC timestamp set when the topic was added; null for
    topics added before this field existed.

`update_topic(id, title="", scope="")`
  Returns: {id, title, scope, added_at, last_checked_at} reflecting updated state.
  - At least one of `title` or `scope` must be provided.
  - `added_at` and `last_checked_at` are never modified by this call.
  - Same format rules as `add_topic` apply to title and scope.

`remove_topic(id)`
  Returns: "OK" on success. Error if the ID is not found.
  - To remove by user description, call `list_topics` first to find the match.
  - If multiple topics could match, ask the user which to remove rather than
    guessing. If none match, say so — do not invent an ID.

SCOPE HIERARCHY

Scopes form a containment tree. Narrower scopes are contained within broader ones:

    world   -> everything (international, cross-border)
      us    -> United States
        pdx -> Portland, Oregon

Filtering rule — when listing for a requested scope, include topics whose stored
scope equals the request OR is contained within it:
    request "pdx"   -> include: pdx
    request "us"    -> include: us, pdx
    request "world" -> include: world, us, pdx

When choosing scope for a new topic, pick the narrowest that fits. A Portland city
council vote is "pdx", a federal subpoena is "us", a foreign conflict is "world".
Scope strings are stored verbatim; spelling and case must be consistent ("US" and
"us" will not match — prefer lowercase). If unsure, default to "world" and let the
user correct it.

TITLE CONVENTIONS

A topic title must be distinctive and useful as an LLM search query.

Good:
  "Bondi subpoenaed about Epstein files"
  "Warhammer 40K 11th edition release"
  "OpenAI vs NYT copyright lawsuit"

Bad:
  "Politics"            (subject area, not a story)
  "Trump"               (person, not a story)
  "NYT article on AI"   (single article, not an ongoing story)
  "that crypto thing"   (not searchable)

Include distinctive nouns, entities, or events. Vague phrasing degrades results.

OPERATIONAL MODES

Topic Tracking
  Map natural language to tools:
  - "track X" / "follow up on X" / "keep an eye on X"  -> add_topic
  - "what am I tracking?" / "show my topics"            -> list_topics (no args)
  - "stop tracking X" / "drop X" / "remove X"          -> remove_topic
    (call list_topics first to resolve the ID; ask if ambiguous)

News Roundup
  Trigger: "news [scope] [timeframe]"  (defaults: scope=us, timeframe=48h)

  Workflow:
  1. Call list_topics(scope=<requested_scope>, roundup=True) to get topics filtered
     by the containment hierarchy. The server records last_checked_at for each.
  2. Search for new developments on each returned topic within the timeframe.
  3. For topics with no significant new development, skip rather than re-summarizing.
  4. For topics with material updates, present the update and context — not a recap.
  5. Search for additional stories matching the requested scope and user interests.
  6. Use the `recent_chats` tool (if available) to avoid re-presenting old stories.

  The tracked topic list is the source of truth for follow-up stories. Do not rely
  on conversation memory alone to reconstruct what the user cares about.

NOTES
  - IDs are server-generated UUIDs. Always copy them from tool output; never
    construct or guess one.
  - An empty topic list is valid. Do not fabricate entries.
  - If a call fails unexpectedly, report the error to the user rather than retrying
    silently or substituting a different action.
"""


@mcp.resource("interesting://instructions")
def get_instructions() -> str:
    logger.info("get_instructions resource read")
    return _INSTRUCTIONS


@mcp.tool(description="Adds a topic of interest and returns the created entry.")
def add_topic(title: str, scope: str = "") -> str:
    logger.info("add_topic called title=%r scope=%r", title, scope)
    _validate_title(title)
    resolved_scope = scope if scope else storage.DEFAULT_SCOPE
    _validate_scope(resolved_scope)
    topic = storage.add_topic(title, resolved_scope)
    return json.dumps(
        {"id": topic.id, "title": topic.title, "scope": topic.scope, "added_at": topic.added_at}
    )


@mcp.tool(
    description=(
        "Returns tracked topics. "
        "Pass scope to filter by geographic containment (pdx is contained in us, us in world); "
        "omit or pass empty string to return all topics regardless of scope. "
        "Set roundup=true when calling as part of a news roundup — the server will record "
        "last_checked_at for each returned topic."
    )
)
def list_topics(scope: str = "", roundup: bool = False) -> str:
    logger.info("list_topics called scope=%r roundup=%r", scope, roundup)
    resolved = scope if scope else None
    topics = storage.list_topics(scope=resolved, roundup=roundup)
    return json.dumps(
        [
            {
                "id": t.id,
                "title": t.title,
                "scope": t.scope,
                "added_at": t.added_at,
                "last_checked_at": t.last_checked_at,
            }
            for t in topics
        ]
    )


@mcp.tool(description="Removes a topic by ID.")
def remove_topic(id: str) -> str:
    logger.info("remove_topic called id=%r", id)
    if not id:
        raise ValueError("id must not be empty")
    found = storage.remove_topic(id)
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
    topic = storage.update_topic(id, new_title, new_scope)
    if topic is None:
        raise ValueError(f"topic not found: {id}")
    return json.dumps(
        {
            "id": topic.id,
            "title": topic.title,
            "scope": topic.scope,
            "added_at": topic.added_at,
            "last_checked_at": topic.last_checked_at,
        }
    )


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
    _db_path = _resolve_db_path(args.db or os.environ.get("INTERESTING_DB_PATH", "interesting.db"))

    logger.info("Starting interesting MCP server with transport=%s db=%s", transport, _db_path)
    mcp.run(transport=transport)  # type: ignore[arg-type]
