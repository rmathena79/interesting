import pathlib

import pytest

from interesting.server import _resolve_db_path


def p(path: str) -> pathlib.Path:
    return pathlib.Path(path)


def test_simple_name() -> None:
    assert p(_resolve_db_path("foo.db")) == p("data/foo.db")


def test_default_name() -> None:
    assert p(_resolve_db_path("interesting.db")) == p("data/interesting.db")


def test_forward_slash_subdirectory() -> None:
    assert p(_resolve_db_path("sub/foo.db")) == p("data/sub/foo.db")


def test_backslash_treated_as_separator() -> None:
    # Windows-style path: backslash must become a path separator, not be stripped.
    assert p(_resolve_db_path("sub\\foo.db")) == p("data/sub/foo.db")


def test_data_prefix_forward_slash_nests_under_data() -> None:
    # "data/foo.db" is treated as a relative path, so it lands under data/data/.
    assert p(_resolve_db_path("data/foo.db")) == p("data/data/foo.db")


def test_data_prefix_backslash_nests_under_data() -> None:
    assert p(_resolve_db_path("data\\production.db")) == p("data/data/production.db")


def test_mixed_slashes() -> None:
    assert p(_resolve_db_path("a/b\\c.db")) == p("data/a/b/c.db")


def test_deep_path() -> None:
    assert p(_resolve_db_path("a/b/c/d.db")) == p("data/a/b/c/d.db")


def test_absolute_unix_path_raises() -> None:
    with pytest.raises(ValueError, match="absolute"):
        _resolve_db_path("/data/foo.db")


def test_absolute_windows_path_raises() -> None:
    with pytest.raises(ValueError, match="absolute"):
        _resolve_db_path("C:/data/foo.db")


def test_absolute_windows_backslash_raises() -> None:
    with pytest.raises(ValueError, match="absolute"):
        _resolve_db_path("C:\\data\\foo.db")
