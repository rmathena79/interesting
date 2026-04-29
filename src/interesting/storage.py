import logging
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import NamedTuple

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "world"
_ROUNDUP_LIMIT = 6
_SCHEMA_VERSION = 3

# Maps a requested scope to the set of stored scopes it includes.
# DEFAULT_SCOPE ("world") is not listed — it means no filter (return all topics).
_CONTAINED_SCOPES: dict[str, set[str]] = {
    "us": {"us", "pdx"},
    "pdx": {"pdx"},
}

KNOWN_SCOPES: frozenset[str] = frozenset({DEFAULT_SCOPE} | set(_CONTAINED_SCOPES.keys()))
KNOWN_STATUSES: frozenset[str] = frozenset({"active", "archived"})


def get_scope_hierarchy() -> dict[str, list[str]]:
    """Returns each scope mapped to the stored scopes included when filtering by it."""
    result: dict[str, list[str]] = {DEFAULT_SCOPE: sorted(KNOWN_SCOPES)}
    for scope, included in _CONTAINED_SCOPES.items():
        result[scope] = sorted(included)
    return result


class Topic(NamedTuple):
    id: str
    title: str
    scope: str
    added_at: str | None
    last_checked_at: str | None
    notes: str | None
    status: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "added_at": self.added_at,
            "last_checked_at": self.last_checked_at,
            "notes": self.notes,
            "status": self.status,
        }


