r"""Tests for the radar-style TSV parser.

Covers the escape rules documented at radar/radar.go:682-684:
- values with \\t, \\n, \\r, or " are wrapped in double-quotes
- inner " is doubled
- NULL is written as an empty field (no escape)
- single quotes are NOT escaped
"""

import pytest

from radar_analyst.parse.tsv import parse_tsv, parse_tsv_bytes


def test_empty_input_yields_no_columns_no_rows() -> None:
    t = parse_tsv("")
    assert t.columns == []
    assert t.rows == []


def test_header_only() -> None:
    t = parse_tsv("name\tvalue\n")
    assert t.columns == ["name", "value"]
    assert t.rows == []


def test_simple_row() -> None:
    t = parse_tsv("name\tvalue\nshared_buffers\t128MB\n")
    assert t.columns == ["name", "value"]
    assert t.rows == [
        {"name": "shared_buffers", "value": "128MB"},
    ]


def test_null_becomes_empty_string() -> None:
    # Radar writes NULL as an unescaped empty field.
    t = parse_tsv("a\tb\tc\nx\t\tz\n")
    assert t.rows == [{"a": "x", "b": "", "c": "z"}]


def test_value_with_tab_is_quoted() -> None:
    t = parse_tsv('name\tvalue\nx\t"a\tb"\n')
    assert t.rows == [{"name": "x", "value": "a\tb"}]


def test_value_with_embedded_newline_is_quoted() -> None:
    t = parse_tsv('comment\n"line 1\nline 2"\n')
    assert t.rows == [{"comment": "line 1\nline 2"}]


def test_value_with_quote_is_doubled() -> None:
    # Radar: inner " → "" (escaped by doubling inside quotes).
    t = parse_tsv('q\n"say ""hi"""\n')
    assert t.rows == [{"q": 'say "hi"'}]


def test_single_quotes_are_not_escaped() -> None:
    # Radar explicitly does NOT escape single quotes.
    t = parse_tsv("q\nit's fine\n")
    assert t.rows == [{"q": "it's fine"}]


def test_multiple_rows() -> None:
    tsv = (
        "rule_name\tallow\n"
        "host\tyes\n"
        "local\tyes\n"
        "hostssl\tno\n"
    )
    t = parse_tsv(tsv)
    assert [r["rule_name"] for r in t.rows] == [
        "host",
        "local",
        "hostssl",
    ]


def test_parse_tsv_bytes_handles_utf8() -> None:
    t = parse_tsv_bytes("hdr\nçüé\n".encode())
    assert t.rows == [{"hdr": "çüé"}]


def test_row_missing_trailing_fields_is_padded_with_empty() -> None:
    # Defensive: if a row has fewer fields than the header, fill with
    # empty string (treated as NULL), matching the radar-emits-empty
    # convention.
    t = parse_tsv("a\tb\tc\nx\ty\n")
    assert t.rows == [{"a": "x", "b": "y", "c": ""}]


def test_row_with_more_fields_than_header_raises() -> None:
    # Extra fields indicate a corrupted TSV; fail fast rather than drop
    # data silently.
    with pytest.raises(ValueError):
        parse_tsv("a\tb\nx\ty\tz\n")


def test_parse_tsv_bytes_replaces_invalid_utf8() -> None:
    # A stray non-UTF-8 byte must not raise: the value survives
    # with U+FFFD so the rest of the file still parses.
    table = parse_tsv_bytes(b"col\nva\xffl\n")
    assert table.columns == ["col"]
    assert table.rows == [{"col": "va�l"}]


def test_a_field_over_the_csv_default_limit_is_read() -> None:
    # csv's own default field limit is 128 KiB.
    value = "x" * (200 * 1024)
    t = parse_tsv(f"q\tn\n{value}\t1\n")
    assert t.rows == [{"q": value, "n": "1"}]
