import logging
import sqlite3
import uuid
from typing import NamedTuple

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "world"

_conn: sqlite3.Connection | None = None


class Topic(NamedTuple):
    id: str
    title: str
    scope: str


def init_db(db_path: str) -> None:
    global _conn
    if _conn is not None:
        _conn.close()
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
    _conn.commit()
    logger.info("Database initialized at %s", db_path)


def _get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("Database not initialized; call init_db() first")
    return _conn


def add_topic(title: str, scope: str) -> Topic:
    topic_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute(
        "INSERT INTO topics (id, title, scope) VALUES (?, ?, ?)",
        (topic_id, title, scope),
    )
    conn.commit()
    logger.info("Added topic id=%s title=%r scope=%r", topic_id, title, scope)
    return Topic(id=topic_id, title=title, scope=scope)


def list_topics() -> list[Topic]:
    conn = _get_conn()
    rows = conn.execute("SELECT id, title, scope FROM topics ORDER BY title").fetchall()
    logger.info("Listed %d topics", len(rows))
    return [Topic(id=row[0], title=row[1], scope=row[2]) for row in rows]


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
