"""A radar archive read by read_and_parse, then checked by the rules.

Each archive holds only the entries one case needs, written the
way radar writes them: Go's ``%v`` layout for timestamps, NULL as
an empty field.
"""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

from radar_analyst.analyze.categories import CATEGORIES, Category
from radar_analyst.analyze.facts import build_category_facts
from radar_analyst.analyze.parsing import read_and_parse
from radar_analyst.rules import run_for_category


_PG_VERSION = (
    "version\nPostgreSQL 15.8 on x86_64-pc-linux-gnu, "
    "compiled by gcc 11.5.0, 64-bit\n"
)


def _archive(tmp_path: Path, entries: dict[str, str]) -> Path:
    z = tmp_path / "radar-testhost-20260101-000000.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        for name, body in entries.items():
            zf.writestr(name, body)
    return z


def _tsv(columns: tuple[str, ...], *rows: dict[str, str]) -> str:
    lines = ["\t".join(columns)]
    lines += ["\t".join(r.get(c, "") for c in columns) for r in rows]
    return "\n".join(lines) + "\n"


def _category(key: str) -> Category:
    return next(c for c in CATEGORIES if c.key == key)


def test_bgwriter_stats_reset_in_utc_is_read(tmp_path: Path) -> None:
    z = _archive(tmp_path, {
        "postgresql/bgwriter.tsv": (
            "checkpoints_timed\tcheckpoints_req\t"
            "checkpoint_write_time\tcheckpoint_sync_time\t"
            "buffers_checkpoint\tbuffers_clean\tmaxwritten_clean\t"
            "buffers_backend\tbuffers_backend_fsync\tbuffers_alloc\t"
            "stats_reset\n"
            "100\t10\t1.5e+06\t2000\t50000\t3000\t20\t40000\t0\t"
            "900000\t2026-02-02 06:15:30.12345 +0000 UTC\n"
        ),
    })
    parsed = read_and_parse(z)[0]
    assert parsed["pg.bgwriter"].stats_reset == datetime(
        2026, 2, 2, 6, 15, 30, 123450, tzinfo=UTC
    )


_ACTIVITY_COLUMNS = (
    "datid", "datname", "pid", "leader_pid", "usesysid", "usename",
    "application_name", "client_addr", "client_hostname",
    "client_port", "backend_start", "xact_start", "query_start",
    "state_change", "wait_event_type", "wait_event", "state",
    "backend_xid", "backend_xmin", "query_id", "query",
    "backend_type",
)

# A standby's walsender: its START_REPLICATION stays the running
# query for as long as the standby is connected.
_WALSENDER = {
    "pid": "101", "usename": "replicator",
    "application_name": "standby1", "client_addr": "192.0.2.10",
    "client_port": "50000",
    "backend_start": "2026-01-01 00:00:00.5 +0000 UTC",
    "query_start": "2026-01-01 00:00:01.25 +0000 UTC",
    "state_change": "2026-01-01 00:00:01.25 +0000 UTC",
    "wait_event_type": "Activity", "wait_event": "WalSenderMain",
    "state": "active",
    "query": '"START_REPLICATION SLOT ""standby1"" 0/3000000 '
             'TIMELINE 1"',
    "backend_type": "walsender",
}

# radar's aggregate over every non-idle session, read 15 h 35 min
# after the walsender's query began.
_MAXAGE = (
    "max_query_age\tmax_xact_age\tmax_backend_age\t"
    "max_lock_wait_age\n"
    "15:35:00\t00:15:00\t15:35:00.75\t\n"
)


def _client(query_start: str, state: str) -> dict[str, str]:
    return {
        "datid": "16384", "datname": "appdb", "pid": "202",
        "usename": "app", "client_addr": "192.0.2.20",
        "client_port": "50001",
        "backend_start": "2026-01-01 15:00:00 +0000 UTC",
        "xact_start": query_start, "query_start": query_start,
        "state_change": query_start, "state": state,
        "query": "SELECT count(*) FROM tab1",
        "backend_type": "client backend",
    }


def _activity(*rows: dict[str, str]) -> str:
    return _tsv(_ACTIVITY_COLUMNS, *rows)


def test_a_walsender_is_not_the_oldest_running_query(
    tmp_path: Path,
) -> None:
    z = _archive(tmp_path, {
        "postgresql/running_activity.tsv": _activity(
            _WALSENDER,
            _client("2026-01-01 15:20:01.25 +0000 UTC", "active"),
        ),
        "postgresql/running_activity_maxage.tsv": _MAXAGE,
    })
    parsed = read_and_parse(z)[0]
    found = [
        f for f in run_for_category("Workload", parsed)
        if f.rule_id == "pg.activity.long_query"
    ]
    assert [(f.severity, f.title) for f in found] == [(
        "warning",
        "Oldest running query has been executing for 15.0 min",
    )]
    facts = build_category_facts(_category("pg_workload"), parsed)
    assert facts is not None
    assert "  query   = 15.0 min (client backends)" in (
        facts.splitlines()
    )


