import argparse
import logging
import os

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "interesting",
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        allowed_hosts=["soliboy.tail52f9f8.ts.net", "localhost", "127.0.0.1"]
    ),
)


@mcp.tool(description="Verify connectivity with the server.")
def ping(ctx: Context) -> str:
    logger.info("ping called")
    ctx.info("ping called")
    return "pong"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="interesting MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Transport to use (overrides MCP_TRANSPORT env var)",
    )
    args = parser.parse_args()

    transport: str = args.transport or os.environ.get("MCP_TRANSPORT", "stdio")
    logger.info("Starting interesting MCP server with transport=%s", transport)
    mcp.run(transport=transport)  # type: ignore[arg-type]
