import json
import pathlib

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

import interesting.server as server_module
from interesting import storage
from interesting.server import mcp


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = str(tmp_path / "test.db")
    # Set _db_path so the lifespan uses the test DB if it runs during the session.
    monkeypatch.setattr(server_module, "_db_path", db_file)
    # Also initialize directly in case the test harness skips the lifespan.
    storage.init_db(db_file)


async def test_ping_returns_pong() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("ping", {})
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].text == "pong"  # type: ignore[union-attr]


async def test_add_topic_default_scope() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "AI News"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["title"] == "AI News"
    assert data["scope"] == "world"
    assert len(data["id"]) == 36  # UUID format: 8-4-4-4-12


async def test_add_topic_custom_scope() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Local News", "scope": "local"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["scope"] == "local"


async def test_add_topic_empty_scope_uses_default() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "scope": ""})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["scope"] == "world"


async def test_add_topic_empty_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": ""})
    assert result.isError


async def test_add_topic_title_too_long_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "x" * 129})
    assert result.isError


async def test_add_topic_non_ascii_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Café News"})
    assert result.isError


async def test_add_topic_non_ascii_scope_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "News", "scope": "éu"})
    assert result.isError


async def test_add_topic_scope_too_long_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "News", "scope": "s" * 33})
    assert result.isError


async def test_add_topic_returns_unique_ids() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        r1 = await client.call_tool("add_topic", {"title": "Topic A"})
        r2 = await client.call_tool("add_topic", {"title": "Topic B"})
    id1 = json.loads(r1.content[0].text)["id"]  # type: ignore[union-attr]
    id2 = json.loads(r2.content[0].text)["id"]  # type: ignore[union-attr]
    assert id1 != id2


async def test_list_topics_empty() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("list_topics", {})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data == []


async def test_list_topics_returns_all() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Topic A"})
        await client.call_tool("add_topic", {"title": "Topic B", "scope": "local"})
        result = await client.call_tool("list_topics", {})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 2
    titles = {t["title"] for t in data}
    assert titles == {"Topic A", "Topic B"}
    scopes = {t["title"]: t["scope"] for t in data}
    assert scopes["Topic A"] == "world"
    assert scopes["Topic B"] == "local"


async def test_list_topics_includes_id() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Topic A"})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data[0]["id"]) == 36


async def test_remove_topic_success() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "To Remove"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        remove_result = await client.call_tool("remove_topic", {"id": topic_id})
    assert not remove_result.isError
    assert remove_result.content[0].text == "OK"  # type: ignore[union-attr]


async def test_remove_topic_not_found_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": "no-such-id"})
    assert result.isError


async def test_remove_topic_removes_from_list() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Ephemeral"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("remove_topic", {"id": topic_id})
        list_result = await client.call_tool("list_topics", {})
    data = json.loads(list_result.content[0].text)  # type: ignore[union-attr]
    assert data == []


async def test_remove_topic_id_is_case_sensitive() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Case Test"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        # Try to remove with upper-cased ID (UUIDs use lowercase hex)
        result = await client.call_tool("remove_topic", {"id": topic_id.upper()})
    assert result.isError


def test_storage_init_creates_db(tmp_path: pathlib.Path) -> None:
    db_file = tmp_path / "explicit.db"
    storage.init_db(str(db_file))
    assert db_file.exists()
