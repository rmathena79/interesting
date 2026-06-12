import json
import pathlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

import interesting.server as server_module
from interesting import storage
from interesting.server import mcp


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(server_module, "_db_path", db_file)
    return db_file


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
        result = await client.call_tool("add_topic", {"title": "Local News", "scope": "pdx"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["scope"] == "pdx"


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


async def test_add_topic_title_max_length_succeeds() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "x" * 128})
    assert not result.isError


async def test_add_topic_non_ascii_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Café News"})
    assert result.isError


async def test_add_topic_non_ascii_scope_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "News", "scope": "éu"})
    assert result.isError


async def test_add_topic_whitespace_only_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "   "})
    assert result.isError


async def test_add_topic_control_char_in_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "AI\nNews"})
    assert result.isError


async def test_add_topic_tab_in_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "AI\tNews"})
    assert result.isError


async def test_add_topic_null_byte_in_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "AI\x00News"})
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
        await client.call_tool("add_topic", {"title": "Topic B", "scope": "us"})
        result = await client.call_tool("list_topics", {})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 2
    titles = {t["title"] for t in data}
    assert titles == {"Topic A", "Topic B"}
    scopes = {t["title"]: t["scope"] for t in data}
    assert scopes["Topic A"] == "world"
    assert scopes["Topic B"] == "us"


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


async def test_remove_topic_empty_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": ""})
    assert result.isError


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


# --- ID sanitization tests (apply to remove_topic, update_topic, archive_topic) ---


async def test_remove_topic_whitespace_only_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": "   "})
    assert result.isError


async def test_remove_topic_control_char_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": "abc\nxyz"})
    assert result.isError


async def test_remove_topic_null_byte_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": "abc\x00xyz"})
    assert result.isError


async def test_remove_topic_non_ascii_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": "café-id"})
    assert result.isError


async def test_remove_topic_too_long_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("remove_topic", {"id": "a" * 65})
    assert result.isError


async def test_update_topic_whitespace_only_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("update_topic", {"id": "   ", "title": "X"})
    assert result.isError


async def test_update_topic_control_char_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("update_topic", {"id": "abc\tdef", "title": "X"})
    assert result.isError


async def test_update_topic_non_ascii_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("update_topic", {"id": "café-id", "title": "X"})
    assert result.isError


async def test_update_topic_too_long_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("update_topic", {"id": "a" * 65, "title": "X"})
    assert result.isError


async def test_archive_topic_whitespace_only_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("archive_topic", {"id": "   "})
    assert result.isError


async def test_archive_topic_control_char_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("archive_topic", {"id": "abc\rdef"})
    assert result.isError


async def test_archive_topic_non_ascii_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("archive_topic", {"id": "café-id"})
    assert result.isError


async def test_archive_topic_too_long_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("archive_topic", {"id": "a" * 65})
    assert result.isError


def test_storage_init_creates_db(tmp_path: pathlib.Path) -> None:
    db_file = tmp_path / "explicit.db"
    conn = storage.init_db(str(db_file))
    conn.close()
    assert db_file.exists()


# --- Timestamp tests ---


async def test_add_topic_returns_added_at() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Timestamped"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["added_at"] is not None
    assert isinstance(data["added_at"], str)


async def test_list_topics_includes_timestamps() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Topic A"})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["added_at"] is not None
    assert data[0]["last_checked_at"] is None


async def test_list_topics_roundup_sets_last_checked() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Topic A"})
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["last_checked_at"] is not None


async def test_list_topics_no_roundup_leaves_last_checked_null() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Topic A"})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["last_checked_at"] is None


# --- Scope filtering tests ---


async def test_list_topics_scope_exact() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "PDX Story", "scope": "pdx"})
        await client.call_tool("add_topic", {"title": "US Story", "scope": "us"})
        await client.call_tool("add_topic", {"title": "World Story", "scope": "world"})
        result = await client.call_tool("list_topics", {"scope": "pdx"})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["title"] == "PDX Story"


async def test_list_topics_scope_containment_us() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "PDX Story", "scope": "pdx"})
        await client.call_tool("add_topic", {"title": "US Story", "scope": "us"})
        await client.call_tool("add_topic", {"title": "World Story", "scope": "world"})
        result = await client.call_tool("list_topics", {"scope": "us"})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    titles = {t["title"] for t in data}
    assert titles == {"PDX Story", "US Story"}


