import pytest

from interesting import config, storage

# --- ROUNDUP_LIMIT pure parsing tests (no DB, no env access) ---


def test_roundup_limit_parse_valid() -> None:
    assert config._parse_roundup_limit("10") == 10


def test_roundup_limit_parse_one() -> None:
    assert config._parse_roundup_limit("1") == 1


def test_roundup_limit_parse_non_int() -> None:
    with pytest.raises(ValueError, match="INTERESTING_ROUNDUP_LIMIT"):
        config._parse_roundup_limit("abc")


def test_roundup_limit_parse_zero() -> None:
    with pytest.raises(ValueError, match="INTERESTING_ROUNDUP_LIMIT"):
        config._parse_roundup_limit("0")


def test_roundup_limit_parse_negative() -> None:
    with pytest.raises(ValueError, match="INTERESTING_ROUNDUP_LIMIT"):
        config._parse_roundup_limit("-3")


def test_roundup_limit_parse_float_string() -> None:
    with pytest.raises(ValueError, match="INTERESTING_ROUNDUP_LIMIT"):
        config._parse_roundup_limit("6.0")


# --- Default-preservation regression ---


def test_storage_roundup_limit_default_is_6() -> None:
    """Guard against default drift: storage._ROUNDUP_LIMIT must stay 6."""
    assert storage._ROUNDUP_LIMIT == 6


def test_module_roundup_limit_matches_storage_default() -> None:
    """With no env override, ROUNDUP_LIMIT equals the storage-layer default."""
    assert config.ROUNDUP_LIMIT == storage._ROUNDUP_LIMIT
