# interesting
MCP server for deterministically tracking news stories of interest

## Launching the MCP Server

The server communicates over stdio. MCP clients launch it as a subprocess:

```json
{
  "mcpServers": {
    "interesting": {
      "command": "C:/path/to/.venv/Scripts/python.exe",
      "args": ["-m", "interesting.server"]
    }
  }
}
```

Replace `C:/path/to/` with the absolute path to this repo's `.venv`. The server
logs to stderr; MCP protocol messages travel over stdout/stdin.
