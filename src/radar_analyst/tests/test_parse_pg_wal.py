"""Tests for pg_wal parsers (archiver + replication_slots)."""

from radar_analyst.parse.pg_wal import (
    parse_archiver,
    parse_replication_slots,
)


def test_archiver_parses_counts_and_timestamps() -> None:
    tsv = (
        "archived_count\tlast_archived_wal\t"
        "last_archived_time\tfailed_count\t"
        "last_failed_wal\tlast_failed_time\tstats_reset\n"
        "1234\t00000001000000000000001A\t"
        "2026-04-15 12:00:00+00\t5\t"
        "00000001000000000000001B\t"
        "2026-04-15 11:30:00+00\t2026-01-01 00:00:00+00\n"
    )
    a = parse_archiver(tsv.encode())
    assert a is not None
    assert a.archived_count == 1234
    assert a.failed_count == 5
    assert a.has_recent_failure is False  # success newer


def test_archiver_detects_recent_failure() -> None:
    tsv = (
        "archived_count\tlast_archived_wal\t"
        "last_archived_time\tfailed_count\t"
        "last_failed_wal\tlast_failed_time\tstats_reset\n"
        "100\t00000001000000000000000A\t"
        "2026-04-15 10:00:00+00\t3\t"
        "00000001000000000000000B\t"
        "2026-04-15 12:00:00+00\t2026-01-01 00:00:00+00\n"
    )
    a = parse_archiver(tsv.encode())
    assert a is not None
    assert a.has_recent_failure is True


def test_archiver_empty_returns_none() -> None:
    assert parse_archiver(b"") is None


def test_replication_slots_parses_active_flag() -> None:
    tsv = (
        "slot_name\tslot_type\tdatabase\tactive\t"
        "restart_lsn\twal_status\n"
        "standby1\tphysical\t\tt\t0/1A000000\treserved\n"
        "orphan\tlogical\tappdb\tf\t0/12000000\tlost\n"
    )
    s = parse_replication_slots(tsv.encode())
    assert len(s.all) == 2
    assert len(s.inactive) == 1
    assert s.inactive[0].slot_name == "orphan"
    assert len(s.lost) == 1
    assert s.lost[0].slot_name == "orphan"
