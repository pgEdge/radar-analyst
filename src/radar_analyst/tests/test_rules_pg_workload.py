"""Tests for cluster-level Workload rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from radar_analyst.parse.databases import (
    DatabaseXactStats,
    DbStatDatabase,
)
from radar_analyst.parse.pg_activity import (
    PgActivity,
    PreparedXacts,
    RunningActivityMaxage,
)
from radar_analyst.parse.pg_internals import PgBgwriter
from radar_analyst.parse.pg_settings import PgSetting, PgSettings
from radar_analyst.rules.pg_workload import (
    connection_saturation,
    long_query_present,
    long_xact_present,
    prepared_xacts_present,
    rollback_ratio_high,
    xact_rate_high,
)


def _settings(max_connections: int) -> PgSettings:
    return PgSettings(
        all={
            "max_connections": PgSetting(
                name="max_connections",
                setting=str(max_connections),
                unit="",
                category="",
                short_desc="",
            )
        }
    )


# ---------------------------------------------------------------
# long_xact_present
# ---------------------------------------------------------------


def test_long_xact_silent_below_warning_threshold() -> None:
    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_xact_age_s=59 * 60.0  # 59 min
        )
    }
    assert long_xact_present(parsed) == []


def test_long_xact_warning_at_one_hour() -> None:
    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_xact_age_s=60 * 60.0
        )
    }
    out = long_xact_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.activity.long_xact"


def test_long_xact_critical_at_two_hours() -> None:
    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_xact_age_s=2 * 3600.0
        )
    }
    out = long_xact_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"


def test_long_xact_warning_just_under_two_hours() -> None:
    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_xact_age_s=2 * 3600.0 - 1
        )
    }
    out = long_xact_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_long_xact_silent_when_no_data() -> None:
    assert long_xact_present({}) == []
    assert (
        long_xact_present(
            {
                "pg.running_activity_maxage": RunningActivityMaxage(
                    max_xact_age_s=None
                )
            }
        )
        == []
    )


# ---------------------------------------------------------------
# long_query_present
# ---------------------------------------------------------------


def _long_query(age_s: float) -> dict[str, object]:
    # The oldest non-idle session is a client's query.
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_query_age_s=age_s
        ),
        "pg.running_activity": PgActivity(
            oldest_query_start=start,
            oldest_client_query_start=start,
        ),
    }


def test_long_query_silent_under_threshold() -> None:
    assert long_query_present(_long_query(9 * 60.0)) == []


def test_long_query_warns_at_10min() -> None:
    out = long_query_present(_long_query(10 * 60.0))
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_long_query_critical_at_30min() -> None:
    out = long_query_present(_long_query(30 * 60.0))
    assert len(out) == 1
    assert out[0].severity == "critical"


def test_long_query_measures_the_client_not_a_walsender() -> None:
    parsed = _long_query(15 * 3600.0)
    parsed["pg.running_activity"] = PgActivity(
        oldest_query_start=datetime(2026, 1, 1, tzinfo=UTC),
        oldest_client_query_start=datetime(
            2026, 1, 1, 14, 40, tzinfo=UTC
        ),
    )
    out = long_query_present(parsed)
    assert [(f.severity, f.title) for f in out] == [(
        "warning",
        "Oldest running query has been executing for 20.0 min",
    )]


def test_long_query_silent_without_the_session_snapshot() -> None:
    parsed = _long_query(30 * 60.0)
    del parsed["pg.running_activity"]
    assert long_query_present(parsed) == []


# ---------------------------------------------------------------
# prepared_xacts_present
# ---------------------------------------------------------------


def test_prepared_xacts_silent_when_zero() -> None:
    parsed = {"pg.prepared_xacts": PreparedXacts()}
    assert prepared_xacts_present(parsed) == []


def test_prepared_xacts_warns_when_present() -> None:
    parsed = {
        "pg.prepared_xacts": PreparedXacts(
            total=2, oldest_gid="_g"
        )
    }
    out = prepared_xacts_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert "_g" in out[0].title


def test_prepared_xacts_silent_when_missing() -> None:
    assert prepared_xacts_present({}) == []


# ---------------------------------------------------------------
# connection_saturation
# ---------------------------------------------------------------


def test_connection_saturation_silent_below_80pct() -> None:
    parsed = {
        "pg.running_activity": PgActivity(total=79),
        "pg.settings": _settings(100),
    }
    assert connection_saturation(parsed) == []


def test_connection_saturation_warns_at_80pct() -> None:
    parsed = {
        "pg.running_activity": PgActivity(total=80),
        "pg.settings": _settings(100),
    }
    out = connection_saturation(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert "80%" in out[0].title or "80 %" in out[0].title


def test_connection_saturation_critical_at_95pct() -> None:
    parsed = {
        "pg.running_activity": PgActivity(total=95),
        "pg.settings": _settings(100),
    }
    out = connection_saturation(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"


def test_connection_saturation_silent_when_no_settings() -> None:
    parsed = {"pg.running_activity": PgActivity(total=95)}
    assert connection_saturation(parsed) == []


def test_connection_saturation_silent_when_no_activity() -> None:
    parsed = {"pg.settings": _settings(100)}
    assert connection_saturation(parsed) == []


def test_connection_saturation_silent_on_garbage_max() -> None:
    parsed = {
        "pg.running_activity": PgActivity(total=10),
        "pg.settings": PgSettings(
            all={
                "max_connections": PgSetting(
                    name="max_connections",
                    setting="not-a-number",
                    unit="",
                    category="",
                    short_desc="",
                )
            }
        ),
    }
    assert connection_saturation(parsed) == []


# ---------------------------------------------------------------
# rollback_ratio_high (cluster-wide)
# ---------------------------------------------------------------

def _xact(name: str, commits: int, rollbacks: int
          ) -> DatabaseXactStats:
    return DatabaseXactStats(
        datname=name,
        xact_commit=commits,
        xact_rollback=rollbacks,
    )


def test_rollback_ratio_high_fires_above_5pct() -> None:
    parsed = {
        "pg.databases_xact": {
            "mydb": _xact("mydb", 900, 100),  # 10%
        }
    }
    out = rollback_ratio_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.workload.rollback_ratio_high"


def test_rollback_ratio_high_silent_below_threshold() -> None:
    parsed = {
        "pg.databases_xact": {
            "mydb": _xact("mydb", 960, 40),  # 4%
        }
    }
    assert rollback_ratio_high(parsed) == []


def test_rollback_ratio_high_silent_low_volume() -> None:
    parsed = {
        "pg.databases_xact": {
            "mydb": _xact("mydb", 5, 5),  # 50% but < 500
        }
    }
    assert rollback_ratio_high(parsed) == []


def test_rollback_ratio_high_sums_across_dbs() -> None:
    parsed = {
        "pg.databases_xact": {
            "a": _xact("a", 400, 100),  # 20%
            "b": _xact("b", 400, 100),  # 20%
        }
    }
    out = rollback_ratio_high(parsed)
    assert len(out) == 1


def test_rollback_ratio_high_silent_when_no_data() -> None:
    assert rollback_ratio_high({}) == []


# ---------------------------------------------------------------
# xact_rate_high (cluster-wide, bgwriter.stats_reset baseline)
# ---------------------------------------------------------------

def _bgwriter(
    stats_reset: datetime | None = None,
) -> PgBgwriter:
    return PgBgwriter(
        checkpoints_timed=None,
        checkpoints_req=None,
        buffers_checkpoint=None,
        buffers_clean=0,
        maxwritten_clean=0,
        buffers_alloc=0,
        buffers_backend=None,
        buffers_backend_fsync=None,
        stats_reset=stats_reset,
    )


_RESET = datetime(2026, 1, 1, tzinfo=UTC)


def _collected(at: datetime) -> dict[str, object]:
    # radar's own session is the oldest non-idle one, its query just
    # begun when radar read pg_stat_activity.
    return {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_query_age_s=0.0
        ),
        "pg.running_activity": PgActivity(oldest_query_start=at),
    }


def _reset(name: str, at: datetime | None) -> DbStatDatabase:
    return DbStatDatabase(
        datname=name, conflicts=0, deadlocks=0, temp_files=0,
        temp_bytes=0, stats_reset=at,
    )


def test_xact_rate_high_fires_above_threshold() -> None:
    # 4M xacts in the hour from mydb's reset to the collection.
    parsed = {
        **_collected(_RESET + timedelta(hours=1)),
        "pg.databases_xact": {
            "mydb": _xact("mydb", 4_000_000, 0),
        },
        "pg.db.stat_database": {"mydb": _reset("mydb", _RESET)},
    }
    out = xact_rate_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.workload.xact_rate_high"
    assert out[0].title == "Sustained transaction rate is 1,111 TPS"


def test_xact_rate_high_sums_each_database_over_its_own_window() -> None:
    # 2M in one hour plus 4M in two hours: 1,111 TPS together. The
    # database with no reset on record is left out.
    parsed = {
        **_collected(_RESET + timedelta(hours=2)),
        "pg.databases_xact": {
            "db1": _xact("db1", 2_000_000, 0),
            "db2": _xact("db2", 4_000_000, 0),
            "db3": _xact("db3", 900_000_000, 0),
        },
        "pg.db.stat_database": {
            "db1": _reset("db1", _RESET + timedelta(hours=1)),
            "db2": _reset("db2", _RESET),
            "db3": _reset("db3", None),
        },
    }
    out = xact_rate_high(parsed)
    assert [f.title for f in out] == [
        "Sustained transaction rate is 1,111 TPS",
    ]


def test_xact_rate_high_silent_below_threshold() -> None:
    parsed = {
        **_collected(_RESET + timedelta(hours=1)),
        "pg.databases_xact": {
            "mydb": _xact("mydb", 100, 0),
        },
        "pg.db.stat_database": {"mydb": _reset("mydb", _RESET)},
    }
    assert xact_rate_high(parsed) == []


def test_xact_rate_high_silent_without_a_reset_on_record() -> None:
    # The counters could cover any length of time: no rate, and
    # bgwriter's reset does not stand in for the database's.
    parsed = {
        **_collected(_RESET + timedelta(hours=1)),
        "pg.databases_xact": {
            "mydb": _xact("mydb", 10_000_000, 0),
        },
        "pg.db.stat_database": {"mydb": _reset("mydb", None)},
        "pg.bgwriter": _bgwriter(_RESET),
    }
    assert xact_rate_high(parsed) == []


def test_xact_rate_high_silent_without_the_collection_time() -> None:
    # The archive does not say when it was collected. Measured to the
    # analyst's own clock this would be 1,111 TPS; it is no rate.
    parsed = {
        "pg.databases_xact": {
            "mydb": _xact("mydb", 4_000_000, 0),
        },
        "pg.db.stat_database": {
            "mydb": _reset("mydb", datetime.now(UTC) - timedelta(hours=1)),
        },
    }
    assert xact_rate_high(parsed) == []


def test_xact_rate_high_silent_when_no_data() -> None:
    assert xact_rate_high({}) == []


# ----------------------------------------------------------------------
# connections_without_ssl
# ----------------------------------------------------------------------


def test_connections_without_ssl_silent_when_no_data() -> None:
    from radar_analyst.rules.pg_workload import (
        connections_without_ssl,
    )

    assert connections_without_ssl({}) == []


def test_connections_without_ssl_silent_when_all_secure() -> None:
    from radar_analyst.parse.pg_stat_ssl import (
        SslConnection,
        StatSsl,
    )
    from radar_analyst.rules.pg_workload import (
        connections_without_ssl,
    )

    parsed = {
        "pg.stat_ssl": StatSsl(
            rows=[
                SslConnection(
                    pid="1",
                    ssl=True,
                    client_addr="10.0.0.1",
                ),
            ]
        )
    }
    assert connections_without_ssl(parsed) == []


def test_connections_without_ssl_warns_on_remote_plain() -> None:
    from radar_analyst.parse.pg_stat_ssl import (
        SslConnection,
        StatSsl,
    )
    from radar_analyst.rules.pg_workload import (
        connections_without_ssl,
    )

    parsed = {
        "pg.stat_ssl": StatSsl(
            rows=[
                SslConnection(
                    pid="1",
                    ssl=False,
                    client_addr="10.0.0.5",
                    application_name="legacy_app",
                ),
            ]
        )
    }
    findings = connections_without_ssl(parsed)
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "pg.workload.connections_without_ssl"
    assert f.severity == "warning"
    assert "legacy_app" in f.detail


def test_connections_without_ssl_info_for_local_only() -> None:
    from radar_analyst.parse.pg_stat_ssl import (
        SslConnection,
        StatSsl,
    )
    from radar_analyst.rules.pg_workload import (
        connections_without_ssl,
    )

    parsed = {
        "pg.stat_ssl": StatSsl(
            rows=[
                SslConnection(
                    pid="1",
                    ssl=False,
                    client_addr="",
                    application_name="psql",
                ),
            ]
        )
    }
    findings = connections_without_ssl(parsed)
    assert findings[0].severity == "info"


# ---------------------------------------------------------------
# slow_query_count_high
# ---------------------------------------------------------------


def _stmt(mean_ms: float, calls: int = 100, query: str = "q") -> object:
    from radar_analyst.parse.pg_stat_statements import StatementRow

    return StatementRow(
        userid="10",
        dbid="16400",
        query=query,
        calls=calls,
        total_exec_time=mean_ms * calls,
        mean_exec_time=mean_ms,
        max_exec_time=mean_ms * 1.5,
        rows=calls,
    )


def test_slow_query_silent_when_no_data() -> None:
    from radar_analyst.rules.pg_workload import slow_query_count_high

    assert slow_query_count_high({}) == []
    assert slow_query_count_high(
        {"pg.stat_statements.calls": []}
    ) == []


def test_slow_query_silent_below_count_threshold() -> None:
    # 10 slow statements isn't enough: the rule fires above 10.
    from radar_analyst.rules.pg_workload import slow_query_count_high

    parsed = {
        "pg.stat_statements.calls": [
            _stmt(mean_ms=1500, query=f"q{i}") for i in range(10)
        ],
    }
    assert slow_query_count_high(parsed) == []


def test_slow_query_warns_above_eleven_slow() -> None:
    from radar_analyst.rules.pg_workload import slow_query_count_high

    parsed = {
        "pg.stat_statements.calls": [
            _stmt(mean_ms=1200, query=f"q{i}") for i in range(15)
        ],
    }
    findings = slow_query_count_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "15" in findings[0].title


def test_slow_query_silent_when_all_fast() -> None:
    # 50 statements all under 1 s: nothing slow.
    from radar_analyst.rules.pg_workload import slow_query_count_high

    parsed = {
        "pg.stat_statements.calls": [
            _stmt(mean_ms=500, query=f"q{i}") for i in range(50)
        ],
    }
    assert slow_query_count_high(parsed) == []


# ---------------------------------------------------------------
# lock_wait_time_high
# ---------------------------------------------------------------


def test_lock_wait_silent_when_no_data() -> None:
    from radar_analyst.rules.pg_workload import lock_wait_time_high

    assert lock_wait_time_high({}) == []


def test_lock_wait_silent_on_pre_0_5_0_zip() -> None:
    # radar 0.4.1 zips have RunningActivityMaxage but no
    # max_lock_wait_age column → field is None.
    from radar_analyst.rules.pg_workload import lock_wait_time_high

    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_query_age_s=1.0,
            max_lock_wait_age_s=None,
        )
    }
    assert lock_wait_time_high(parsed) == []


def test_lock_wait_silent_below_threshold() -> None:
    from radar_analyst.rules.pg_workload import lock_wait_time_high

    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_lock_wait_age_s=29.0
        )
    }
    assert lock_wait_time_high(parsed) == []


def test_lock_wait_warns_at_30_seconds() -> None:
    from radar_analyst.rules.pg_workload import lock_wait_time_high

    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_lock_wait_age_s=30.0
        )
    }
    findings = lock_wait_time_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].rule_id == "pg.activity.lock_wait_time"


def test_lock_wait_critical_at_5_minutes() -> None:
    from radar_analyst.rules.pg_workload import lock_wait_time_high

    parsed = {
        "pg.running_activity_maxage": RunningActivityMaxage(
            max_lock_wait_age_s=300.0
        )
    }
    findings = lock_wait_time_high(parsed)
    assert len(findings) == 1
    assert findings[0].severity == "critical"
