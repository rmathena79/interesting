# interesting

MCP server for deterministically tracking news stories of interest.

## Commands

| Task       | Command                      |
|------------|------------------------------|
| Run server | python -m interesting.server |
| Tests      | pytest                       |
| Lint       | ruff check src tests         |
| Format     | ruff format src tests        |

## Project Guidance

- User-facing documentation (setup, configuration, deployment, environment variables) belongs in README.md, not CLAUDE.md.
- Ensure tests can be run while production server is running on same system
- Strict python type annotations throughout
- Rigorous logging to console (use the module logger pattern in server.py)
- All log output must be timestamped
- When adding or changing tools, update `interesting-mcp-reference.md` to match — it is the single source of truth for the `interesting://instructions` MCP resource and for human reference