async def test_list_topics_scope_world_returns_all() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "PDX Story", "scope": "pdx"})
        await client.call_tool("add_topic", {"title": "US Story", "scope": "us"})
        await client.call_tool("add_topic", {"title": "World Story", "scope": "world"})
        result = await client.call_tool("list_topics", {"scope": "world"})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 3


async def test_list_topics_no_scope_returns_all() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "PDX Story", "scope": "pdx"})
        await client.call_tool("add_topic", {"title": "US Story", "scope": "us"})
        await client.call_tool("add_topic", {"title": "World Story", "scope": "world"})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 3


async def test_list_topics_roundup_with_scope_only_updates_filtered() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "PDX Story", "scope": "pdx"})
        await client.call_tool("add_topic", {"title": "US Story", "scope": "us"})
        await client.call_tool("list_topics", {"scope": "pdx", "roundup": True})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    by_title = {t["title"]: t for t in data}
    assert by_title["PDX Story"]["last_checked_at"] is not None
    assert by_title["US Story"]["last_checked_at"] is None


# --- Rotation / limit tests ---


async def test_roundup_returns_at_most_limit() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        for i in range(8):
            await client.call_tool("add_topic", {"title": f"Topic {i:02d}"})
        result = await client.call_tool("list_topics", {"roundup": True})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 6


async def test_non_roundup_returns_all_when_over_limit() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        for i in range(8):
            await client.call_tool("add_topic", {"title": f"Topic {i:02d}"})
        result = await client.call_tool("list_topics", {})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 8


async def test_roundup_unchecked_topics_returned_before_checked() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        for i in range(8):
            await client.call_tool("add_topic", {"title": f"Topic {i:02d}"})
        # First roundup checks 6 topics; 2 remain unchecked.
        await client.call_tool("list_topics", {"roundup": True})
        all_result = await client.call_tool("list_topics", {})
        all_topics = json.loads(all_result.content[0].text)  # type: ignore[union-attr]
        unchecked_ids = {t["id"] for t in all_topics if t["last_checked_at"] is None}
        assert len(unchecked_ids) == 2
        # Second roundup must include both unchecked topics.
        second_result = await client.call_tool("list_topics", {"roundup": True})
    second_data = json.loads(second_result.content[0].text)  # type: ignore[union-attr]
    returned_ids = {t["id"] for t in second_data}
    assert unchecked_ids.issubset(returned_ids)


async def test_roundup_under_limit_returns_all() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        for i in range(4):
            await client.call_tool("add_topic", {"title": f"Topic {i:02d}"})
        result = await client.call_tool("list_topics", {"roundup": True})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 4


# --- update_topic tests ---


async def test_update_topic_title() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Old Title", "scope": "us"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "title": "New Title"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["title"] == "New Title"
    assert data["scope"] == "us"
    assert data["id"] == topic_id


async def test_update_topic_scope() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic", "scope": "us"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "scope": "pdx"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["scope"] == "pdx"
    assert data["title"] == "My Topic"
    assert data["id"] == topic_id


async def test_update_topic_both() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Old Title", "scope": "us"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool(
            "update_topic", {"id": topic_id, "title": "New Title", "scope": "pdx"}
        )
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["title"] == "New Title"
    assert data["scope"] == "pdx"


async def test_update_topic_preserves_timestamps() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic", "scope": "us"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        added_at = json.loads(add_result.content[0].text)["added_at"]  # type: ignore[union-attr]
        await client.call_tool("list_topics", {"roundup": True})
        list_result = await client.call_tool("list_topics", {})
        last_checked = json.loads(list_result.content[0].text)[0]["last_checked_at"]  # type: ignore[union-attr]
        await client.call_tool("update_topic", {"id": topic_id, "title": "Updated Title"})
        final_result = await client.call_tool("list_topics", {})
    data = json.loads(final_result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["added_at"] == added_at
    assert data[0]["last_checked_at"] == last_checked


async def test_update_topic_reflected_in_list() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Old Title", "scope": "us"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("update_topic", {"id": topic_id, "title": "New Title"})
        list_result = await client.call_tool("list_topics", {})
    data = json.loads(list_result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["title"] == "New Title"


async def test_update_topic_not_found_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("update_topic", {"id": "no-such-id", "title": "X"})
    assert result.isError


async def test_update_topic_empty_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("update_topic", {"id": "", "title": "X"})
    assert result.isError


async def test_update_topic_no_fields_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id})
    assert result.isError


