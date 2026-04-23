import argparse
import logging
import os

from mcp.server.fastmcp import Context, FastMCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

mcp = FastMCP("interesting")


@mcp.tool(description="Verify connectivity with the server.")
def ping(ctx: Context) -> str:
    logger.info("ping called")
    ctx.info("ping called")
    return "pong"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="interesting MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="Transport to use (overrides MCP_TRANSPORT env var)",
    )
    args = parser.parse_args()

    transport: str = args.transport or os.environ.get("MCP_TRANSPORT", "stdio")
    logger.info("Starting interesting MCP server with transport=%s", transport)
    mcp.run(transport=transport)  # type: ignore[arg-type]
