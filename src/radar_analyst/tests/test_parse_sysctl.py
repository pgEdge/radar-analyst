"""Tests for the sysctl.out whitelist parser."""

from radar_analyst.parse.sysctl import PG_RELEVANT_KEYS, parse_sysctl


_FULL = """\
abi.vsyscall32 = 1
vm.swappiness = 10
vm.dirty_background_bytes = 0
vm.dirty_ratio = 20
vm.overcommit_memory = 2
kernel.shmmax = 18446744073692774399
kernel.sem = 32000 1024000000 500 32000
net.core.somaxconn = 4096
fs.file-max = 9223372036854775807
kernel.random.uuid = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
"""


def test_empty_input_returns_empty_dict() -> None:
    assert parse_sysctl(b"") == {}


def test_whitelist_filters_noise() -> None:
    out = parse_sysctl(_FULL.encode())
    # Keys not on the PG whitelist must be dropped.
    assert "abi.vsyscall32" not in out
    assert "kernel.random.uuid" not in out


def test_whitelisted_keys_are_kept() -> None:
    out = parse_sysctl(_FULL.encode())
    assert out["vm.swappiness"] == "10"
    assert out["vm.dirty_background_bytes"] == "0"
    assert out["vm.dirty_ratio"] == "20"
    assert out["vm.overcommit_memory"] == "2"
    assert out["net.core.somaxconn"] == "4096"


def test_multi_value_setting_is_preserved() -> None:
    # kernel.sem = "32000 1024000000 500 32000": four space-separated
    # numbers. Preserve as a single string.
    out = parse_sysctl(_FULL.encode())
    assert out["kernel.sem"] == "32000 1024000000 500 32000"


def test_lines_without_equals_are_ignored() -> None:
    out = parse_sysctl(
        b"vm.swappiness = 10\nnot a sysctl line\n"
    )
    assert out == {"vm.swappiness": "10"}


def test_whitelist_contains_expected_pg_keys() -> None:
    # Sanity: the whitelist must at least include the keys we rely
    # on for the Host & OS rule pack.
    required = {
        "vm.swappiness",
        "vm.dirty_background_bytes",
        "vm.dirty_ratio",
        "vm.overcommit_memory",
        "kernel.shmmax",
        "net.core.somaxconn",
        "fs.file-max",
    }
    assert required <= PG_RELEVANT_KEYS
