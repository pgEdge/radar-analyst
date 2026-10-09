"""Tests for pg_activity parsers."""

from datetime import UTC, datetime

from radar_analyst.parse.pg_activity import (
    PgActivity,
    RunningActivityMaxage,
    collected_at,
    oldest_client_query_age_s,
    parse_blocking_locks_count,
    parse_connection_summary,
    parse_pg_interval_seconds,
    parse_prepared_xacts,
    parse_running_activity,
    parse_running_activity_maxage,
    parse_running_locks,
    parse_waits_sample,
)


def test_running_activity_counts_states_and_wait_events() -> None:
    tsv = (
        "pid\tstate\twait_event_type\twait_event\n"
        "1\tactive\tLock\ttransactionid\n"
        "2\tidle\t\t\n"
        "3\tidle\t\t\n"
        "4\tidle in transaction\tClient\tClientRead\n"
        "5\tidle in transaction (aborted)\t\t\n"
    )
    a = parse_running_activity(tsv.encode())
    assert a.total == 5
    assert a.by_state == {
        "active": 1,
        "idle": 2,
        "idle in transaction": 1,
        "idle in transaction (aborted)": 1,
    }
    assert a.idle_in_transaction == 2
    assert a.wait_events == {
        "transactionid": 1,
        "ClientRead": 1,
    }


def test_running_activity_empty() -> None:
    a = parse_running_activity(b"")
    assert a.total == 0


def test_running_activity_oldest_query_starts() -> None:
    # The non-idle minimum covers what radar's max_query_age does;
    # the client minimum only queries a client backend is running.
    tsv = (
        "pid\tstate\tquery_start\tbackend_type\n"
        "1\tidle\t2026-01-01 00:00:00 +0000 UTC\tclient backend\n"
        "2\tactive\t2026-01-01 01:00:00 +0000 UTC\twalsender\n"
        "3\tidle in transaction\t2026-01-01 02:00:00 +0000 UTC\t"
        "client backend\n"
        "4\tactive\t2026-01-01 03:00:00.5 +0000 UTC\tclient backend\n"
        "5\t\t\tbackground writer\n"
    )
    a = parse_running_activity(tsv.encode())
    assert a.oldest_query_start == datetime(
        2026, 1, 1, 1, tzinfo=UTC
    )
    assert a.oldest_client_query_start == datetime(
        2026, 1, 1, 3, 0, 0, 500000, tzinfo=UTC
    )


def test_collected_at_is_the_oldest_query_start_plus_its_age() -> None:
    m = RunningActivityMaxage(max_query_age_s=3600.0)
    a = PgActivity(oldest_query_start=datetime(2026, 1, 1, tzinfo=UTC))
    assert collected_at(m, a) == datetime(2026, 1, 1, 1, tzinfo=UTC)
    assert collected_at(None, a) is None
    assert collected_at(m, None) is None
    assert collected_at(m, PgActivity()) is None


def test_oldest_client_query_age_moves_max_query_age() -> None:
    m = RunningActivityMaxage(max_query_age_s=3600.0)
    a = PgActivity(
        oldest_query_start=datetime(2026, 1, 1, tzinfo=UTC),
        oldest_client_query_start=datetime(
            2026, 1, 1, 0, 50, tzinfo=UTC
        ),
    )
    assert oldest_client_query_age_s(m, a) == 600.0


