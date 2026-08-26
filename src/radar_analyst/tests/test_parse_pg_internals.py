"""Tests for parse/pg_internals.py.

The bgwriter, checkpointer, stat_wal, stat_io, and stat_slru
parsers.
"""

from __future__ import annotations

from radar_analyst.parse.pg_internals import (
    PgStatIoRow,
    PgStatSlruRow,
    parse_bgwriter,
    parse_checkpointer,
    parse_stat_io,
    parse_stat_slru,
    parse_stat_wal,
)


# ---------------------------------------------------------------
# parse_bgwriter: pre-PG17 layout (checkpoint + bgwriter fields)
# ---------------------------------------------------------------

_BGWRITER_TSV_PRE17 = (
    "checkpoints_timed\tcheckpoints_req\tcheckpoint_write_time\t"
    "checkpoint_sync_time\tbuffers_checkpoint\tbuffers_clean\t"
    "maxwritten_clean\tbuffers_backend\tbuffers_backend_fsync\t"
    "buffers_alloc\tstats_reset\n"
    "42\t8\t12345\t678\t9000\t1200\t3\t4500\t2\t15000\t"
    "2024-01-01 00:00:00+00\n"
)

_BGWRITER_TSV_PG17 = (
    "buffers_clean\tmaxwritten_clean\tbuffers_alloc\tstats_reset\n"
    "1200\t3\t15000\t2024-01-01 00:00:00+00\n"
)


def test_parse_bgwriter_pre17_columns() -> None:
    result = parse_bgwriter(_BGWRITER_TSV_PRE17.encode())
    assert result is not None
    assert result.checkpoints_timed == 42
    assert result.checkpoints_req == 8
    assert result.buffers_checkpoint == 9000
    assert result.buffers_clean == 1200
    assert result.maxwritten_clean == 3
    assert result.buffers_backend == 4500
    assert result.buffers_backend_fsync == 2
    assert result.buffers_alloc == 15000
    assert result.stats_reset is not None
    assert result.stats_reset.year == 2024


def test_parse_bgwriter_pg17_columns() -> None:
    # PG17+ bgwriter table dropped checkpoint and backend fields.
    result = parse_bgwriter(_BGWRITER_TSV_PG17.encode())
    assert result is not None
    assert result.buffers_clean == 1200
    assert result.maxwritten_clean == 3
    assert result.buffers_alloc == 15000
    # Checkpoint + backend fields absent → None.
    assert result.checkpoints_timed is None
    assert result.checkpoints_req is None
    assert result.buffers_backend is None
    assert result.buffers_backend_fsync is None
    assert result.stats_reset is not None
    assert result.stats_reset.year == 2024


def test_parse_bgwriter_empty_returns_none() -> None:
    assert parse_bgwriter(b"") is None
    assert parse_bgwriter(b"checkpoints_timed\n") is None


# ---------------------------------------------------------------
# parse_checkpointer: PG17+ checkpointer table
# ---------------------------------------------------------------

_CHECKPOINTER_TSV = (
    "num_timed\tnum_requested\trestartpoints_timed\t"
    "restartpoints_req\trestartpoints_done\t"
    "write_time\tsync_time\tbuffers_written\tstats_reset\n"
    "100\t15\t0\t0\t0\t8765\t432\t11000\t"
    "2024-01-01 00:00:00+00\n"
)


def test_parse_checkpointer_columns() -> None:
    result = parse_checkpointer(_CHECKPOINTER_TSV.encode())
    assert result is not None
    assert result.num_timed == 100
    assert result.num_requested == 15
    assert result.write_time == 8765.0
    assert result.sync_time == 432.0
    assert result.buffers_written == 11000


def test_parse_checkpointer_empty_returns_none() -> None:
    assert parse_checkpointer(b"") is None


# ---------------------------------------------------------------
# parse_stat_wal
# ---------------------------------------------------------------

_STAT_WAL_TSV = (
    "wal_records\twal_fpi\twal_bytes\twal_buffers_full\t"
    "wal_write\twal_sync\twal_write_time\twal_sync_time\t"
    "stats_reset\n"
    "1000000\t5000\t2147483648\t37\t98000\t97500\t"
    "1234.5\t456.7\t2024-01-01 00:00:00+00\n"
)


