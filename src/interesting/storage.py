import logging
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "world"
_ROUNDUP_LIMIT = 6
_SCHEMA_VERSION = 4

# Maps a requested scope to the set of stored scopes it includes.
# DEFAULT_SCOPE ("world") is not listed -- it means no filter (return all topics).
_CONTAINED_SCOPES: dict[str, set[str]] = {
    "us": {"us", "pdx"},
    "pdx": {"pdx"},
}

KNOWN_SCOPES: frozenset[str] = frozenset({DEFAULT_SCOPE} | set(_CONTAINED_SCOPES.keys()))
_STATUS_ACTIVE = "active"
_STATUS_ARCHIVED = "archived"

# Cadence: minimum days between roundup inclusions for a topic. None means "no minimum".
_CADENCE_DAYS: dict[str, int | None] = {
    "rare": 14,
    "occasional": 7,
    "regular": 3,
    "frequent": 1,
    "always": None,
}
KNOWN_CADENCES: frozenset[str] = frozenset(_CADENCE_DAYS.keys())
DEFAULT_CADENCE = "regular"  # default for new topics
_MIGRATION_CADENCE = "frequent"  # backfill for existing rows in the v4 migration


def _build_cadence_eligibility_clause() -> str:
    """SQL fragment that selects topics eligible for inclusion in a roundup.

    A topic is eligible if its cadence is 'always', if it has never been checked
    (last_checked_at IS NULL), or if its last check was at least the cadence's
    minimum-interval days ago.

    last_checked_at is stored as a Python isoformat string (e.g.
    '2026-06-11T16:57:46.495858+00:00'), which differs from SQLite's canonical
    'YYYY-MM-DD HH:MM:SS' produced by datetime('now', ...). Wrapping the column
    in datetime() normalizes both sides to the same format so the comparison is
    correct; without it the 'T' separator causes same-day checks to appear
    ineligible.
    """
    parts = ["cadence = 'always'", "last_checked_at IS NULL"]
    for cadence, days in _CADENCE_DAYS.items():
        if days is None:
            continue
        clause = (
            f"(cadence = '{cadence}'"
            f" AND datetime(last_checked_at) <= datetime('now', '-{days} days'))"
        )
        parts.append(clause)
    return "(" + " OR ".join(parts) + ")"


_CADENCE_ELIGIBILITY_CLAUSE = _build_cadence_eligibility_clause()


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
    cadence: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "added_at": self.added_at,
            "last_checked_at": self.last_checked_at,
            "notes": self.notes,
            "status": self.status,
            "cadence": self.cadence,
        }


_TOPIC_COLUMNS = "id, title, scope, added_at, last_checked_at, notes, status, cadence"


def _topic_from_row(row: tuple[Any, ...]) -> Topic:
    return Topic(
        id=row[0],
        title=row[1],
        scope=row[2],
        added_at=row[3],
        last_checked_at=row[4],
        notes=row[5],
        status=row[6],
        cadence=row[7],
    )


def _fetch_topic(conn: sqlite3.Connection, topic_id: str) -> Topic | None:
    row = conn.execute(
        f"SELECT {_TOPIC_COLUMNS} FROM topics WHERE id = ?",
        (topic_id,),
    ).fetchone()
    return _topic_from_row(row) if row is not None else None


def init_db(db_path: str) -> sqlite3.Connection:
    db_file = pathlib.Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    is_existing = db_file.exists() and db_file.stat().st_size > 0
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
    needs_version_update = row is None  # legacy detection may skip all migration blocks

    if version == 0:
        # Detect databases migrated before version tracking was introduced.
        existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(topics)").fetchall()}
        if {"added_at", "last_checked_at", "notes", "status", "cadence"}.issubset(existing_cols):
            version = _SCHEMA_VERSION
        elif {"added_at", "last_checked_at", "notes", "status"}.issubset(existing_cols):
            version = 3
        elif {"added_at", "last_checked_at"}.issubset(existing_cols):
            version = 2

    if version < _SCHEMA_VERSION and is_existing:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = f"{db_path}.pre-migration-v{version}-{ts}.db"
        try:
            conn.execute(f"VACUUM INTO '{backup_path}'")
        except Exception as exc:
            raise RuntimeError(
                f"pre-migration backup failed (target: {backup_path!r}): {exc}"
            ) from exc
        logger.info("Created pre-migration backup at %s", backup_path)

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

    if version < 4:
        conn.execute(
            f"ALTER TABLE topics ADD COLUMN cadence TEXT NOT NULL DEFAULT '{_MIGRATION_CADENCE}'"
        )
        logger.info(
            "Applied migration 4: added cadence column (existing rows default to %r)",
            _MIGRATION_CADENCE,
        )
        needs_version_update = True

    if needs_version_update:
        conn.execute("DELETE FROM schema_version")
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        logger.info("Schema version set to %d", _SCHEMA_VERSION)

    conn.commit()
    logger.info("Database initialized at %s (schema_version=%d)", db_path, _SCHEMA_VERSION)
    return conn