def test_only_a_walsender_running_is_no_long_query(
    tmp_path: Path,
) -> None:
    z = _archive(tmp_path, {
        "postgresql/running_activity.tsv": _activity(
            _WALSENDER,
            _client("2026-01-01 15:20:01.25 +0000 UTC", "idle"),
        ),
        "postgresql/running_activity_maxage.tsv": _MAXAGE,
    })
    parsed = read_and_parse(z)[0]
    assert "pg.activity.long_query" not in {
        f.rule_id for f in run_for_category("Workload", parsed)
    }


_TABLES_COLUMNS = (
    "schemaname", "tablename", "tableowner", "tablespace",
    "hasindexes", "hasrules", "hastriggers", "relpersistence",
    "reltuples", "relpages", "reloptions", "heap_size", "table_size",
    "toast_table", "toast_size", "relfrozenxid_age", "relminmxid_age",
    "n_live_tup", "n_dead_tup", "n_mod_since_analyze",
    "n_ins_since_vacuum", "last_vacuum", "last_autovacuum",
    "last_analyze", "last_autoanalyze", "last_vacuum_age_seconds",
    "last_autovacuum_age_seconds", "last_analyze_age_seconds",
    "last_autoanalyze_age_seconds",
)


def test_dead_rows_after_a_counter_restart_count_against_reltuples(
    tmp_path: Path,
) -> None:
    # tab1 has no vacuum or analyze on record: the counters started
    # after its last one, so n_live_tup holds only the rows inserted
    # since, while pg_class still knows the table's size.
    z = _archive(tmp_path, {
        "databases/appdb/tables.tsv": _tsv(
            _TABLES_COLUMNS,
            {
                "schemaname": "public", "tablename": "tab1",
                "relpersistence": "p", "reltuples": "1.2e+08",
                "relpages": "10000000", "n_live_tup": "650",
                "n_dead_tup": "135000",
                "n_mod_since_analyze": "135650",
                "n_ins_since_vacuum": "650",
            },
            {
                "schemaname": "public", "tablename": "tab2",
                "relpersistence": "p", "reltuples": "5000",
                "relpages": "100", "n_live_tup": "4000",
                "n_dead_tup": "6000", "n_mod_since_analyze": "6000",
                "n_ins_since_vacuum": "0",
                "last_autovacuum": "2026-01-01 10:00:00.5 +0000 UTC",
                "last_autovacuum_age_seconds": "3600",
            },
        ),
    })
    parsed = read_and_parse(z)[0]
    found = [
        f for f in run_for_category("Internals & I/O Health", parsed)
        if f.rule_id == "pg.health.tables_high_dead_rows"
    ]
    assert [(f.severity, f.title) for f in found] == [
        ("warning", "1 table(s) above 20% dead rows"),
    ]
    assert "appdb/public.tab2 60% dead" in found[0].detail
    assert "tab1" not in found[0].detail


_BLOAT_COLUMNS = (
    "current_database", "schemaname", "tablename",
    "table_bloat_ratio", "wastedbytes", "iname", "ituples", "ipages",
    "iotta",
)


def test_a_bloated_table_with_four_indexes_is_one_table(
    tmp_path: Path,
) -> None:
    # radar's bloat estimate joins each table to its indexes, so the
    # table's figures repeat on one row per index.
    z = _archive(tmp_path, {
        "databases/appdb/bloat.tsv": _tsv(_BLOAT_COLUMNS, *(
            {
                "current_database": "appdb", "schemaname": "public",
                "tablename": "tab1", "table_bloat_ratio": "640.5",
                "wastedbytes": "1073741824", "iname": iname,
                "ituples": "5000", "ipages": "120", "iotta": "100",
            }
            for iname in (
                "tab1_pkey", "tab1_name_idx", "tab1_uuid_key",
                "tab1_owner_idx",
            )
        )),
    })
    parsed = read_and_parse(z)[0]
    found = [
        f for f in run_for_category("Internals & I/O Health", parsed)
        if f.rule_id == "pg.health.bloat_high"
    ]
    assert [f.title for f in found] == [
        "1 table(s) with significant bloat",
    ]
    assert found[0].detail.count("appdb/public.tab1") == 1