def init_db(db_path: str) -> sqlite3.Connection:
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Opening SQLite database at %s", db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topics (
            id    TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            scope TEXT NOT NULL
        )
        """
    )

    row = conn.execute("SELECT version FROM schema_version").fetchone()
    version = row[0] if row else 0
    needs_version_update = row is None

    if version == 0:
        # Detect databases migrated before version tracking was introduced.
        existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(topics)").fetchall()}
        if {"added_at", "last_checked_at", "notes", "status"}.issubset(existing_cols):
            version = _SCHEMA_VERSION
        elif {"added_at", "last_checked_at"}.issubset(existing_cols):
            version = 2

    if version < 1:
        conn.execute("ALTER TABLE topics ADD COLUMN added_at TEXT")
        logger.info("Applied migration 1: added added_at column")
        needs_version_update = True

    if version < 2:
        conn.execute("ALTER TABLE topics ADD COLUMN last_checked_at TEXT")
        logger.info("Applied migration 2: added last_checked_at column")
        needs_version_update = True

    if version < 3:
        conn.execute("ALTER TABLE topics ADD COLUMN notes TEXT")
        conn.execute("ALTER TABLE topics ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        logger.info("Applied migration 3: added notes and status columns")
        needs_version_update = True

    if needs_version_update:
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        logger.info("Schema version set to %d", _SCHEMA_VERSION)

    conn.commit()
    logger.info("Database initialized at %s (schema_version=%d)", db_path, _SCHEMA_VERSION)
    return conn


def add_topic(conn: sqlite3.Connection, title: str, scope: str, notes: str | None = None) -> Topic:
    topic_id = str(uuid.uuid4())
    added_at = datetime.now(timezone.utc).isoformat()
    stored_notes = notes if notes else None
    conn.execute(
        "INSERT INTO topics (id, title, scope, added_at, notes, status)"
        " VALUES (?, ?, ?, ?, ?, 'active')",
        (topic_id, title, scope, added_at, stored_notes),
    )
    conn.commit()
    logger.info("Added topic id=%s title=%r scope=%r", topic_id, title, scope)
    return Topic(
        id=topic_id,
        title=title,
        scope=scope,
        added_at=added_at,
        last_checked_at=None,
        notes=stored_notes,
        status="active",
    )


def list_topics(
    conn: sqlite3.Connection,
    scope: str | None = None,
    roundup: bool = False,
    include_archived: bool = False,
) -> list[Topic]:
    conditions: list[str] = []
    params: list[str] = []

    if scope is not None and scope != DEFAULT_SCOPE:
        included = _CONTAINED_SCOPES.get(scope, {scope})
        placeholders = ",".join("?" * len(included))
        conditions.append(f"scope IN ({placeholders})")
        params.extend(sorted(included))

    if not include_archived:
        conditions.append("status = 'active'")

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    if roundup:
        order_limit = f" ORDER BY last_checked_at ASC, RANDOM() LIMIT {_ROUNDUP_LIMIT}"
    else:
        order_limit = " ORDER BY title"

    rows = conn.execute(
        "SELECT id, title, scope, added_at, last_checked_at, notes, status FROM topics"
        f"{where_clause}{order_limit}",
        params,
    ).fetchall()
    logger.info(
        "Listed %d topics scope=%r roundup=%r include_archived=%r",
        len(rows),
        scope,
        roundup,
        include_archived,
    )

    if roundup and rows:
        now = datetime.now(timezone.utc).isoformat()
        ids = [row[0] for row in rows]
        id_placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE topics SET last_checked_at = ? WHERE id IN ({id_placeholders})",
            [now, *ids],
        )
        conn.commit()
        return [
            Topic(
                id=r[0],
                title=r[1],
                scope=r[2],
                added_at=r[3],
                last_checked_at=now,
                notes=r[5],
                status=r[6],
            )
            for r in rows
        ]
    return [
        Topic(
            id=r[0],
            title=r[1],
            scope=r[2],
            added_at=r[3],
            last_checked_at=r[4],
            notes=r[5],
            status=r[6],
        )
        for r in rows
    ]


def update_topic(
    conn: sqlite3.Connection,
    topic_id: str,
    title: str | None,
    scope: str | None,
    notes: str | None = None,
    update_notes: bool = False,
) -> Topic | None:
    """Update a topic's fields. Pass update_notes=True to write the notes value (even if None)."""
    if title is None and scope is None and not update_notes:
        raise ValueError("update_topic: at least one of title, scope, or notes must be provided")
    parts: list[str] = []
    params: list[str | None] = []
    if title is not None:
        parts.append("title = ?")
        params.append(title)
    if scope is not None:
        parts.append("scope = ?")
        params.append(scope)
    if update_notes:
        parts.append("notes = ?")
        params.append(notes)
    params.append(topic_id)
    cursor = conn.execute(
        f"UPDATE topics SET {', '.join(parts)} WHERE id = ?",
        params,
    )
    conn.commit()
    if cursor.rowcount == 0:
        logger.warning("update_topic: id=%s not found", topic_id)
        return None
    row = conn.execute(
        "SELECT id, title, scope, added_at, last_checked_at, notes, status"
        " FROM topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    logger.info(
        "Updated topic id=%s title=%r scope=%r notes_updated=%r",
        topic_id,
        title,
        scope,
        update_notes,
    )
    return Topic(
        id=row[0],
        title=row[1],
        scope=row[2],
        added_at=row[3],
        last_checked_at=row[4],
        notes=row[5],
        status=row[6],
    )


def archive_topic(conn: sqlite3.Connection, topic_id: str, archived: bool) -> Topic | None:
    status = "archived" if archived else "active"
    cursor = conn.execute("UPDATE topics SET status = ? WHERE id = ?", (status, topic_id))
    conn.commit()
    if cursor.rowcount == 0:
        logger.warning("archive_topic: id=%s not found", topic_id)
        return None
    row = conn.execute(
        "SELECT id, title, scope, added_at, last_checked_at, notes, status"
        " FROM topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    logger.info("archive_topic: id=%s archived=%r", topic_id, archived)
    return Topic(
        id=row[0],
        title=row[1],
        scope=row[2],
        added_at=row[3],
        last_checked_at=row[4],
        notes=row[5],
        status=row[6],
    )


def remove_topic(conn: sqlite3.Connection, topic_id: str) -> bool:
    cursor = conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()
    found = cursor.rowcount > 0
    if found:
        logger.info("Removed topic id=%s", topic_id)
    else:
        logger.warning("remove_topic: id=%s not found", topic_id)
    return found