async def test_update_topic_invalid_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "title": "Café"})
    assert result.isError


async def test_update_topic_control_char_title_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool(
            "update_topic", {"id": topic_id, "title": "Title\nWith\nNewlines"}
        )
    assert result.isError


async def test_update_topic_invalid_scope_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "scope": "s" * 33})
    assert result.isError


# --- list_scopes tests ---


async def test_list_scopes_returns_known_scopes() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("list_scopes", {})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert set(data["scopes"]) == {"world", "us", "pdx"}
    assert data["default"] == "world"


async def test_list_scopes_containment() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("list_scopes", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    containment = data["containment"]
    assert set(containment["world"]) == {"world", "us", "pdx"}
    assert set(containment["us"]) == {"us", "pdx"}
    assert set(containment["pdx"]) == {"pdx"}


# --- scope validation tests ---


async def test_add_topic_unknown_scope_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "scope": "local"})
    assert result.isError


async def test_update_topic_unknown_scope_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "scope": "local"})
    assert result.isError


async def test_list_topics_unknown_scope_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("list_topics", {"scope": "local"})
    assert result.isError


# --- notes field tests ---


async def test_add_topic_with_notes() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool(
            "add_topic",
            {"title": "AI Antitrust Case", "notes": "Focus on DOJ angle, not stock price"},
        )
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["notes"] == "Focus on DOJ angle, not stock price"


async def test_add_topic_without_notes_has_null() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Some Story"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["notes"] is None


async def test_add_topic_notes_too_long_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "notes": "x" * 513})
    assert result.isError


async def test_add_topic_notes_max_length_succeeds() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "notes": "x" * 512})
    assert not result.isError


async def test_add_topic_notes_non_ascii_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "notes": "focus on — dash"})
    assert result.isError


async def test_add_topic_notes_control_char_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "notes": "line1\nline2"})
    assert result.isError


async def test_update_topic_notes() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool(
            "update_topic", {"id": topic_id, "notes": "New search guidance"}
        )
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["notes"] == "New search guidance"


async def test_update_topic_notes_reflected_in_list() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("update_topic", {"id": topic_id, "notes": "Track regulatory angle"})
        list_result = await client.call_tool("list_topics", {})
    data = json.loads(list_result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["notes"] == "Track regulatory angle"


async def test_update_topic_notes_too_long_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "notes": "x" * 513})
    assert result.isError


async def test_update_topic_notes_non_ascii_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "My Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "notes": "café"})
    assert result.isError


async def test_update_topic_omitting_notes_leaves_unchanged() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool(
            "add_topic", {"title": "My Topic", "notes": "Original notes"}
        )
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("update_topic", {"id": topic_id, "title": "Updated Title"})
        list_result = await client.call_tool("list_topics", {})
    data = json.loads(list_result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["notes"] == "Original notes"


# --- archive_topic tests ---


async def test_add_topic_returns_active_status() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "My Topic"})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["status"] == "active"


async def test_archive_topic_success() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Concluded Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("archive_topic", {"id": topic_id})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["status"] == "archived"
    assert data["id"] == topic_id


async def test_archive_topic_excluded_from_default_list() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Concluded Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data == []


