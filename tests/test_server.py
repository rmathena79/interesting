from mcp.shared.memory import create_connected_server_and_client_session

from interesting.server import mcp


async def test_ping_returns_pong() -> None:
    async with create_connected_server_and_client_session(mcp) as client:
        result = await client.call_tool("ping", {})
    assert not result.isError
    assert len(result.content) == 1
    assert result.content[0].text == "pong"  # type: ignore[union-attr]
