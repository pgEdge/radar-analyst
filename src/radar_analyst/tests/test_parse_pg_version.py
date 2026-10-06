"""Tests for the postgresql/version.tsv parser."""

from radar_analyst.parse.pg_version import parse_version


def test_returns_none_for_empty_input() -> None:
    assert parse_version(b"") is None


def test_returns_none_for_missing_column() -> None:
    assert parse_version(b"other\nfoo\n") is None


def test_parses_modern_pg_version_string() -> None:
    raw = (
        "PostgreSQL 17.2 on x86_64-pc-linux-gnu, "
        "compiled by gcc 13.2.0, 64-bit"
    )
    info = parse_version(f"version\n{raw}\n".encode())
    assert info is not None
    assert info.raw == raw
    assert info.major == 17
    assert info.minor == 2


def test_parses_single_digit_major_only() -> None:
    info = parse_version(b"version\nPostgreSQL 13 on foo\n")
    assert info is not None
    assert info.major == 13
    assert info.minor == 0


def test_non_postgres_string_keeps_raw_but_zeros() -> None:
    info = parse_version(b"version\nSomething else\n")
    assert info is not None
    assert info.raw == "Something else"
    assert info.major == 0
    assert info.minor == 0
