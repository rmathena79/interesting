import os

from interesting import storage

# Tunables: env vars that adjust behavior without affecting stored-data semantics.
# Reads happen once at import; no filesystem I/O (safe to import in tests).
# Bad values raise ValueError at import time -- fail fast, same pattern as _resolve_db_path.
#
# Guiding rule: tune behavior, never tune stored-data semantics. Specifically, leave
# alone: KNOWN_CADENCES keys, _MIGRATION_CADENCE, status constants, _SCHEMA_VERSION,
# DEFAULT_SCOPE, _CONTAINED_SCOPES, and _DATA_DIR.


def _parse_roundup_limit(raw: str) -> int:
    """Parse INTERESTING_ROUNDUP_LIMIT. Raises ValueError on non-integer or value < 1."""
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"INTERESTING_ROUNDUP_LIMIT: expected integer >= 1, got {raw!r}")
    if value < 1:
        raise ValueError(f"INTERESTING_ROUNDUP_LIMIT: must be >= 1, got {value}")
    return value


_env_roundup_limit = os.environ.get("INTERESTING_ROUNDUP_LIMIT")
ROUNDUP_LIMIT: int = (
    _parse_roundup_limit(_env_roundup_limit)
    if _env_roundup_limit is not None
    else storage._ROUNDUP_LIMIT
)
