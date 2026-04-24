import logging
import pathlib
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import NamedTuple

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "world"

# Maps a requested scope to the set of stored scopes it includes.
# DEFAULT_SCOPE ("world") is not listed — it means no filter (return all topics).
_CONTAINED_SCOPES: dict[str, set[str]] = {
    "us": {"us", "pdx"},
    "pdx": {"pdx"},
}

_conn: sqlite3.Connection | None = None


class Topic(NamedTuple):
    id: str
    title: str
    scope: str
    added_at: str | None
    last_checked_at: str | None


def init_db(db_path: str) -> None:
    global _conn
    if _conn is not None:
        _conn.close()
    pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    logger.info("Opening SQLite database at %s", db_path)
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topics (
            id    TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            scope TEXT NOT NULL
        )
        """
    )
    existing = {row[1] for row in _conn.execute("PRAGMA table_info(topics)").fetchall()}
    if "added_at" not in existing:
        _conn.execute("ALTER TABLE topics ADD COLUMN added_at TEXT")
    if "last_checked_at" not in existing:
        _conn.execute("ALTER TABLE topics ADD COLUMN last_checked_at TEXT")
    _conn.commit()
    logger.info("Database initialized at %s", db_path)


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized; call init_db() first")
    return _conn


def add_topic(title: str, scope: str) -> Topic:
    topic_id = str(uuid.uuid4())
    added_at = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO topics (id, title, scope, added_at) VALUES (?, ?, ?, ?)",
        (topic_id, title, scope, added_at),
    )
    conn.commit()
    logger.info("Added topic id=%s title=%r scope=%r", topic_id, title, scope)
    return Topic(id=topic_id, title=title, scope=scope, added_at=added_at, last_checked_at=None)


def list_topics(scope: str | None = None, for_update: bool = False) -> list[Topic]:
    conn = _get_conn()
    if scope is None or scope == DEFAULT_SCOPE:
        rows = conn.execute(
            "SELECT id, title, scope, added_at, last_checked_at FROM topics ORDER BY title"
        ).fetchall()
    else:
        included = _CONTAINED_SCOPES.get(scope, {scope})
        placeholders = ",".join("?" * len(included))
        rows = conn.execute(
            f"SELECT id, title, scope, added_at, last_checked_at FROM topics"
            f" WHERE scope IN ({placeholders}) ORDER BY title",
            tuple(included),
        ).fetchall()
    logger.info("Listed %d topics scope=%r for_update=%r", len(rows), scope, for_update)
    if for_update and rows:
        now = datetime.now(timezone.utc).isoformat()
        ids = [row[0] for row in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE topics SET last_checked_at = ? WHERE id IN ({placeholders})",
            [now, *ids],
        )
        conn.commit()
        return [
            Topic(id=r[0], title=r[1], scope=r[2], added_at=r[3], last_checked_at=now) for r in rows
        ]
    return [
        Topic(id=r[0], title=r[1], scope=r[2], added_at=r[3], last_checked_at=r[4]) for r in rows
    ]


def remove_topic(topic_id: str) -> bool:
    conn = _get_conn()
    cursor = conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    conn.commit()
    found = cursor.rowcount > 0
    if found:
        logger.info("Removed topic id=%s", topic_id)
    else:
        logger.warning("remove_topic: id=%s not found", topic_id)
    return found
