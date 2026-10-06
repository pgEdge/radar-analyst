"""Tests for parse/extensions.py."""

from radar_analyst.parse.extensions import (
    AvailableExtensions,
    parse_available_extensions,
)


def test_parse_returns_installed_and_latest_per_extension() -> None:
    tsv = (
        "name\tversion\tinstalled\n"
        "pg_stat_statements\t1.10\tf\n"
        "pg_stat_statements\t1.11\tt\n"
        "pg_stat_statements\t1.12\tf\n"
        "pgcrypto\t1.3\tt\n"
    )
    av = parse_available_extensions(tsv.encode())
    assert isinstance(av, AvailableExtensions)
    pgss = av.by_name["pg_stat_statements"]
    assert pgss.installed == "1.11"
    assert pgss.latest == "1.12"
    crypto = av.by_name["pgcrypto"]
    assert crypto.installed == "1.3"
    assert crypto.latest == "1.3"


def test_parse_empty_input_returns_empty() -> None:
    assert parse_available_extensions(b"").by_name == {}


def test_parse_missing_required_columns_returns_empty() -> None:
    # No `installed` column: radar collector schema drift.
    tsv = "name\tversion\nfoo\t1.0\n"
    assert parse_available_extensions(tsv.encode()).by_name == {}


def test_parse_handles_alphanumeric_versions() -> None:
    tsv = (
        "name\tversion\tinstalled\n"
        "ext\t1.0.0\tt\n"
        "ext\t1.0.1-beta\tf\n"
        "ext\t1.0.2\tf\n"
    )
    av = parse_available_extensions(tsv.encode())
    e = av.by_name["ext"]
    assert e.installed == "1.0.0"
    assert e.latest == "1.0.2"


def test_outdated_lists_only_upgradable_extensions() -> None:
    tsv = (
        "name\tversion\tinstalled\n"
        "old_ext\t1.0\tt\n"
        "old_ext\t2.0\tf\n"
        "current_ext\t3.0\tt\n"
        "current_ext\t3.0\tf\n"
    )
    av = parse_available_extensions(tsv.encode())
    upgradable = av.outdated()
    assert len(upgradable) == 1
    assert upgradable[0].name == "old_ext"
    assert upgradable[0].installed == "1.0"
    assert upgradable[0].latest == "2.0"
