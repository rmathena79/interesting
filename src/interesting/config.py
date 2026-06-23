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


def _parse_cadence_days(raw: str) -> dict[str, int | None]:
    """Parse INTERESTING_CADENCE_DAYS from comma-separated key:days pairs.

    Unspecified keys fall back to storage._CADENCE_DAYS defaults, so a
    deployment can override just one cadence. Returns a full dict covering all
    KNOWN_CADENCES.

    days is f-string-interpolated into SQL, so int >= 1 validation is the only
    guard between the input value and the query -- keep it strict.
    """
    result: dict[str, int | None] = dict(storage._CADENCE_DAYS)
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        parts = pair.split(":")
        if len(parts) != 2:
            raise ValueError(
                f"INTERESTING_CADENCE_DAYS: malformed pair {pair!r};"
                " expected 'key:days' (e.g. 'rare:14,regular:2')"
            )
        key, days_str = parts[0].strip(), parts[1].strip()
        if key not in storage.KNOWN_CADENCES:
            valid = ", ".join(sorted(storage.KNOWN_CADENCES))
            raise ValueError(
                f"INTERESTING_CADENCE_DAYS: unknown cadence key {key!r}; known keys: {valid}"
            )
        if key in ("always", "dated"):
            raise ValueError(
                f"INTERESTING_CADENCE_DAYS: {key!r} cannot be overridden"
                f" (its interval is None, not a day count)"
            )
        try:
            days = int(days_str)
        except ValueError:
            raise ValueError(
                f"INTERESTING_CADENCE_DAYS: expected integer >= 1 for key {key!r}, got {days_str!r}"
            )
        if days < 1:
            raise ValueError(f"INTERESTING_CADENCE_DAYS: days for {key!r} must be >= 1, got {days}")
        result[key] = days
    return result


_env_cadence_days = os.environ.get("INTERESTING_CADENCE_DAYS")
CADENCE_DAYS: dict[str, int | None] = (
    _parse_cadence_days(_env_cadence_days)
    if _env_cadence_days is not None
    else dict(storage._CADENCE_DAYS)
)