def test_oldest_client_query_age_none_without_a_client_query() -> None:
    m = RunningActivityMaxage(max_query_age_s=3600.0)
    walsender_only = PgActivity(
        oldest_query_start=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert oldest_client_query_age_s(m, walsender_only) is None
    assert oldest_client_query_age_s(m, None) is None
    assert oldest_client_query_age_s(None, walsender_only) is None


def test_blocking_locks_count_counts_rows() -> None:
    tsv = (
        "blocked_pid\tblocker_pid\n"
        "1\t2\n"
        "3\t4\n"
    )
    assert parse_blocking_locks_count(tsv.encode()) == 2
    assert parse_blocking_locks_count(b"") == 0


# ---------------------------------------------------------------
# parse_pg_interval_seconds
# ---------------------------------------------------------------


def test_pg_interval_simple_hms() -> None:
    assert parse_pg_interval_seconds("00:00:00") == 0.0
    assert parse_pg_interval_seconds("00:00:01") == 1.0
    assert parse_pg_interval_seconds("00:01:00") == 60.0
    assert parse_pg_interval_seconds("01:00:00") == 3600.0
    assert parse_pg_interval_seconds("01:02:03") == 3723.0


def test_pg_interval_microseconds() -> None:
    v = parse_pg_interval_seconds("00:00:00.000029")
    assert v is not None
    assert abs(v - 0.000029) < 1e-9


def test_pg_interval_with_days() -> None:
    # Postgres prints "N day[s] HH:MM:SS" or "N day[s] HH:MM:SS.ffffff".
    assert parse_pg_interval_seconds("1 day 00:00:00") == 86400.0
    assert (
        parse_pg_interval_seconds("2 days 01:00:00") == 2 * 86400 + 3600
    )


def test_pg_interval_negative() -> None:
    assert parse_pg_interval_seconds("-00:00:01") == -1.0


def test_pg_interval_empty_or_garbage() -> None:
    assert parse_pg_interval_seconds("") is None
    assert parse_pg_interval_seconds(None) is None
    assert parse_pg_interval_seconds("not-an-interval") is None


# ---------------------------------------------------------------
# parse_running_activity_maxage
# ---------------------------------------------------------------


def test_running_activity_maxage_real_radar_columns() -> None:
    # Single row file, three interval columns.
    tsv = (
        "max_query_age\tmax_xact_age\tmax_backend_age\n"
        "00:00:00.000029\t00:00:00.000149\t00:00:19.738653\n"
    )
    out = parse_running_activity_maxage(tsv.encode())
    assert out is not None
    assert out.max_query_age_s is not None
    assert abs(out.max_query_age_s - 0.000029) < 1e-9
    assert out.max_xact_age_s is not None
    assert abs(out.max_xact_age_s - 0.000149) < 1e-9
    assert out.max_backend_age_s is not None
    assert abs(out.max_backend_age_s - 19.738653) < 1e-3


def test_running_activity_maxage_long_xact() -> None:
    tsv = (
        "max_query_age\tmax_xact_age\tmax_backend_age\n"
        "1 day 02:30:00\t1 day 02:30:00\t2 days 00:00:00\n"
    )
    out = parse_running_activity_maxage(tsv.encode())
    assert out is not None
    assert out.max_xact_age_s == 86400 + 2 * 3600 + 30 * 60
    assert out.max_backend_age_s == 2 * 86400


def test_running_activity_maxage_pre_0_5_0_lacks_lock_wait() -> None:
    # Older zips don't carry max_lock_wait_age: parser falls
    # back to None for that field but parses the rest cleanly.
    tsv = (
        "max_query_age\tmax_xact_age\tmax_backend_age\n"
        "00:00:01\t00:00:02\t00:00:03\n"
    )
    out = parse_running_activity_maxage(tsv.encode())
    assert out is not None
    assert out.max_query_age_s == 1.0
    assert out.max_lock_wait_age_s is None


def test_running_activity_maxage_with_lock_wait() -> None:
    # Radar 0.5.0+ adds max_lock_wait_age to the same row.
    tsv = (
        "max_query_age\tmax_xact_age\tmax_backend_age\t"
        "max_lock_wait_age\n"
        "00:00:01\t00:00:02\t00:00:03\t00:01:30\n"
    )
    out = parse_running_activity_maxage(tsv.encode())
    assert out is not None
    assert out.max_lock_wait_age_s == 90.0


def test_running_activity_maxage_lock_wait_null_when_no_lockers() -> None:
    # No backend currently waiting on a lock → aggregate returns
    # NULL → empty TSV value → parsed as None.
    tsv = (
        "max_query_age\tmax_xact_age\tmax_backend_age\t"
        "max_lock_wait_age\n"
        "00:00:01\t00:00:02\t00:00:03\t\n"
    )
    out = parse_running_activity_maxage(tsv.encode())
    assert out is not None
    assert out.max_lock_wait_age_s is None


def test_running_activity_maxage_all_null() -> None:
    # When pg_stat_activity is empty (highly unusual but possible),
    # the aggregates return NULL → empty fields in the TSV.
    tsv = (
        "max_query_age\tmax_xact_age\tmax_backend_age\n"
        "\t\t\n"
    )
    out = parse_running_activity_maxage(tsv.encode())
    assert out is not None
    assert out.max_query_age_s is None
    assert out.max_xact_age_s is None
    assert out.max_backend_age_s is None


def test_running_activity_maxage_empty() -> None:
    assert parse_running_activity_maxage(b"") is None
    assert (
        parse_running_activity_maxage(
            b"max_query_age\tmax_xact_age\tmax_backend_age\n"
        )
        is None
    )


# ---------------------------------------------------------------
# parse_waits_sample
# ---------------------------------------------------------------


def test_waits_sample_counts_by_event_and_type() -> None:
    tsv = (
        "pid\twait_event_type\twait_event\tstate\tquery\n"
        "1\tActivity\tIoWorkerMain\t\t\n"
        "2\tActivity\tIoWorkerMain\t\t\n"
        "3\tActivity\tCheckpointerMain\t\t\n"
        "4\tClient\tClientRead\tidle\tSELECT 1\n"
    )
    out = parse_waits_sample(tsv.encode())
    assert out.total == 4
    assert out.by_event_type == {"Activity": 3, "Client": 1}
    assert out.by_event == {
        "IoWorkerMain": 2,
        "CheckpointerMain": 1,
        "ClientRead": 1,
    }


def test_waits_sample_empty() -> None:
    out = parse_waits_sample(b"")
    assert out.total == 0
    assert out.by_event_type == {}
    assert out.by_event == {}


# ---------------------------------------------------------------
# parse_connection_summary
# ---------------------------------------------------------------


def test_connection_summary_real_radar_shape() -> None:
    # Pre-aggregated grid: state × wait_event_type × count.
    tsv = (
        "state\twait_event_type\tcount\n"
        "\tActivity\t8\n"
        "active\t\t1\n"
        "idle\tClient\t1\n"
    )
    out = parse_connection_summary(tsv.encode())
    assert out.total == 10
    # Preserved as a list of (state, wait_event_type, count) triples
    # for easy rendering.
    assert ("", "Activity", 8) in out.cells
    assert ("active", "", 1) in out.cells
    assert ("idle", "Client", 1) in out.cells
    # Aggregates derived for rule input:
    assert out.by_state == {"(unknown)": 8, "active": 1, "idle": 1}
    assert out.by_wait_event_type == {
        "Activity": 8,
        "(none)": 1,
        "Client": 1,
    }


def test_connection_summary_empty() -> None:
    out = parse_connection_summary(b"")
    assert out.total == 0


# ---------------------------------------------------------------
# parse_running_locks
# ---------------------------------------------------------------


def test_running_locks_distribution() -> None:
    tsv = (
        "locktype\tdatabase\trelation\tmode\tgranted\n"
        "relation\t5\t12073\tAccessShareLock\ttrue\n"
        "virtualxid\t\t\tExclusiveLock\ttrue\n"
        "relation\t5\t12073\tRowExclusiveLock\ttrue\n"
    )
    out = parse_running_locks(tsv.encode())
    assert out.total == 3
    assert out.by_mode == {
        "AccessShareLock": 1,
        "ExclusiveLock": 1,
        "RowExclusiveLock": 1,
    }
    assert out.by_locktype == {"relation": 2, "virtualxid": 1}


def test_running_locks_empty() -> None:
    out = parse_running_locks(b"")
    assert out.total == 0


# ---------------------------------------------------------------
# parse_prepared_xacts
# ---------------------------------------------------------------


def test_prepared_xacts_empty_real_shape() -> None:
    tsv = "transaction\tgid\tprepared\towner\tdatabase\n"
    out = parse_prepared_xacts(tsv.encode(), now_iso=None)
    assert out.total == 0
    assert out.oldest_age_s is None


def test_prepared_xacts_counts_and_oldest_age() -> None:
    # Only count + oldest "prepared" timestamp matter for rules.
    # Oldest age is computed against an injectable "now" so the
    # test is deterministic.
    tsv = (
        "transaction\tgid\tprepared\towner\tdatabase\n"
        "9001\t_some_gid_a\t2026-04-15 10:00:00+00\tpg\tmydb\n"
        "9002\t_some_gid_b\t2026-04-15 09:00:00+00\tpg\tmydb\n"
    )
    out = parse_prepared_xacts(
        tsv.encode(), now_iso="2026-04-15 11:00:00+00"
    )
    assert out.total == 2
    # Oldest is the 09:00 row → 2 hours.
    assert out.oldest_age_s == 2 * 3600.0
    assert out.oldest_gid == "_some_gid_b"


def test_prepared_xacts_no_now_means_no_age() -> None:
    tsv = (
        "transaction\tgid\tprepared\towner\tdatabase\n"
        "9001\t_g\t2026-04-15 10:00:00+00\tpg\tmydb\n"
    )
    out = parse_prepared_xacts(tsv.encode(), now_iso=None)
    assert out.total == 1
    assert out.oldest_age_s is None
    assert out.oldest_gid == "_g"
