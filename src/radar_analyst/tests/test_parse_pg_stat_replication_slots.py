"""Tests for parse/pg_stat_replication_slots.py."""

from radar_analyst.parse.pg_stat_replication_slots import (
    SlotStat,
    StatReplicationSlots,
    parse_stat_replication_slots,
)


_HEADER = (
    "slot_name\tspill_txns\tspill_count\tspill_bytes\t"
    "stream_txns\tstream_count\tstream_bytes\t"
    "total_txns\ttotal_bytes\tstats_reset\n"
)


def test_empty_returns_empty() -> None:
    assert parse_stat_replication_slots(b"").rows == []


def test_missing_columns_returns_empty() -> None:
    tsv = "spill_txns\n0\n"
    assert parse_stat_replication_slots(tsv.encode()).rows == []


def test_parse_one_quiet_one_spilling() -> None:
    tsv = (
        _HEADER
        + "quiet\t0\t0\t0\t10\t100\t1024\t100\t10240\t\n"
        + "noisy\t50\t75\t52428800\t10\t100\t1024\t150\t52439040\t"
        "2026-04-01 00:00:00\n"
    )
    out = parse_stat_replication_slots(tsv.encode())
    assert isinstance(out, StatReplicationSlots)
    assert len(out) == 2
    by_name = {r.slot_name: r for r in out.rows}
    assert by_name["quiet"].is_spilling is False
    assert by_name["noisy"].is_spilling is True
    assert isinstance(by_name["noisy"], SlotStat)


def test_spilling_filter() -> None:
    tsv = (
        _HEADER
        + "a\t0\t0\t0\t0\t0\t0\t0\t0\t\n"
        + "b\t1\t1\t1024\t0\t0\t0\t1\t1024\t\n"
        + "c\t5\t5\t5120\t0\t0\t0\t5\t5120\t\n"
    )
    out = parse_stat_replication_slots(tsv.encode())
    spilling = out.spilling()
    assert {s.slot_name for s in spilling} == {"b", "c"}
