"""Tests for parse/postmaster_start_time.py."""

from radar_analyst.parse.postmaster_start_time import (
    parse_postmaster_start_time,
)


_HEADER = b"start_time\n"


def test_empty_input_returns_none() -> None:
    assert parse_postmaster_start_time(b"") is None


def test_header_only_returns_none() -> None:
    assert parse_postmaster_start_time(_HEADER) is None


def test_parses_pg_timestamp_with_tz_abbrev() -> None:
    # Verbatim shape of radar's postmaster_start_time output.
    raw = _HEADER + b"2026-04-30 10:26:54.03875 +0100 BST\n"
    assert (
        parse_postmaster_start_time(raw)
        == "2026-04-30 10:26:54.03875 +0100 BST"
    )


def test_handles_no_microseconds_no_tz_abbrev() -> None:
    raw = _HEADER + b"2026-05-02 08:46:00 +0000\n"
    assert (
        parse_postmaster_start_time(raw)
        == "2026-05-02 08:46:00 +0000"
    )
