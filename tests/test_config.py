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


# --- CADENCE_DAYS pure parsing tests (no DB, no env access) ---


def test_cadence_days_parse_single_override() -> None:
    result = config._parse_cadence_days("rare:10")
    assert result["rare"] == 10
    assert result["occasional"] == storage._CADENCE_DAYS["occasional"]
    assert result["regular"] == storage._CADENCE_DAYS["regular"]
    assert result["frequent"] == storage._CADENCE_DAYS["frequent"]
    assert result["always"] is None


def test_cadence_days_parse_partial_override() -> None:
    result = config._parse_cadence_days("regular:2,frequent:1")
    assert result["regular"] == 2
    assert result["frequent"] == 1
    assert result["rare"] == storage._CADENCE_DAYS["rare"]
    assert result["occasional"] == storage._CADENCE_DAYS["occasional"]
    assert result["always"] is None


def test_cadence_days_parse_rejects_non_int_days() -> None:
    with pytest.raises(ValueError, match="INTERESTING_CADENCE_DAYS"):
        config._parse_cadence_days("rare:abc")


def test_cadence_days_parse_rejects_zero_days() -> None:
    with pytest.raises(ValueError, match="INTERESTING_CADENCE_DAYS"):
        config._parse_cadence_days("rare:0")


def test_cadence_days_parse_rejects_negative_days() -> None:
    with pytest.raises(ValueError, match="INTERESTING_CADENCE_DAYS"):
        config._parse_cadence_days("rare:-1")


def test_cadence_days_parse_rejects_unknown_key() -> None:
    with pytest.raises(ValueError, match="INTERESTING_CADENCE_DAYS"):
        config._parse_cadence_days("weekly:7")


def test_cadence_days_parse_rejects_always_override() -> None:
    with pytest.raises(ValueError, match="INTERESTING_CADENCE_DAYS"):
        config._parse_cadence_days("always:1")


def test_cadence_days_parse_rejects_malformed_pair() -> None:
    with pytest.raises(ValueError, match="INTERESTING_CADENCE_DAYS"):
        config._parse_cadence_days("rare14")


# --- Default-preservation regression ---


def test_cadence_days_module_default_matches_storage() -> None:
    """With no env override, CADENCE_DAYS must equal the storage-layer defaults."""
    assert config.CADENCE_DAYS == storage._CADENCE_DAYS
