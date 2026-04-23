import logging

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
    logger.info("Starting interesting MCP server")
    mcp.run()
