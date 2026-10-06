"""Tests for parse/radar_version.py."""

from radar_analyst.parse.radar_version import (
    RadarMeta,
    parse_radar_meta,
)


def test_parses_version_and_commit() -> None:
    out = parse_radar_meta(b"version: v0.5.0\ncommit: abc1234\n")
    assert out == RadarMeta(version="v0.5.0", commit="abc1234")


def test_parses_no_trailing_newline() -> None:
    out = parse_radar_meta(b"version: v0.5.0\ncommit: abc1234")
    assert out == RadarMeta(version="v0.5.0", commit="abc1234")


def test_strips_whitespace() -> None:
    out = parse_radar_meta(
        b"  version : v0.5.0  \n  commit : abc1234  \n"
    )
    assert out == RadarMeta(version="v0.5.0", commit="abc1234")


def test_returns_none_when_version_missing() -> None:
    assert parse_radar_meta(b"") is None
    assert parse_radar_meta(b"\n\n") is None
    assert parse_radar_meta(b"commit: abc1234\n") is None


def test_handles_dev_build() -> None:
    # Unstamped builds report version: dev. Preserve it
    # verbatim.
    out = parse_radar_meta(b"version: dev\ncommit: unknown\n")
    assert out == RadarMeta(version="dev", commit="unknown")


def test_tolerates_unknown_extra_keys() -> None:
    out = parse_radar_meta(
        b"version: v0.5.0\ncommit: abc1234\nfuture_key: x\n"
    )
    assert out == RadarMeta(version="v0.5.0", commit="abc1234")
