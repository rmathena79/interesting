import os
import pathlib

from mcp.shared.memory import create_connected_server_and_client_session

from interesting import storage
from interesting.server import mcp


async def test_ping_returns_pong() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("ping", {})
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].text == "pong"  # type: ignore[union-attr]


def test_storage_initializes_and_creates_db(tmp_path: pathlib.Path) -> None:
    db_file = tmp_path / "test.db"
    os.environ["INTERESTING_DB_PATH"] = str(db_file)
    try:
        conn = storage.open_connection()
        conn.close()
        assert db_file.exists()
    finally:
        del os.environ["INTERESTING_DB_PATH"]
