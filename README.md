# interesting
MCP server for deterministically tracking news stories of interest

For technical description of the project, see `OVERVIEW.md`.

## Usage

[interesting-mcp-reference.md](interesting-mcp-reference.md) documents how chat applications are expected to interact with this server: tool parameters, scope semantics, title conventions, and the operational modes (topic tracking and news roundup) that drive tool calls. This file is also served to AI clients.

## Claude Project Setup

When Claude connects to this server, it should read the `interesting://instructions`
resource, or call `get_instructions_tool`, at the start of each session. The resource returns plain-text usage instructions
covering all tools, scope semantics, title conventions, and the news roundup workflow --
ingests [interesting-mcp-reference.md](interesting-mcp-reference.md).

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

## Deployment (Windows)

Use `deploy.ps1` to install the server into a separate production directory, isolated from the dev repo.

### First-time setup

```powershell
# From the dev repo root:
.\deploy.ps1 -DestDir C:\path\to\interesting-prod
```

This copies the server source, creates a `.venv`, and installs the package. Tests, dev tooling, and the dev database are not copied.

Then create a `.env` in the production directory:

```powershell
Copy-Item .env.example C:\path\to\interesting-prod\.env
# Edit .env -- at minimum, set MCP_TRANSPORT and the OAuth credentials for HTTP mode
```

### Launching

Double-click `launch.bat` in the production directory (or create a Windows shortcut to it for one-click access). This opens a minimized console window in the taskbar; restore it to see live log output. The window stays open if the server exits, so errors remain visible.

The database (`data\interesting.db`) is created in the production directory on first launch.

### Updating

After making changes in the dev repo, re-run `deploy.ps1` and restart the server:

```powershell
.\deploy.ps1 -DestDir C:\path\to\interesting-prod
# Then stop the server (close its console window) and launch again
```

`deploy.ps1` is safe to re-run: it mirrors source files and reinstalls the package without touching `.env` or `data\`.

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

When running in `streamable-http` mode, set both credential variables to enable OAuth 2.0
Authorization Code + PKCE authentication. If either is absent the server starts without auth
(appropriate for stdio / local dev).

| Variable | Description |
|---|---|
| `INTERESTING_CLIENT_ID` | OAuth client ID registered with the MCP client |
| `INTERESTING_ACCESS_TOKEN` | Static bearer token issued by `/token` and validated on every MCP request |
| `INTERESTING_BASE_URL` | Server base URL used as OAuth issuer URL (default: `http://localhost:8000`) |

Generate a strong random value for the token, e.g.:

```
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Connecting Claude to an authenticated server

In the Claude custom connector settings, enter your server URL and set:
- **OAuth Client ID**: value of `INTERESTING_CLIENT_ID`
- **OAuth Client Secret**: leave blank (this server uses PKCE without a client secret)

Claude will perform the Authorization Code + PKCE flow -- redirecting to `/authorize` then exchanging the code at `/token` -- before connecting.
