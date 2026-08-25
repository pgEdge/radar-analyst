"""Tests for parse/io_schedulers.py."""

from radar_analyst.parse.io_schedulers import parse_io_schedulers


def test_parse_typical_blk_mq_lines() -> None:
    raw = (
        b"sda: [mq-deadline] kyber bfq none\n"
        b"nvme0n1: [none] mq-deadline kyber bfq\n"
    )
    out = parse_io_schedulers(raw)
    assert out == {
        "sda": "mq-deadline",
        "nvme0n1": "none",
    }


def test_parse_legacy_scheduler_lines() -> None:
    raw = b"sda: noop deadline [cfq]\n"
    assert parse_io_schedulers(raw) == {"sda": "cfq"}


def test_empty_input_returns_empty() -> None:
    assert parse_io_schedulers(b"") == {}


def test_skips_lines_without_active_bracket() -> None:
    raw = (
        b"weird: scheduler-with-no-brackets\n"
        b"sda: [none]\n"
    )
    assert parse_io_schedulers(raw) == {"sda": "none"}


def test_handles_extra_whitespace() -> None:
    raw = b"  sda  :   [mq-deadline]  kyber  bfq  \n"
    assert parse_io_schedulers(raw) == {"sda": "mq-deadline"}
