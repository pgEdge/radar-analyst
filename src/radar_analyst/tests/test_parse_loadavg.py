"""Tests for parse/loadavg.py."""

from radar_analyst.parse.loadavg import LoadAverage, parse_loadavg


def test_empty_input_returns_none() -> None:
    assert parse_loadavg(b"") is None


def test_parses_three_load_values() -> None:
    out = parse_loadavg(b"0.52 0.58 0.59 1/418 12345\n")
    assert out == LoadAverage(load1=0.52, load5=0.58, load15=0.59)


def test_handles_no_trailing_metadata() -> None:
    # /proc/loadavg always has 5 fields; tolerate a stripped form
    # in case some collector ever emits just the three averages.
    out = parse_loadavg(b"1.0 2.0 3.0\n")
    assert out == LoadAverage(load1=1.0, load5=2.0, load15=3.0)


def test_returns_none_on_garbage() -> None:
    assert parse_loadavg(b"not numeric\n") is None
