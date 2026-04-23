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

### Streamable HTTP (persistent server)

Run the server in streamable HTTP mode so it stays alive across sessions and is
reachable over the network:

```
MCP_TRANSPORT=streamable-http python -m interesting.server
```

Or use the CLI flag:

```
python -m interesting.server --transport streamable-http
```

The server binds to `0.0.0.0:8000` by default. Configure Claude Desktop to
connect via streamable HTTP:

```json
{"url": "http://localhost:8000/"}
```

## Configuration

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--transport` | `stdio` | Transport to use: `stdio` or `streamable-http` |
| `--db` | `interesting.db` | Path to the SQLite database file |

### Environment Variables

CLI arguments take precedence over environment variables.

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport to use: `stdio` or `streamable-http` |
| `INTERESTING_DB_PATH` | `interesting.db` | Path to the SQLite database file |