def add_topic(
    conn: sqlite3.Connection,
    title: str,
    scope: str,
    notes: str | None = None,
    cadence: str = DEFAULT_CADENCE,
) -> Topic:
    topic_id = str(uuid.uuid4())
    added_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO topics (id, title, scope, added_at, notes, status, cadence)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (topic_id, title, scope, added_at, notes, _STATUS_ACTIVE, cadence),
    )
    conn.commit()
    logger.info("Added topic id=%s title=%r scope=%r cadence=%r", topic_id, title, scope, cadence)
    return Topic(
        id=topic_id,
        title=title,
        scope=scope,
        added_at=added_at,
        last_checked_at=None,
        notes=notes,
        status=_STATUS_ACTIVE,
        cadence=cadence,
    )


def list_topics(
    conn: sqlite3.Connection,
    scope: str | None = None,
    roundup: bool = False,
    include_archived: bool = False,
    roundup_limit: int = _ROUNDUP_LIMIT,
) -> list[Topic]:
    conditions: list[str] = []
    params: list[str] = []

    if scope is not None and scope != DEFAULT_SCOPE:
        included = _CONTAINED_SCOPES.get(scope, {scope})
        placeholders = ",".join("?" * len(included))
        conditions.append(f"scope IN ({placeholders})")
        params.extend(sorted(included))

    if not include_archived:
        conditions.append("status = ?")
        params.append(_STATUS_ACTIVE)

    if roundup:
        # Filter out topics still within their cadence cooldown before rotation runs.
        conditions.append(_CADENCE_ELIGIBILITY_CLAUSE)

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    if roundup:
        order_limit = f" ORDER BY last_checked_at ASC, RANDOM() LIMIT {roundup_limit}"
    else:
        order_limit = " ORDER BY title"

    rows = conn.execute(
        f"SELECT {_TOPIC_COLUMNS} FROM topics{where_clause}{order_limit}",
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
        return [_topic_from_row(r)._replace(last_checked_at=now) for r in rows]
    return [_topic_from_row(r) for r in rows]


def update_topic(
    conn: sqlite3.Connection,
    topic_id: str,
    title: str | None,
    scope: str | None,
    notes: str | None = None,
    update_notes: bool = False,
    cadence: str | None = None,
) -> Topic | None:
    """Update a topic's fields. Pass update_notes=True to write the notes value (even if None)."""
    if title is None and scope is None and not update_notes and cadence is None:
        raise ValueError(
            "update_topic: at least one of title, scope, notes, or cadence must be provided"
        )
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
    if cadence is not None:
        parts.append("cadence = ?")
        params.append(cadence)
    params.append(topic_id)
    cursor = conn.execute(
        f"UPDATE topics SET {', '.join(parts)} WHERE id = ?",
        params,
    )
    conn.commit()
    if cursor.rowcount == 0:
        logger.warning("update_topic: id=%s not found", topic_id)
        return None
    logger.info(
        "Updated topic id=%s title=%r scope=%r notes_updated=%r cadence=%r",
        topic_id,
        title,
        scope,
        update_notes,
        cadence,
    )
    return _fetch_topic(conn, topic_id)


def archive_topic(conn: sqlite3.Connection, topic_id: str, archived: bool) -> Topic | None:
    status = _STATUS_ARCHIVED if archived else _STATUS_ACTIVE
    cursor = conn.execute("UPDATE topics SET status = ? WHERE id = ?", (status, topic_id))
    conn.commit()
    if cursor.rowcount == 0:
        logger.warning("archive_topic: id=%s not found", topic_id)
        return None
    logger.info("archive_topic: id=%s archived=%r", topic_id, archived)
    return _fetch_topic(conn, topic_id)


def remove_topic(conn: sqlite3.Connection, topic_id: str) -> bool:
    cursor = conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()
    found = cursor.rowcount > 0
    if found:
        logger.info("Removed topic id=%s", topic_id)
    else:
        logger.warning("remove_topic: id=%s not found", topic_id)
    return found