def _cgroup(current: int, active_file: int, inactive_file: int) -> dict[
    str, str
]:
    return {
        "system/cgroup/memory_current.out": f"{current}\n",
        "system/cgroup/memory_max.out": "17179869184\n",
        "system/cgroup/memory_stat.out": (
            "anon 1000000000\n"
            f"file {active_file + inactive_file + 4500000000}\n"
            "kernel 500000000\n"
            "shmem 4500000000\n"
            f"active_file {active_file}\n"
            f"inactive_file {inactive_file}\n"
            "pgfault 123456\n"
        ),
    }


def test_page_cache_does_not_fill_a_cgroup(tmp_path: Path) -> None:
    # The kernel reclaims file page cache before the OOM killer
    # runs; shmem, PostgreSQL's shared_buffers, is not page cache.
    z = _archive(tmp_path, _cgroup(
        17_000_000_000, 4_300_000_000, 6_700_000_000
    ))
    parsed = read_and_parse(z)[0]
    assert "sys.cgroup_memory_near_limit" not in {
        f.rule_id for f in run_for_category("Host & OS", parsed)
    }
    facts = build_category_facts(_category("host_os"), parsed)
    assert facts is not None
    assert (
        "cgroup memory: 15.8 GiB / 16.0 GiB (99%), "
        "5.6 GiB excluding page cache"
    ) in facts.splitlines()


def test_a_cgroup_near_its_limit_without_page_cache(
    tmp_path: Path,
) -> None:
    z = _archive(tmp_path, _cgroup(
        16_000_000_000, 1_000_000_000, 500_000_000
    ))
    parsed = read_and_parse(z)[0]
    found = [
        f for f in run_for_category("Host & OS", parsed)
        if f.rule_id == "sys.cgroup_memory_near_limit"
    ]
    assert [(f.severity, f.title) for f in found] == [(
        "warning",
        "cgroup memory usage at 84% of limit, excluding page cache "
        "(13.5 / 16.0 GiB)",
    )]


_STATEMENT_COLUMNS = (
    "userid", "dbid", "query", "calls", "total_exec_time",
    "mean_exec_time", "max_exec_time", "rows",
)


def _statement(query: str, mean_ms: float) -> dict[str, str]:
    return {
        "userid": "10", "dbid": "16384", "query": query,
        "calls": "100", "total_exec_time": f"{mean_ms * 100}",
        "mean_exec_time": f"{mean_ms}", "max_exec_time": f"{mean_ms}",
        "rows": "100",
    }


def _slow_statement_ids(parsed: dict[str, object]) -> list[str]:
    return [
        f.rule_id for f in run_for_category("Workload", parsed)
        if f.rule_id == "pg.workload.slow_query_count_high"
    ]


def test_a_statement_list_over_a_mebibyte_is_read(
    tmp_path: Path,
) -> None:
    # radar keeps the top 100 statements, each with its full text;
    # literal-heavy statements make the file large.
    in_list = "1, " * 4000 + "1)"
    statements = _tsv(_STATEMENT_COLUMNS, *(
        _statement(
            f"SELECT * FROM tab1 WHERE c{i} IN ({in_list}",
            1500.0 if i < 11 else 5.0,
        )
        for i in range(100)
    ))
    assert len(statements) > 1024 * 1024
    z = _archive(tmp_path, {
        "postgresql/stat_statements_calls.tsv": statements,
    })
    parsed = read_and_parse(z)[0]
    assert len(parsed["pg.stat_statements.calls"]) == 100
    assert _slow_statement_ids(parsed) == [
        "pg.workload.slow_query_count_high",
    ]


def test_a_query_text_over_the_csv_field_limit_is_cut_short(
    tmp_path: Path,
) -> None:
    # Python's csv refuses a field over 128 KiB unless told otherwise.
    long_query = "SELECT * FROM tab1 WHERE id IN (" + "1, " * 70000 + "1)"
    statements = _tsv(
        _STATEMENT_COLUMNS,
        _statement(long_query, 2000.0),
        *(_statement(f"SELECT {i} FROM tab1", 1500.0) for i in range(10)),
    )
    assert len(long_query) > 128 * 1024
    assert len(statements) < 1024 * 1024
    z = _archive(tmp_path, {
        "postgresql/stat_statements_calls.tsv": statements,
    })
    parsed = read_and_parse(z)[0]
    rows = parsed["pg.stat_statements.calls"]
    assert len(rows) == 11
    assert rows[0].query == long_query[:1024]
    assert _slow_statement_ids(parsed) == [
        "pg.workload.slow_query_count_high",
    ]


_XACT_MAXAGE = (
    "max_query_age\tmax_xact_age\tmax_backend_age\t"
    "max_lock_wait_age\n"
    "00:01:00\t00:01:00\t00:01:00\t\n"
)


