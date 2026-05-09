import argparse
import json
import logging
import os
import pathlib
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Literal, cast

from mcp.server.auth.handlers.authorize import construct_redirect_uri
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthClientInformationFull,
    OAuthToken,
    RefreshToken,
)
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from interesting import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_DATA_DIR = "data"
_DEFAULT_DB_NAME = "interesting.db"
_TITLE_MAX = 128
_NOTES_MAX = 512
_ID_MAX = 64
_Transport = Literal["stdio", "streamable-http"]

# --- Auth config (read once at import; no filesystem I/O) ---
_client_id: str = os.environ.get("INTERESTING_CLIENT_ID", "")
_client_secret: str = os.environ.get("INTERESTING_CLIENT_SECRET", "")
_access_token_value: str = os.environ.get("INTERESTING_ACCESS_TOKEN", "")
_auth_enabled: bool = bool(_client_id and _client_secret and _access_token_value)

_CLAUDE_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"
_AUTH_CODE_TTL = 300  # seconds
_AUTH_CODE_BYTES = 32
_TOKEN_TTL = 24 * 60 * 60  # seconds


class _SingleUserOAuthProvider:
    """OAuth 2.0 Authorization Code + PKCE server for a single pre-registered client.

    Auto-approves every authorization request — security relies on network-level access
    control (e.g. Tailscale). In-memory code store is intentionally ephemeral.
    """

    def __init__(self) -> None:
        self._pending_codes: dict[str, AuthorizationCode] = {}

    def _registered_client(self) -> OAuthClientInformationFull:
        return OAuthClientInformationFull(
            client_id=_client_id,
            client_secret=_client_secret,
            redirect_uris=[_CLAUDE_REDIRECT_URI],  # type: ignore[arg-type]
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code"],
            response_types=["code"],
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._registered_client() if client_id == _client_id else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("dynamic client registration is disabled")

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        code = secrets.token_urlsafe(_AUTH_CODE_BYTES)
        self._pending_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + _AUTH_CODE_TTL,
            client_id=client.client_id or "",
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        )
        logger.info("authorize: issued code for client_id=%r", client.client_id)
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        return self._pending_codes.get(authorization_code)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        self._pending_codes.pop(authorization_code.code, None)
        logger.info(
            "exchange_authorization_code: issued access token for client_id=%r", client.client_id
        )
        return OAuthToken(
            access_token=_access_token_value, token_type="Bearer", expires_in=_TOKEN_TTL
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        return None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        raise NotImplementedError("refresh tokens are not supported")

    async def load_access_token(self, token: str) -> AccessToken | None:
        if secrets.compare_digest(token, _access_token_value):
            return AccessToken(token=token, client_id=_client_id, scopes=[])
        return None

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        pass


def _resolve_db_path(name: str) -> str:
    """Resolve a DB name/path to a path under the data/ directory.

    Both forward and backward slashes are treated as path separators so that
    Windows-style paths work on any platform, including when passed through
    JSON configs where backslash escaping may vary. Absolute paths are rejected.
    """
    normalized = name.replace("\\", "/")
    posix_abs = pathlib.PurePosixPath(normalized).is_absolute()
    win_abs = pathlib.PureWindowsPath(normalized).is_absolute()
    if posix_abs or win_abs:
        raise ValueError(
            f"absolute paths are not supported; pass a filename or relative path (got {name!r})"
        )
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
    path = _db_path or _resolve_db_path(os.environ.get("INTERESTING_DB_PATH", _DEFAULT_DB_NAME))
    _conn = storage.init_db(path)
    try:
        yield
    finally:
        _conn.close()
        _conn = None


_DEFAULT_BASE_URL = "http://localhost:8000"
_base_url: str = os.environ.get("INTERESTING_BASE_URL", _DEFAULT_BASE_URL)
_allowed_hosts: list[str] = [
    h.strip()
    for h in os.environ.get("INTERESTING_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]

_auth_kwargs: dict[str, Any] = {}
if _auth_enabled:
    _auth_kwargs = {
        "auth_server_provider": _SingleUserOAuthProvider(),
        "auth": AuthSettings(issuer_url=_base_url, resource_server_url=_base_url),
    }

mcp = FastMCP(
    "interesting",
    lifespan=_lifespan,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(allowed_hosts=_allowed_hosts),
    **_auth_kwargs,
)


def _is_printable_ascii(s: str) -> bool:
    return all(0x20 <= ord(c) <= 0x7E for c in s)


def _validate_field(value: str, field_name: str, max_len: int, *, required: bool = True) -> None:
    if required and (not value or not value.strip()):
        raise ValueError(f"{field_name} must not be empty")
    if not required and value and not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    if len(value) > max_len:
        raise ValueError(f"{field_name} must be {max_len} characters or fewer")
    if not _is_printable_ascii(value):
        raise ValueError(
            f"{field_name} must contain only printable ASCII characters (no control characters)"
        )


def _validate_id(id_value: str) -> None:
    """Validate a topic ID. Server-generated IDs are UUIDs, but the check is permissive
    enough that any reasonable opaque string passes — only obviously malformed input is
    rejected before reaching the DB."""
    _validate_field(id_value, "id", _ID_MAX)


def _validate_title(title: str) -> None:
    _validate_field(title, "title", _TITLE_MAX)


def _validate_scope(scope: str) -> None:
    if scope not in storage.KNOWN_SCOPES:
        raise ValueError(f"unknown scope {scope!r}; call list_scopes for valid options")


def _validate_notes(notes: str) -> None:
    _validate_field(notes, "notes", _NOTES_MAX, required=False)


def _validate_cadence(cadence: str) -> None:
    if cadence not in storage.KNOWN_CADENCES:
        valid = ", ".join(sorted(storage.KNOWN_CADENCES))
        raise ValueError(f"unknown cadence {cadence!r}; valid values: {valid}")


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


@mcp.tool(
    description=(
        "Adds a topic of interest and returns the created entry. "
        "cadence controls how often the topic is eligible for roundup inclusion: "
        "'rare' (~every two weeks), 'occasional' (~weekly), 'regular' (~every three days, "
        "default), 'frequent' (~daily), or 'always' (no minimum interval). "
        "Pick 'frequent' for breaking stories, 'rare' for slow-burn confirmations."
    )
)
def add_topic(title: str, scope: str = "", notes: str = "", cadence: str = "") -> str:
    logger.info("add_topic called title=%r scope=%r cadence=%r", title, scope, cadence)
    _validate_title(title)
    resolved_scope = scope if scope else storage.DEFAULT_SCOPE
    _validate_scope(resolved_scope)
    if notes:
        _validate_notes(notes)
    resolved_cadence = cadence if cadence else storage.DEFAULT_CADENCE
    _validate_cadence(resolved_cadence)
    topic = storage.add_topic(
        _get_conn(),
        title,
        resolved_scope,
        notes if notes else None,
        resolved_cadence,
    )
    return json.dumps(topic.to_dict())


@mcp.tool(
    description=(
        "Returns tracked topics. "
        "Pass scope to filter by geographic containment (pdx is contained in us, us in world); "
        "omit or pass empty string to return all topics regardless of scope. "
        "Set roundup=true when calling as part of a news roundup — the server returns at most "
        "6 topics, prioritizing those least recently checked (null last_checked_at first, then "
        "oldest), with random tiebreaking, and records last_checked_at for each returned topic. "
        "In roundup mode, topics still within their cadence cooldown are excluded before "
        "rotation runs, so the result may contain fewer than 6 topics (or be empty) when "
        "everything tracked has been checked recently; cadence has no effect on non-roundup "
        "listings. "
        "Without roundup=true, all matching topics are returned sorted by title. "
        "By default only active (non-archived) topics are returned; pass include_archived=true "
        "to include archived topics as well. "
        "Use list_scopes to see valid scope values."
    )
)
def list_topics(scope: str = "", roundup: bool = False, include_archived: bool = False) -> str:
    logger.info(
        "list_topics called scope=%r roundup=%r include_archived=%r",
        scope,
        roundup,
        include_archived,
    )
    if scope:
        _validate_scope(scope)
    resolved = scope if scope else None
    topics = storage.list_topics(
        _get_conn(), scope=resolved, roundup=roundup, include_archived=include_archived
    )
    return json.dumps([t.to_dict() for t in topics])


@mcp.tool(description="Removes a topic by ID.")
def remove_topic(id: str) -> str:
    logger.info("remove_topic called id=%r", id)
    _validate_id(id)
    found = storage.remove_topic(_get_conn(), id)
    if not found:
        raise ValueError(f"topic not found: {id}")
    return "OK"


@mcp.tool(
    description=(
        "Updates the title, scope, notes, and/or cadence of an existing topic. "
        "Pass only the fields you want to change; omit or pass empty string to leave unchanged. "
        "At least one of title, scope, notes, or cadence must be provided. "
        "Valid cadence values: 'rare', 'occasional', 'regular', 'frequent', 'always' "
        "(see add_topic for meanings). "
        "The topic ID, added_at, last_checked_at, and status are never changed by this call."
    )
)
def update_topic(
    id: str, title: str = "", scope: str = "", notes: str = "", cadence: str = ""
) -> str:
    logger.info("update_topic called id=%r title=%r scope=%r cadence=%r", id, title, scope, cadence)
    _validate_id(id)
    if not title and not scope and not notes and not cadence:
        raise ValueError("at least one of title, scope, notes, or cadence must be provided")
    new_title: str | None = None
    new_scope: str | None = None
    new_cadence: str | None = None
    if title:
        _validate_title(title)
        new_title = title
    if scope:
        _validate_scope(scope)
        new_scope = scope
    if notes:
        _validate_notes(notes)
    if cadence:
        _validate_cadence(cadence)
        new_cadence = cadence
    topic = storage.update_topic(
        _get_conn(),
        id,
        new_title,
        new_scope,
        notes=notes if notes else None,
        update_notes=bool(notes),
        cadence=new_cadence,
    )
    if topic is None:
        raise ValueError(f"topic not found: {id}")
    return json.dumps(topic.to_dict())


@mcp.tool(
    description=(
        "Archives a topic to remove it from normal rotation without deleting it. "
        "Use when a story has concluded or is no longer relevant. "
        "Pass archived=false to reactivate an archived topic if a story resurfaces. "
        "Archived topics do not appear in list_topics or roundups by default."
    )
)
def archive_topic(id: str, archived: bool = True) -> str:
    logger.info("archive_topic called id=%r archived=%r", id, archived)
    _validate_id(id)
    topic = storage.archive_topic(_get_conn(), id, archived)
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

    transport = cast(_Transport, args.transport or os.environ.get("MCP_TRANSPORT", "stdio"))
    _db_path = _resolve_db_path(args.db or os.environ.get("INTERESTING_DB_PATH", _DEFAULT_DB_NAME))

    logger.info(
        "Starting interesting MCP server with transport=%s db=%s auth=%s",
        transport,
        _db_path,
        "enabled" if _auth_enabled else "disabled",
    )
    if transport == "streamable-http" and not _auth_enabled:
        logger.warning(
            "Running in HTTP mode without auth; set INTERESTING_CLIENT_ID, "
            "INTERESTING_CLIENT_SECRET, and INTERESTING_ACCESS_TOKEN to enable auth"
        )
    try:
        mcp.run(transport=transport)
    except KeyboardInterrupt:
        logger.info("Server stopped")
    except SystemExit as e:
        if e.code not in (0, None):
            raise
