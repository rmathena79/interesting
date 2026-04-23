# interesting

MCP server for deterministically tracking news stories of interest.

## Setup

```
python -m venv .venv
source .venv/Scripts/activate  # Windows; use .venv/bin/activate on macOS/Linux
pip install -r requirements-dev.txt   # installs package as editable + dev tools
```

## Commands

| Task       | Command                      |
|------------|------------------------------|
| Run server | python -m interesting.server |
| Tests      | pytest                       |
| Lint       | ruff check src tests         |
| Format     | ruff format src tests        |

## Project Guidance

- Ensure tests can be run while production server is running on same system
- Strict python type enforcement
- Rigorous logging to console