def _rate_archive(
    tmp_path: Path, appdb_reset: str
) -> dict[str, object]:
    # Collected at 2026-01-01 01:00 by the server's clock. bgwriter's
    # counters were reset an hour before that, appdb's at
    # *appdb_reset*, and the postgres database's never.
    z = _archive(tmp_path, {
        "postgresql/bgwriter.tsv": (
            "buffers_clean\tmaxwritten_clean\tbuffers_alloc\t"
            "stats_reset\n"
            "0\t0\t0\t2026-01-01 00:00:00 +0000 UTC\n"
        ),
        "postgresql/databases_xact.tsv": (
            "datname\txact_commit\txact_rollback\n"
            "appdb\t7000000\t200000\n"
            "postgres\t90000000\t0\n"
        ),
        "databases/appdb/stat_database.tsv": (
            "datname\tconflicts\tdeadlocks\ttemp_files\t"
            "temp_bytes\tstats_reset\n"
            f"appdb\t0\t0\t0\t0\t{appdb_reset}\n"
        ),
        "databases/postgres/stat_database.tsv": (
            "datname\tconflicts\tdeadlocks\ttemp_files\t"
            "temp_bytes\tstats_reset\n"
            "postgres\t0\t0\t0\t0\t\n"
        ),
        "postgresql/running_activity.tsv": _activity(
            _client("2026-01-01 00:59:00 +0000 UTC", "active"),
        ),
        "postgresql/running_activity_maxage.tsv": _XACT_MAXAGE,
    })
    return read_and_parse(z)[0]


def _rate_titles(parsed: dict[str, object]) -> list[str]:
    return [
        f.title for f in run_for_category("Workload", parsed)
        if f.rule_id == "pg.workload.xact_rate_high"
    ]


def test_each_database_rate_runs_from_its_own_reset(
    tmp_path: Path,
) -> None:
    # 7.2 million transactions in appdb's hour from its reset to the
    # collection. The postgres database has no reset on record, so
    # its counters could cover any length of time: it is left out.
    parsed = _rate_archive(tmp_path, "2026-01-01 00:00:00 +0000 UTC")
    assert _rate_titles(parsed) == [
        "Sustained transaction rate is 2,000 TPS",
    ]


def test_no_rate_without_a_database_reset_on_record(
    tmp_path: Path,
) -> None:
    # bgwriter's reset says nothing about when pg_stat_database's
    # counters started, so it cannot stand in for them.
    parsed = _rate_archive(tmp_path, "")
    assert _rate_titles(parsed) == []
    facts = build_category_facts(_category("pg_workload"), parsed)
    assert facts is not None
    assert "since" not in next(
        line for line in facts.splitlines()
        if line.startswith("Cluster transactions")
    )


def test_slow_statements_are_counted_across_all_three_lists(
    tmp_path: Path,
) -> None:
    # The list by calls ranks frequent statements; slow ones rank by
    # maximum and by total time. Each statement counts once.
    slow = [
        _statement(f"SELECT * FROM tab2 WHERE c = {i}", 1500.0)
        for i in range(11)
    ]
    fast = [_statement(f"SELECT {i} FROM tab1", 2.0) for i in range(99)]
    z = _archive(tmp_path, {
        "postgresql/stat_statements_calls.tsv": _tsv(
            _STATEMENT_COLUMNS, slow[0], *fast
        ),
        "postgresql/stat_statements_max_time.tsv": _tsv(
            _STATEMENT_COLUMNS, *slow[:8]
        ),
        "postgresql/stat_statements_total_time.tsv": _tsv(
            _STATEMENT_COLUMNS, *slow[5:]
        ),
    })
    parsed = read_and_parse(z)[0]
    found = [
        f for f in run_for_category("Workload", parsed)
        if f.rule_id == "pg.workload.slow_query_count_high"
    ]
    assert [f.title for f in found] == [
        "11 statements with mean exec time > 1 s",
    ]


def test_slow_statements_that_differ_past_the_cut_count_apart(
    tmp_path: Path,
) -> None:
    # Eleven IN-list lengths of one statement, each its own entry in
    # pg_stat_statements, all alike in their first 1024 characters.
    head = "SELECT * FROM tab1 WHERE id IN (" + "$1, " * 300
    z = _archive(tmp_path, {
        "postgresql/stat_statements_max_time.tsv": _tsv(
            _STATEMENT_COLUMNS, *(
                _statement(
                    head + ", ".join(f"${n}" for n in range(301, 302 + i))
                    + ")",
                    1500.0,
                )
                for i in range(11)
            ),
        ),
    })
    parsed = read_and_parse(z)[0]
    found = [
        f for f in run_for_category("Workload", parsed)
        if f.rule_id == "pg.workload.slow_query_count_high"
    ]
    assert [f.title for f in found] == [
        "11 statements with mean exec time > 1 s",
    ]
