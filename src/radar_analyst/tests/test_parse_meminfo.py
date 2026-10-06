"""Tests for the /proc/meminfo parser."""

from radar_analyst.parse.meminfo import parse_meminfo


_SAMPLE = (
    "MemTotal:       16384000 kB\n"
    "MemFree:         1024000 kB\n"
    "MemAvailable:    8192000 kB\n"
    "Buffers:          128000 kB\n"
    "Cached:          4096000 kB\n"
    "SwapTotal:       2048000 kB\n"
    "SwapFree:        2048000 kB\n"
    "HugePages_Total:       0\n"
    "HugePages_Free:        0\n"
    "Hugepagesize:       2048 kB\n"
)


def test_empty_input_returns_empty_dict() -> None:
    assert parse_meminfo(b"") == {}


def test_kb_values_converted_to_bytes() -> None:
    info = parse_meminfo(_SAMPLE.encode())
    assert info["MemTotal"] == 16_384_000 * 1024
    assert info["MemAvailable"] == 8_192_000 * 1024
    assert info["Hugepagesize"] == 2048 * 1024


def test_count_values_left_as_is() -> None:
    info = parse_meminfo(_SAMPLE.encode())
    assert info["HugePages_Total"] == 0
    assert info["HugePages_Free"] == 0


def test_all_expected_keys_present() -> None:
    info = parse_meminfo(_SAMPLE.encode())
    assert {
        "MemTotal",
        "MemFree",
        "MemAvailable",
        "Buffers",
        "Cached",
        "SwapTotal",
        "SwapFree",
        "HugePages_Total",
        "HugePages_Free",
        "Hugepagesize",
    } <= info.keys()


def test_malformed_lines_are_skipped() -> None:
    info = parse_meminfo(
        b"MemTotal:       100 kB\n"
        b"garbage line without colon\n"
        b"MemFree:        50 kB\n"
    )
    assert info == {
        "MemTotal": 100 * 1024,
        "MemFree": 50 * 1024,
    }
