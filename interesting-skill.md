# Skill: interesting MCP Server

You have access to the **interesting** MCP server, which provides tools for
tracking news stories of interest.

## Available Tools

### `ping`
- **Parameters:** none
- **Returns:** the string `"pong"`
- **Use when:** verifying that the server is reachable and responding correctly.

## Usage Notes

- Call `ping` at the start of any session to confirm connectivity before using
  other tools.
- All tools return plain text unless otherwise noted.
- The server may be running as a persistent streamable HTTP server (e.g., via
  `MCP_TRANSPORT=streamable-http python -m interesting.server`). In that case it
  retains state across sessions and is reachable at `http://localhost:8000/` by
  default.