def test_parse_stat_wal_columns() -> None:
    result = parse_stat_wal(_STAT_WAL_TSV.encode())
    assert result is not None
    assert result.wal_records == 1000000
    assert result.wal_fpi == 5000
    assert result.wal_buffers_full == 37
    assert result.wal_write == 98000
    assert result.wal_sync == 97500


def test_parse_stat_wal_empty_returns_none() -> None:
    assert parse_stat_wal(b"") is None


def test_parse_stat_wal_zero_buffers_full() -> None:
    tsv = (
        "wal_records\twal_fpi\twal_bytes\twal_buffers_full\t"
        "wal_write\twal_sync\twal_write_time\twal_sync_time\t"
        "stats_reset\n"
        "500\t0\t65536\t0\t40\t40\t0.1\t0.1\t"
        "2024-01-01 00:00:00+00\n"
    )
    result = parse_stat_wal(tsv.encode())
    assert result is not None
    assert result.wal_buffers_full == 0


# ---------------------------------------------------------------
# parse_stat_io
# ---------------------------------------------------------------

_STAT_IO_TSV = (
    "backend_type\tobject\tcontext\treads\tread_time\twrites\t"
    "write_time\twritebacks\twriteback_time\textends\t"
    "extend_time\top_bytes\thits\tevictions\treuses\tfsyncs\t"
    "fsync_time\tstats_reset\n"
    "client backend\trelation\tnormal\t5000\t123.4\t300\t"
    "45.6\t0\t0\t100\t12.3\t8192\t95000\t200\t0\t5\t"
    "1.2\t2024-01-01 00:00:00+00\n"
    "autovacuum worker\trelation\tnormal\t1000\t10.0\t50\t"
    "5.0\t0\t0\t0\t0\t8192\t8000\t10\t0\t0\t"
    "0.0\t2024-01-01 00:00:00+00\n"
)


def test_parse_stat_io_returns_rows() -> None:
    result = parse_stat_io(_STAT_IO_TSV.encode())
    assert result is not None
    assert len(result) == 2
    first = result[0]
    assert isinstance(first, PgStatIoRow)
    assert first.backend_type == "client backend"
    assert first.object == "relation"
    assert first.context == "normal"
    assert first.reads == 5000
    assert first.writes == 300
    assert first.hits == 95000
    assert first.fsyncs == 5


def test_parse_stat_io_empty_returns_empty_list() -> None:
    tsv = (
        "backend_type\tobject\tcontext\treads\tread_time\t"
        "writes\twrite_time\twritebacks\twriteback_time\t"
        "extends\textend_time\top_bytes\thits\tevictions\t"
        "reuses\tfsyncs\tfsync_time\tstats_reset\n"
    )
    result = parse_stat_io(tsv.encode())
    assert result == []


# ---------------------------------------------------------------
# parse_stat_slru
# ---------------------------------------------------------------

_STAT_SLRU_TSV = (
    "name\tblks_zeroed\tblks_hit\tblks_read\tblks_written\t"
    "blks_exists\tflushes\ttruncates\tstats_reset\n"
    "CommitTs\t0\t1000\t50\t40\t100\t5\t0\t"
    "2024-01-01 00:00:00+00\n"
    "MultiXactMember\t0\t500\t20\t15\t50\t3\t0\t"
    "2024-01-01 00:00:00+00\n"
    "MultiXactOffset\t0\t200\t10\t8\t20\t1\t0\t"
    "2024-01-01 00:00:00+00\n"
)


def test_parse_stat_slru_returns_rows() -> None:
    result = parse_stat_slru(_STAT_SLRU_TSV.encode())
    assert result is not None
    assert len(result) == 3
    first = result[0]
    assert isinstance(first, PgStatSlruRow)
    assert first.name == "CommitTs"
    assert first.blks_hit == 1000
    assert first.blks_read == 50
    assert first.blks_written == 40


def test_parse_stat_slru_empty_returns_empty_list() -> None:
    tsv = (
        "name\tblks_zeroed\tblks_hit\tblks_read\tblks_written\t"
        "blks_exists\tflushes\ttruncates\tstats_reset\n"
    )
    result = parse_stat_slru(tsv.encode())
    assert result == []
