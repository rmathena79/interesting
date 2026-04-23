# interesting
MCP server for deterministically tracking news stories of interest

## Setup

```
python -m venv .venv
source .venv/Scripts/activate  # Windows; use .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt   # installs package as editable + dev tools
```

## Launching the MCP Server

### stdio (subprocess)

MCP clients launch the server as a subprocess over stdio:

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

### SSE (persistent server)

Run the server in SSE mode so it stays alive across sessions and is reachable
over the network:

```
MCP_TRANSPORT=sse python -m interesting.server
```

Or use the CLI flag:

```
python -m interesting.server --transport sse
```

The server binds to `0.0.0.0:8000` by default. Configure Claude Desktop to
connect via SSE:

```json
{"url": "http://localhost:8000/sse"}
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport to use: `stdio` or `sse` |
| `INTERESTING_DB_PATH` | `interesting.db` | Path to the SQLite database file |
