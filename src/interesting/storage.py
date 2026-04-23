import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "interesting.db"


def get_db_path() -> str:
    return os.environ.get("INTERESTING_DB_PATH", _DEFAULT_DB_PATH)


def open_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    logger.info("Opening SQLite database at %s", db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    logger.info("Database connection established")
    return conn
