"""The host and collection time are read from radar's archive name.

Radar writes ``radar-<hostname>-<YYYYMMDD>-<HHMMSS>.zip`` and records
no collection time inside the archive, so the name is the only
source for it. The hostname may itself contain dashes, which is why
the parse anchors on the trailing timestamp rather than splitting.
"""

from __future__ import annotations

from datetime import datetime

from radar_analyst.archive.naming import parse_archive_name


def test_reads_host_and_time_from_a_radar_name() -> None:
    parsed = parse_archive_name("radar-db1-20260903-164450.zip")
    assert parsed is not None
    assert parsed.hostname == "db1"
    assert parsed.collected_at == datetime(2026, 9, 3, 16, 44, 50)


def test_keeps_dashes_inside_the_hostname() -> None:
    parsed = parse_archive_name("radar-pg-prod-01-20260101-000000.zip")
    assert parsed is not None
    assert parsed.hostname == "pg-prod-01"


def test_ignores_a_leading_directory() -> None:
    parsed = parse_archive_name("/tmp/radar-db1-20260903-164450.zip")
    assert parsed is not None
    assert parsed.hostname == "db1"


def test_returns_none_for_other_names() -> None:
    assert parse_archive_name("archive.zip") is None
    assert parse_archive_name("radar-db1.zip") is None
    assert parse_archive_name("radar-db1-20260903-164450.tar") is None
    assert parse_archive_name("") is None


def test_returns_none_for_an_impossible_time() -> None:
    assert parse_archive_name("radar-db1-20261399-256161.zip") is None
