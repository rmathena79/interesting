import logging
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "world"
_ROUNDUP_LIMIT = 6
_SCHEMA_VERSION = 5

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
# "dated" is special: topics are invisible until next_check_at is reached, then eligible once.
_CADENCE_DAYS: dict[str, int | None] = {
    "rare": 14,
    "occasional": 7,
    "regular": 3,
    "frequent": 1,
    "always": None,
    "dated": None,
}
KNOWN_CADENCES: frozenset[str] = frozenset(_CADENCE_DAYS.keys())
DEFAULT_CADENCE = "regular"  # default for new topics
_MIGRATION_CADENCE = "frequent"  # backfill for existing rows in the v4 migration


def _build_cadence_eligibility_clause(cadence_days: dict[str, int | None]) -> str:
    """SQL fragment that selects topics eligible for inclusion in a roundup.

    'dated' topics are eligible only when next_check_at is reached. All other
    cadences use normal rotation rules and gain an extra eligibility window when
    next_check_at is reached (additive, not a replacement).

    last_checked_at and next_check_at are stored as Python isoformat strings
    (e.g. '2026-06-11T16:57:46.495858+00:00'). Wrapping in datetime() normalizes
    them to SQLite's canonical 'YYYY-MM-DD HH:MM:SS' so comparisons are correct;
    without it the 'T' separator causes same-day timestamps to compare wrong.

    days values are f-string-interpolated into the SQL (not bound parameters);
    callers are responsible for ensuring all days values are integers >= 1.
    """
    target_reached = (
        "next_check_at IS NOT NULL AND datetime(next_check_at) <= datetime('now')"
    )
    parts = [
        # dated: only eligible when target date is reached
        f"(cadence = 'dated' AND {target_reached})",
        # always: no cooldown (never has cadence = 'dated', so no guard needed)
        "cadence = 'always'",
        # non-dated unchecked: eligible regardless of cadence
        "(cadence != 'dated' AND last_checked_at IS NULL)",
    ]
    for cadence, days in cadence_days.items():
        if days is None:
            continue  # 'always' and 'dated' are handled above
        clause = (
            f"(cadence = '{cadence}'"
            f" AND datetime(last_checked_at) <= datetime('now', '-{days} days'))"
        )
        parts.append(clause)
    # non-dated: extra eligibility when target date reached (bypasses cadence cooldown)
    parts.append(f"(cadence != 'dated' AND {target_reached})")
    return "(" + " OR ".join(parts) + ")"


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
    next_check_at: str | None

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
            "next_check_at": self.next_check_at,
        }


_TOPIC_COLUMNS = (
    "id, title, scope, added_at, last_checked_at, notes, status, cadence, next_check_at"
)


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
        next_check_at=row[8],
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
        if {"added_at", "last_checked_at", "notes", "status", "cadence", "next_check_at"}.issubset(
            existing_cols
        ):
            version = _SCHEMA_VERSION
        elif {"added_at", "last_checked_at", "notes", "status", "cadence"}.issubset(existing_cols):
            version = 4
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

    if version < 5:
        conn.execute("ALTER TABLE topics ADD COLUMN next_check_at TEXT")
        logger.info("Applied migration 5: added next_check_at column")
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
    next_check_at: str | None = None,
) -> Topic:
    topic_id = str(uuid.uuid4())
    added_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO topics (id, title, scope, added_at, notes, status, cadence, next_check_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (topic_id, title, scope, added_at, notes, _STATUS_ACTIVE, cadence, next_check_at),
    )
    conn.commit()
    logger.info(
        "Added topic id=%s title=%r scope=%r cadence=%r next_check_at=%r",
        topic_id,
        title,
        scope,
        cadence,
        next_check_at,
    )
    return Topic(
        id=topic_id,
        title=title,
        scope=scope,
        added_at=added_at,
        last_checked_at=None,
        notes=notes,
        status=_STATUS_ACTIVE,
        cadence=cadence,
        next_check_at=next_check_at,
    )


def list_topics(
    conn: sqlite3.Connection,
    scope: str | None = None,
    roundup: bool = False,
    include_archived: bool = False,
    roundup_limit: int = _ROUNDUP_LIMIT,
    cadence_days: dict[str, int | None] = _CADENCE_DAYS,
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
        conditions.append(_build_cadence_eligibility_clause(cadence_days))

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    if roundup:
        # Triggered next_check_at topics first (oldest date first), then normal rotation.
        order_limit = (
            f" ORDER BY"
            f" (CASE WHEN next_check_at IS NOT NULL AND datetime(next_check_at) <= datetime('now')"
            f" THEN 0 ELSE 1 END),"
            f" (CASE WHEN next_check_at IS NOT NULL AND datetime(next_check_at) <= datetime('now')"
            f" THEN next_check_at END),"
            f" last_checked_at ASC, RANDOM()"
            f" LIMIT {roundup_limit}"
        )
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
            f"UPDATE topics SET last_checked_at = ?, next_check_at = NULL"
            f" WHERE id IN ({id_placeholders})",
            [now, *ids],
        )
        conn.commit()
        return [_topic_from_row(r)._replace(last_checked_at=now, next_check_at=None) for r in rows]
    return [_topic_from_row(r) for r in rows]


def update_topic(
    conn: sqlite3.Connection,
    topic_id: str,
    title: str | None,
    scope: str | None,
    notes: str | None = None,
    update_notes: bool = False,
    cadence: str | None = None,
    next_check_at: str | None = None,
    update_next_check_at: bool = False,
) -> Topic | None:
    """Update a topic's fields.

    Pass update_notes=True to write the notes value (even if None).
    Pass update_next_check_at=True to write the next_check_at value (even if None, which clears it).
    """
    if (
        title is None
        and scope is None
        and not update_notes
        and cadence is None
        and not update_next_check_at
    ):
        raise ValueError(
            "update_topic: at least one of title, scope, notes, cadence,"
            " or next_check_at must be provided"
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
    if update_next_check_at:
        parts.append("next_check_at = ?")
        params.append(next_check_at)
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
        "Updated topic id=%s title=%r scope=%r notes_updated=%r cadence=%r"
        " next_check_at_updated=%r",
        topic_id,
        title,
        scope,
        update_notes,
        cadence,
        update_next_check_at,
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
