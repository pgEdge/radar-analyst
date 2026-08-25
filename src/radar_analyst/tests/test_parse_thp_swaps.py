"""Tests for THP + /proc/swaps parsers."""

from radar_analyst.parse.swaps import parse_swaps
from radar_analyst.parse.thp import parse_thp


def test_thp_picks_root_enabled_line() -> None:
    real = (
        b"/sys/kernel/mm/transparent_hugepage/hugepages-32kB/enabled:"
        b"always inherit madvise [never]\n"
        b"/sys/kernel/mm/transparent_hugepage/hugepages-64kB/enabled:"
        b"always inherit madvise [never]\n"
        b"/sys/kernel/mm/transparent_hugepage/enabled:"
        b"always [madvise] never\n"
        b"/sys/kernel/mm/transparent_hugepage/defrag:"
        b"always [madvise] never\n"
    )
    assert parse_thp(real) == "madvise"


def test_thp_honours_bracket_modes() -> None:
    assert (
        parse_thp(
            b"/sys/kernel/mm/transparent_hugepage/enabled:"
            b"[always] madvise never\n"
        )
        == "always"
    )
    assert (
        parse_thp(
            b"/sys/kernel/mm/transparent_hugepage/enabled:"
            b"always madvise [never]\n"
        )
        == "never"
    )


def test_thp_malformed_returns_none() -> None:
    assert parse_thp(b"no brackets here") is None
    assert parse_thp(b"") is None
    # Only per-size lines, no root: must not fall back.
    assert (
        parse_thp(
            b"/sys/kernel/mm/transparent_hugepage/"
            b"hugepages-32kB/enabled:always [never]\n"
        )
        is None
    )


def test_swaps_no_active_devices() -> None:
    data = (
        b"Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
    )
    assert parse_swaps(data) == []


def test_swaps_one_partition() -> None:
    data = (
        b"Filename\t\tType\tSize\tUsed\tPriority\n"
        b"/dev/sda2\tpartition\t8388604\t12345\t-2\n"
    )
    out = parse_swaps(data)
    assert len(out) == 1
    assert out[0].name == "/dev/sda2"
    assert out[0].kind == "partition"
    assert out[0].size_kib == 8388604
    assert out[0].used_kib == 12345
