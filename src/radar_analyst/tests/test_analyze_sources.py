"""Tests for the category → archive-paths derivation."""

from typing import Any

from radar_analyst.analyze.sources import (
    CATEGORY_KINDS,
    sources_for_category,
)


_INVENTORY: list[dict[str, Any]] = [
    {
        "path": "postgresql/configuration.tsv",
        "kind": "pg.settings",
        "dbname": None,
        "size": 100,
    },
    {
        "path": "postgresql/postgresql.conf",
        "kind": "pg.conf.postgresql",
        "dbname": None,
        "size": 100,
    },
    {
        "path": "postgresql/replication.tsv",
        "kind": "pg.replication",
        "dbname": None,
        "size": 100,
    },
    {
        "path": "system/proc/meminfo.out",
        "kind": "sys.proc.meminfo",
        "dbname": None,
        "size": 100,
    },
    {
        "path": "system/sysctl.out",
        "kind": "sys.sysctl",
        "dbname": None,
        "size": 100,
    },
    {
        "path": "databases/foo/extensions.tsv",
        "kind": "pg.db.extensions",
        "dbname": "foo",
        "size": 100,
    },
    {
        "path": "databases/bar/extensions.tsv",
        "kind": "pg.db.extensions",
        "dbname": "bar",
        "size": 100,
    },
    {
        "path": "weird/unknown.txt",
        "kind": None,
        "dbname": None,
        "size": 5,
    },
]


def test_categories_have_kinds_defined() -> None:
    for cat in (
        "Host & OS",
        "PostgreSQL Configuration",
        "Workload",
        "Internals & I/O Health",
        "Replication",
    ):
        assert cat in CATEGORY_KINDS
        assert CATEGORY_KINDS[cat], f"{cat} has no kinds"


def test_host_os_returns_only_sys_paths() -> None:
    paths = sources_for_category("Host & OS", _INVENTORY)
    assert "system/proc/meminfo.out" in paths
    assert "system/sysctl.out" in paths
    assert "postgresql/configuration.tsv" not in paths


def test_pg_config_returns_postgres_settings_paths() -> None:
    paths = sources_for_category(
        "PostgreSQL Configuration", _INVENTORY
    )
    assert "postgresql/configuration.tsv" in paths
    assert "postgresql/postgresql.conf" in paths
    assert "system/proc/meminfo.out" not in paths


def test_replication_returns_only_replication_paths() -> None:
    paths = sources_for_category("Replication", _INVENTORY)
    assert "postgresql/replication.tsv" in paths
    assert "postgresql/configuration.tsv" not in paths


def test_per_database_filters_by_dbname() -> None:
    paths = sources_for_category(
        "Database: foo", _INVENTORY
    )
    assert "databases/foo/extensions.tsv" in paths
    assert "databases/bar/extensions.tsv" not in paths


def test_per_database_unknown_db_returns_empty() -> None:
    paths = sources_for_category(
        "Database: nonexistent", _INVENTORY
    )
    assert paths == []


def test_unknown_category_returns_empty() -> None:
    assert sources_for_category("Bogus", _INVENTORY) == []


def test_sorted_output() -> None:
    paths = sources_for_category("Host & OS", _INVENTORY)
    assert paths == sorted(paths)


def test_excludes_unclassified_unknown_paths() -> None:
    # The coverage canary list shouldn't bleed into category
    # source lists: those are surfaced separately through the
    # files inventory endpoint, not per-category.
    for cat in CATEGORY_KINDS:
        assert "weird/unknown.txt" not in (
            sources_for_category(cat, _INVENTORY)
        )


def test_every_mapped_kind_is_producible_by_the_classifier() -> None:
    # Every kind the operator-facing source list names must be a
    # kind the archive classifier can actually emit; a typo here
    # silently drops files from the sources panel.
    from radar_analyst.archive.reader import _FIXED

    emittable = set(_FIXED.values())
    mapped: set[str] = set()
    for kinds in CATEGORY_KINDS.values():
        mapped |= kinds
    assert sorted(mapped - emittable) == []