async def test_archive_topic_visible_with_include_archived() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Concluded Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        result = await client.call_tool("list_topics", {"include_archived": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["status"] == "archived"


async def test_archived_topic_excluded_from_roundup() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Active Story"})
        add_result = await client.call_tool("add_topic", {"title": "Archived Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    titles = {t["title"] for t in data}
    assert "Active Story" in titles
    assert "Archived Story" not in titles


async def test_unarchive_topic_returns_to_list() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Resurfaced Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        await client.call_tool("archive_topic", {"id": topic_id, "archived": False})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["status"] == "active"


async def test_unarchive_topic_appears_in_roundup() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Resurfaced Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        await client.call_tool("archive_topic", {"id": topic_id, "archived": False})
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1


async def test_archive_topic_not_found_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("archive_topic", {"id": "no-such-id"})
    assert result.isError


async def test_archive_topic_empty_id_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("archive_topic", {"id": ""})
    assert result.isError


async def test_archive_topic_preserves_notes_and_timestamps() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool(
            "add_topic",
            {"title": "Story With Notes", "notes": "some guidance"},
        )
        topic_data = json.loads(add_result.content[0].text)  # type: ignore[union-attr]
        topic_id = topic_data["id"]
        added_at = topic_data["added_at"]
        result = await client.call_tool("archive_topic", {"id": topic_id})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["notes"] == "some guidance"
    assert data["added_at"] == added_at


async def test_include_archived_false_hides_archived() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Active Story"})
        add_result = await client.call_tool("add_topic", {"title": "Archived Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        result = await client.call_tool("list_topics", {"include_archived": False})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["title"] == "Active Story"


async def test_include_archived_true_shows_both() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Active Story"})
        add_result = await client.call_tool("add_topic", {"title": "Archived Story"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("archive_topic", {"id": topic_id})
        result = await client.call_tool("list_topics", {"include_archived": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 2


# --- Resource tests ---


def test_reference_doc_path_is_cwd_relative() -> None:
    import pathlib

    from interesting.server import _REFERENCE_DOC

    assert _REFERENCE_DOC == pathlib.Path.cwd() / "interesting-mcp-reference.md", (
        f"_REFERENCE_DOC must resolve from cwd, not from __file__. Got: {_REFERENCE_DOC}"
    )


async def test_instructions_resource_returns_text() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.read_resource(AnyUrl("interesting://instructions"))
    assert len(result.contents) == 1
    text = result.contents[0].text  # type: ignore[union-attr]
    assert isinstance(text, str)
    assert len(text) > 100
    for keyword in (
        "add_topic",
        "list_scopes",
        "list_topics",
        "update_topic",
        "remove_topic",
        "archive_topic",
        "scope",
        "roundup",
        "notes",
        "status",
    ):
        assert keyword in text, f"instructions missing expected keyword: {keyword!r}"


async def test_instructions_resource_covers_roundup_workflow() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.read_resource(AnyUrl("interesting://instructions"))
    text = result.contents[0].text  # type: ignore[union-attr]
    assert "pdx" in text  # scope hierarchy
    assert "128" in text  # title max-length rule
    assert "last_checked_at" in text  # roundup semantics
    assert "news" in text  # roundup trigger
    assert "OpenAI" in text or "Bondi" in text  # concrete title example


async def test_get_instructions_tool_returns_same_content() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        tool_result = await client.call_tool("get_instructions_tool", {})
        resource_result = await client.read_resource(AnyUrl("interesting://instructions"))
    assert not tool_result.isError
    tool_text = tool_result.content[0].text  # type: ignore[union-attr]
    resource_text = resource_result.contents[0].text  # type: ignore[union-attr]
    assert tool_text == resource_text


# --- cadence tests ---


def _backdate_last_checked(db_path: str, topic_id: str, days_ago: int) -> None:
    """Set a topic's last_checked_at to N days before now (UTC), via a direct SQL write.

    Writes the same Python isoformat that production code writes, so the tests
    exercise the real timestamp format used by add_topic / list_topics.
    Opens a separate sqlite3 connection; safe alongside the lifespan's connection
    because the database is opened in WAL mode.
    """
    stamp = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE topics SET last_checked_at = ? WHERE id = ?",
            (stamp, topic_id),
        )
        conn.commit()
    finally:
        conn.close()


async def test_add_topic_default_cadence() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Default cadence"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["cadence"] == "regular"


async def test_add_topic_explicit_cadences() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        for value in ("rare", "occasional", "regular", "frequent", "always"):
            result = await client.call_tool(
                "add_topic", {"title": f"Topic {value}", "cadence": value}
            )
            assert not result.isError, value
            data = json.loads(result.content[0].text)  # type: ignore[union-attr]
            assert data["cadence"] == value


async def test_add_topic_unknown_cadence_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Bad cadence", "cadence": "monthly"})
    assert result.isError


async def test_add_topic_empty_cadence_uses_default() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("add_topic", {"title": "Topic", "cadence": ""})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["cadence"] == "regular"


async def test_update_topic_cadence() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Pace shifter"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "cadence": "frequent"})
    assert not result.isError
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data["cadence"] == "frequent"


async def test_update_topic_unknown_cadence_fails() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "cadence": "monthly"})
    assert result.isError


async def test_update_topic_omitting_cadence_leaves_unchanged() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Stable", "cadence": "rare"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("update_topic", {"id": topic_id, "title": "Renamed"})
        list_result = await client.call_tool("list_topics", {})
    data = json.loads(list_result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["cadence"] == "rare"
    assert data[0]["title"] == "Renamed"


async def test_update_topic_cadence_only_satisfies_at_least_one() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool("add_topic", {"title": "Topic"})
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        result = await client.call_tool("update_topic", {"id": topic_id, "cadence": "frequent"})
    assert not result.isError


async def test_list_topics_includes_cadence() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        await client.call_tool("add_topic", {"title": "Topic", "cadence": "occasional"})
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data[0]["cadence"] == "occasional"


async def test_roundup_excludes_topic_within_cooldown(isolated_db: str) -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool(
            "add_topic", {"title": "Slow burner", "cadence": "rare"}
        )
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        # Backdate to 5 days ago — well inside the 14-day cooldown for 'rare'.
        _backdate_last_checked(isolated_db, topic_id, days_ago=5)
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert data == []


async def test_roundup_includes_topic_after_cooldown(isolated_db: str) -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool(
            "add_topic", {"title": "Slow burner", "cadence": "rare"}
        )
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        # Backdate to 15 days ago — past the 14-day cooldown for 'rare'.
        _backdate_last_checked(isolated_db, topic_id, days_ago=15)
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["id"] == topic_id


async def test_roundup_always_cadence_ignores_cooldown(isolated_db: str) -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool(
            "add_topic", {"title": "High priority", "cadence": "always"}
        )
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        # Backdate by less than a day — for 'always', cooldown is irrelevant.
        _backdate_last_checked(isolated_db, topic_id, days_ago=0)
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["id"] == topic_id


async def test_roundup_null_last_checked_eligible_regardless_of_cadence() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        # Brand-new 'rare' topic — never checked, so should still be eligible.
        await client.call_tool("add_topic", {"title": "Fresh rare", "cadence": "rare"})
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1


async def test_roundup_all_in_cooldown_returns_empty_and_no_stamp(isolated_db: str) -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        add_a = await client.call_tool("add_topic", {"title": "A", "cadence": "rare"})
        id_a = json.loads(add_a.content[0].text)["id"]  # type: ignore[union-attr]
        add_b = await client.call_tool("add_topic", {"title": "B", "cadence": "occasional"})
        id_b = json.loads(add_b.content[0].text)["id"]  # type: ignore[union-attr]
        # Backdate both to within their cooldowns.
        _backdate_last_checked(isolated_db, id_a, days_ago=2)
        _backdate_last_checked(isolated_db, id_b, days_ago=2)
        # Capture pre-roundup last_checked_at.
        pre_list = await client.call_tool("list_topics", {})
        pre_data = json.loads(pre_list.content[0].text)  # type: ignore[union-attr]
        pre_stamps = {t["id"]: t["last_checked_at"] for t in pre_data}
        # Roundup should return empty.
        roundup = await client.call_tool("list_topics", {"roundup": True})
        assert json.loads(roundup.content[0].text) == []  # type: ignore[union-attr]
        # last_checked_at must be unchanged.
        post_list = await client.call_tool("list_topics", {})
        post_data = json.loads(post_list.content[0].text)  # type: ignore[union-attr]
    post_stamps = {t["id"]: t["last_checked_at"] for t in post_data}
    assert post_stamps == pre_stamps


async def test_roundup_mixed_cadences_filters_only_ineligible(isolated_db: str) -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        cooldown_add = await client.call_tool(
            "add_topic", {"title": "In cooldown", "cadence": "rare"}
        )
        cooldown_id = json.loads(cooldown_add.content[0].text)["id"]  # type: ignore[union-attr]
        await client.call_tool("add_topic", {"title": "Eligible fresh", "cadence": "regular"})
        _backdate_last_checked(isolated_db, cooldown_id, days_ago=3)
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    titles = {t["title"] for t in data}
    assert titles == {"Eligible fresh"}


async def test_list_topics_non_roundup_unaffected_by_cadence(isolated_db: str) -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        cooldown_add = await client.call_tool(
            "add_topic", {"title": "Cooling off", "cadence": "rare"}
        )
        cooldown_id = json.loads(cooldown_add.content[0].text)["id"]  # type: ignore[union-attr]
        _backdate_last_checked(isolated_db, cooldown_id, days_ago=2)
        result = await client.call_tool("list_topics", {})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["title"] == "Cooling off"


async def test_roundup_frequent_topic_25h_ago_is_eligible(isolated_db: str) -> None:
    """Regression: Python isoformat timestamps must compare correctly via datetime() normalization.

    A 'frequent' topic (1-day cooldown) last checked 25 hours ago must appear in roundup.
    The stored stamp uses the 'T' separator and '+00:00' offset; without datetime()
    normalization it would compare greater than SQLite's space-separated datetime('now', ...)
    and be wrongly excluded.
    """
    async with create_connected_server_and_client_session(mcp) as client:
        add_result = await client.call_tool(
            "add_topic", {"title": "Frequent 25h", "cadence": "frequent"}
        )
        topic_id = json.loads(add_result.content[0].text)["id"]  # type: ignore[union-attr]
        stamp = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        conn = sqlite3.connect(isolated_db)
        try:
            conn.execute("UPDATE topics SET last_checked_at = ? WHERE id = ?", (stamp, topic_id))
            conn.commit()
        finally:
            conn.close()
        result = await client.call_tool("list_topics", {"roundup": True})
    data = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert len(data) == 1
    assert data[0]["id"] == topic_id


def test_migration_v3_to_v4_backfills_frequent(tmp_path: pathlib.Path) -> None:
    """A v3 database opened by the new init_db gets cadence='frequent' on existing rows."""
    db_path = str(tmp_path / "v3.db")
    # Build a v3-shaped database by hand: schema_version=3 and topics columns up to status.
    raw = sqlite3.connect(db_path)
    try:
        raw.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        raw.execute("INSERT INTO schema_version (version) VALUES (3)")
        raw.execute(
            """
            CREATE TABLE topics (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                scope           TEXT NOT NULL,
                added_at        TEXT,
                last_checked_at TEXT,
                notes           TEXT,
                status          TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        raw.execute(
            "INSERT INTO topics (id, title, scope, added_at, status)"
            " VALUES ('legacy-id', 'Legacy topic', 'world', '2024-01-01T00:00:00+00:00', 'active')"
        )
        raw.commit()
    finally:
        raw.close()

    conn = storage.init_db(db_path)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 4
        cadence = conn.execute("SELECT cadence FROM topics WHERE id = 'legacy-id'").fetchone()[0]
        assert cadence == "frequent"
    finally:
        conn.close()


def test_migration_legacy_v3_columns_detected(tmp_path: pathlib.Path) -> None:
    """A pre-versioning database with v3-shaped columns gets the v4 migration applied."""
    db_path = str(tmp_path / "legacy.db")
    raw = sqlite3.connect(db_path)
    try:
        # No schema_version table yet — exact pre-versioning state.
        raw.execute(
            """
            CREATE TABLE topics (
                id              TEXT PRIMARY KEY,
                title           TEXT NOT NULL,
                scope           TEXT NOT NULL,
                added_at        TEXT,
                last_checked_at TEXT,
                notes           TEXT,
                status          TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        raw.execute(
            "INSERT INTO topics (id, title, scope, status)"
            " VALUES ('old-id', 'Old topic', 'world', 'active')"
        )
        raw.commit()
    finally:
        raw.close()

    conn = storage.init_db(db_path)
    try:
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == 4
        cadence = conn.execute("SELECT cadence FROM topics WHERE id = 'old-id'").fetchone()[0]
        assert cadence == "frequent"
    finally:
        conn.close()


async def test_instructions_resource_mentions_cadence() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.read_resource(AnyUrl("interesting://instructions"))
    text = result.contents[0].text  # type: ignore[union-attr]
    for keyword in ("cadence", "rare", "occasional", "regular", "frequent", "always"):
        assert keyword in text, f"instructions missing cadence keyword: {keyword!r}"
