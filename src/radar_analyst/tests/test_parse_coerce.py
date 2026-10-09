"""Tests for the shared string-to-scalar coercion helpers."""

from datetime import UTC, datetime

from radar_analyst.parse.coerce import (
    as_bool,
    as_datetime_or_none,
    as_float,
    as_int,
    as_int_or_none,
    row_float,
    row_int,
)


def test_as_int_parses_and_defaults_to_zero() -> None:
    assert as_int("42") == 42
    assert as_int(" 42 ") == 42
    assert as_int("") == 0
    assert as_int("   ") == 0
    assert as_int("nope") == 0


def test_as_int_or_none_distinguishes_absent() -> None:
    assert as_int_or_none("42") == 42
    assert as_int_or_none("") is None
    assert as_int_or_none("nope") is None
    assert as_int_or_none(None) is None


def test_as_float_parses_and_defaults_to_zero() -> None:
    assert as_float("1.5") == 1.5
    assert as_float("") == 0.0
    assert as_float("junk") == 0.0


def test_as_bool_accepts_go_and_postgres_spellings() -> None:
    # Radar serializes booleans via Go's %v ("true"/"false"),
    # and the helper also tolerates Postgres text spellings.
    assert as_bool("true") is True
    assert as_bool("t") is True
    assert as_bool("TRUE") is True
    assert as_bool("1") is True
    assert as_bool("yes") is True
    assert as_bool("false") is False
    assert as_bool("f") is False
    assert as_bool("") is False
    assert as_bool("0") is False


def test_row_helpers_read_and_coerce() -> None:
    row = {"n": "7", "x": "2.5", "empty": ""}
    assert row_int(row, "n") == 7
    assert row_int(row, "absent") == 0
    assert row_int(row, "empty") == 0
    assert row_float(row, "x") == 2.5
    assert row_float(row, "absent") == 0.0


def test_as_datetime_or_none_reads_radar_go_layout() -> None:
    # Go's time.Time layout: the fraction drops trailing zeros, and
    # a zone name follows the offset.
    assert as_datetime_or_none(
        "2026-03-14 09:26:53.58979 +0000 UTC"
    ) == datetime(2026, 3, 14, 9, 26, 53, 589790, tzinfo=UTC)
    assert as_datetime_or_none(
        "2026-01-23 23:47:57.595778 +0000 GMT"
    ) == datetime(2026, 1, 23, 23, 47, 57, 595778, tzinfo=UTC)
    assert as_datetime_or_none(
        "2026-07-01 12:00:00 +0100 BST"
    ) == datetime(2026, 7, 1, 11, 0, tzinfo=UTC)
    assert as_datetime_or_none(
        "2026-01-31 23:30:00.123456789 -0500 EST"
    ) == datetime(2026, 2, 1, 4, 30, 0, 123456, tzinfo=UTC)


def test_as_datetime_or_none_reads_iso_and_rejects_the_rest() -> None:
    assert as_datetime_or_none(
        "2024-01-01 00:00:00+00"
    ) == datetime(2024, 1, 1, tzinfo=UTC)
    assert as_datetime_or_none("") is None
    assert as_datetime_or_none(None) is None
    assert as_datetime_or_none("yesterday") is None
