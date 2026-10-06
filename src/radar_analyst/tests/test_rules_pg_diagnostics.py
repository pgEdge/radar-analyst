"""Tests for rules/pg_diagnostics.py."""

from __future__ import annotations

from radar_analyst.parse.pg_diagnostics import PgRole, ProgressRow
from radar_analyst.rules.pg_diagnostics import (
    analyze_in_progress,
    basebackup_in_progress,
    cluster_or_copy_in_progress,
    create_index_in_progress,
    replication_role_present,
    superuser_count_high,
    vacuum_in_progress,
)


def _role(
    rolname: str,
    rolsuper: bool = False,
    rolreplication: bool = False,
    rolcanlogin: bool = True,
    rolvaliduntil: str = "",
) -> PgRole:
    return PgRole(
        rolname=rolname,
        rolsuper=rolsuper,
        rolreplication=rolreplication,
        rolcanlogin=rolcanlogin,
        rolvaliduntil=rolvaliduntil,
    )


# ---------------------------------------------------------------
# superuser_count_high
# ---------------------------------------------------------------

def test_superuser_count_silent_for_only_postgres() -> None:
    parsed = {"pg.roles": [_role("postgres", rolsuper=True)]}
    assert superuser_count_high(parsed) == []


def test_superuser_count_warns_for_extra_superuser() -> None:
    parsed = {
        "pg.roles": [
            _role("postgres", rolsuper=True),
            _role("admin_user", rolsuper=True),
        ]
    }
    out = superuser_count_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.superuser_count_high"
    assert "admin_user" in out[0].detail


def test_superuser_count_silent_for_pg_prefixed_system_roles() -> None:
    parsed = {
        "pg.roles": [
            _role("postgres", rolsuper=True),
            _role("pg_monitor", rolsuper=True),  # system role
        ]
    }
    assert superuser_count_high(parsed) == []


def test_superuser_count_silent_when_no_data() -> None:
    assert superuser_count_high({}) == []


def test_superuser_count_silent_with_empty_roles() -> None:
    assert superuser_count_high({"pg.roles": []}) == []


# ---------------------------------------------------------------
# replication_role_present
# ---------------------------------------------------------------

def test_replication_role_warns_for_non_system_role() -> None:
    parsed = {
        "pg.roles": [
            _role("postgres", rolsuper=True, rolreplication=True),
            _role("repl_user", rolreplication=True),
        ]
    }
    out = replication_role_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.replication_role_present"
    assert "repl_user" in out[0].detail


def test_replication_role_silent_for_postgres_only() -> None:
    parsed = {
        "pg.roles": [
            _role("postgres", rolsuper=True, rolreplication=True),
        ]
    }
    assert replication_role_present(parsed) == []


def test_replication_role_silent_for_pg_prefixed() -> None:
    parsed = {
        "pg.roles": [
            _role("pg_replication", rolreplication=True),
        ]
    }
    assert replication_role_present(parsed) == []


def test_replication_role_silent_when_no_replication_roles() -> None:
    parsed = {
        "pg.roles": [
            _role("app_user"),
            _role("readonly"),
        ]
    }
    assert replication_role_present(parsed) == []


def test_replication_role_silent_when_no_data() -> None:
    assert replication_role_present({}) == []


def _progress(
    pid: int = 12345,
    datname: str = "mydb",
    phase: str = "vacuuming heap",
    blocks_done: int | None = None,
    blocks_total: int | None = None,
) -> ProgressRow:
    return ProgressRow(
        pid=pid,
        datname=datname,
        phase=phase,
        blocks_done=blocks_done,
        blocks_total=blocks_total,
    )


# ---------------------------------------------------------------
# vacuum_in_progress
# ---------------------------------------------------------------

def test_vacuum_in_progress_fires_when_rows_present() -> None:
    parsed = {
        "pg.stat_progress_vacuum": [
            _progress(phase="scanning heap"),
        ]
    }
    out = vacuum_in_progress(parsed)
    assert len(out) == 1
    assert out[0].rule_id == "pg.vacuum_in_progress"
    assert out[0].severity == "info"
    assert "mydb" in out[0].detail


def test_vacuum_in_progress_warns_on_early_progress() -> None:
    parsed = {
        "pg.stat_progress_vacuum": [
            _progress(
                phase="vacuuming heap",
                blocks_done=50,
                blocks_total=10000,
            ),
        ]
    }
    out = vacuum_in_progress(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_vacuum_in_progress_silent_when_no_data() -> None:
    assert vacuum_in_progress({}) == []


def test_vacuum_in_progress_silent_on_empty_list() -> None:
    assert vacuum_in_progress(
        {"pg.stat_progress_vacuum": []}
    ) == []


# ---------------------------------------------------------------
# create_index_in_progress
# ---------------------------------------------------------------

def test_create_index_in_progress_fires() -> None:
    parsed = {
        "pg.stat_progress_create_index": [
            _progress(phase="building index"),
        ]
    }
    out = create_index_in_progress(parsed)
    assert len(out) == 1
    assert out[0].rule_id == "pg.create_index_in_progress"
    assert out[0].severity == "info"


def test_create_index_in_progress_silent() -> None:
    assert create_index_in_progress({}) == []


# ---------------------------------------------------------------
# analyze_in_progress
# ---------------------------------------------------------------

def test_analyze_in_progress_fires() -> None:
    parsed = {
        "pg.stat_progress_analyze": [
            _progress(phase="acquiring sample rows"),
        ]
    }
    out = analyze_in_progress(parsed)
    assert len(out) == 1
    assert out[0].rule_id == "pg.analyze_in_progress"
    assert out[0].severity == "info"


def test_analyze_in_progress_silent() -> None:
    assert analyze_in_progress({}) == []


# ---------------------------------------------------------------
# basebackup_in_progress
# ---------------------------------------------------------------

def test_basebackup_in_progress_fires() -> None:
    parsed = {
        "pg.stat_progress_basebackup": [
            _progress(
                phase="streaming database files",
                datname="",
            ),
        ]
    }
    out = basebackup_in_progress(parsed)
    assert len(out) == 1
    assert out[0].rule_id == "pg.basebackup_in_progress"
    assert out[0].severity == "info"


def test_basebackup_in_progress_silent() -> None:
    assert basebackup_in_progress({}) == []


# ---------------------------------------------------------------
# cluster_or_copy_in_progress
# ---------------------------------------------------------------

def test_cluster_or_copy_fires_on_cluster() -> None:
    parsed = {
        "pg.stat_progress_cluster": [
            _progress(phase="seq scanning heap"),
        ]
    }
    out = cluster_or_copy_in_progress(parsed)
    assert len(out) == 1
    assert out[0].rule_id == "pg.cluster_or_copy_in_progress"
    assert out[0].severity == "info"


def test_cluster_or_copy_fires_on_copy() -> None:
    parsed = {
        "pg.stat_progress_copy": [
            _progress(phase="copying"),
        ]
    }
    out = cluster_or_copy_in_progress(parsed)
    assert len(out) == 1


def test_cluster_or_copy_silent() -> None:
    assert cluster_or_copy_in_progress({}) == []
