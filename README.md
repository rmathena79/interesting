# interesting
MCP server for deterministically tracking news stories of interest

For technical description of the project, see `OVERVIEW.md`.

## Usage

[interesting-mcp-reference.md](interesting-mcp-reference.md) documents how chat applications are expected to interact with this server: tool parameters, scope semantics, title conventions, and the operational modes (topic tracking and news roundup) that drive tool calls.

## Claude Project Setup

When Claude connects to this server, it should read the `interesting://instructions`
resource, or call `get_instructions_tool`, at the start of each session. The resource returns plain-text usage instructions
covering all tools, scope semantics, title conventions, and the news roundup workflow —
the machine-readable equivalent of [interesting-mcp-reference.md](interesting-mcp-reference.md).

Add a project instruction such as:

> At the start of each conversation, call the get_instructions_tool function on the Interesting MCP server before calling any tools.

## Setup

```
python -m venv .venv
source .venv/Scripts/activate  # Windows; use .venv/bin/activate on macOS/Linux
pip install -e .                # installs the package and its runtime dependency
pip install pytest anyio pytest-anyio ruff  # dev tools (see [dependency-groups] in pyproject.toml)
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
| `--db` | `data/interesting.db` | Path to the SQLite database file |

Note the database path is relative to the 'data' directory.

### Environment Variables

CLI arguments take precedence over environment variables.

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | Transport to use: `stdio` or `streamable-http` |
| `INTERESTING_DB_PATH` | `data/interesting.db` | Path to the SQLite database file |
| `INTERESTING_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated allowed `Host` header values; add your server's hostname for HTTP mode |

### Authentication (HTTP mode only)

When running in `streamable-http` mode, set all three credential variables to enable OAuth 2.0
Authorization Code + PKCE authentication. If any are absent the server starts without auth
(appropriate for stdio / local dev).

| Variable | Description |
|---|---|
| `INTERESTING_CLIENT_ID` | OAuth client ID presented by the MCP client at token fetch time |
| `INTERESTING_CLIENT_SECRET` | OAuth client secret presented by the MCP client at token fetch time |
| `INTERESTING_ACCESS_TOKEN` | Static bearer token issued by `/token` and validated on every MCP request |
| `INTERESTING_BASE_URL` | Server base URL used as OAuth issuer URL (default: `http://localhost:8000`) |

Generate strong random values for the secret and token, e.g.:

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Connecting Claude to an authenticated server

In the Claude custom connector settings, enter your server URL and set:
- **OAuth Client ID**: value of `INTERESTING_CLIENT_ID`
- **OAuth Client Secret**: value of `INTERESTING_CLIENT_SECRET`

Claude will perform the Authorization Code + PKCE flow — redirecting to `/authorize` then exchanging the code at `/token` — before connecting.
