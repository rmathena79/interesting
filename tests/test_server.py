import json
import pathlib

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import AnyUrl

import interesting.server as server_module
from interesting import storage
from interesting.server import mcp


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = str(tmp_path / "test.db")
    monkeypatch.setattr(server_module, "_db_path", db_file)


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
