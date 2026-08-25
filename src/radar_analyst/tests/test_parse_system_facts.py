"""Tests for the small system-facts parsers."""

from radar_analyst.parse.system_facts import (
    parse_hostname,
    parse_hypervisor,
    parse_lscpu,
    parse_os_release,
    parse_uname,
    parse_uptime,
)


def test_parse_hostname_strips_whitespace() -> None:
    assert parse_hostname(b"sarlacc\n") == "sarlacc"


def test_parse_hostname_empty_returns_none() -> None:
    assert parse_hostname(b"\n") is None


def test_parse_os_release_keeps_pretty_name() -> None:
    data = (
        b'PRETTY_NAME="Ubuntu 25.10 (Questing Quokka)"\n'
        b'NAME="Ubuntu"\n'
        b'VERSION_ID="25.10"\n'
        b"# a comment line\n"
        b"garbage-without-equals\n"
    )
    out = parse_os_release(data)
    assert (
        out["PRETTY_NAME"] == "Ubuntu 25.10 (Questing Quokka)"
    )
    assert out["VERSION_ID"] == "25.10"
    assert "garbage-without-equals" not in out


def test_parse_uname_returns_full_line() -> None:
    line = (
        b"Linux sarlacc 6.11.0-9-generic #10-Ubuntu SMP "
        b"x86_64 GNU/Linux\n"
    )
    assert "6.11.0-9-generic" in (parse_uname(line) or "")


def test_parse_lscpu_captures_cpu_count() -> None:
    data = (
        b"Architecture:        x86_64\n"
        b"CPU(s):              16\n"
        b"Thread(s) per core:  2\n"
        b"Model name:          AMD EPYC 7763 64-Core Processor\n"
    )
    out = parse_lscpu(data)
    assert out["CPU(s)"] == "16"
    assert "AMD EPYC" in out["Model name"]


def test_parse_uptime_returns_seconds() -> None:
    assert parse_uptime(b"12345.67 9876.54\n") == 12345.67


def test_parse_uptime_garbage_returns_none() -> None:
    assert parse_uptime(b"nope\n") is None


def test_parse_hypervisor_kvm() -> None:
    assert parse_hypervisor(b"kvm\n") == "kvm"


def test_parse_hypervisor_none_means_bare_metal() -> None:
    assert parse_hypervisor(b"none\n") == "none"


def test_parse_hypervisor_normalises_case() -> None:
    assert parse_hypervisor(b"Microsoft\n") == "microsoft"


def test_parse_hypervisor_empty_input() -> None:
    assert parse_hypervisor(b"") == ""


def test_cpu_count_from_lscpu() -> None:
    from radar_analyst.parse.system_facts import (
        cpu_count_from_lscpu,
    )

    assert cpu_count_from_lscpu({"CPU(s)": "16"}) == 16
    assert cpu_count_from_lscpu({"CPU(s)": ""}) == 0
    assert cpu_count_from_lscpu({"CPU(s)": "junk"}) == 0
    assert cpu_count_from_lscpu({}) == 0
