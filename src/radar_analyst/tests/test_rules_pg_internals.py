"""Tests for rules/pg_internals.py: Internals & I/O Health rules."""

from __future__ import annotations

from radar_analyst.parse.pg_internals import (
    PgBgwriter,
    PgCheckpointer,
    PgStatWal,
)
from radar_analyst.rules.pg_internals import (
    bgwriter_backend_fsync_nonzero,
    bgwriter_backend_writes_dominant,
    checkpoint_req_ratio_high,
    wal_buffers_full,
)


# ---------------------------------------------------------------
# wal_buffers_full
# ---------------------------------------------------------------

def test_wal_buffers_full_warns_when_nonzero() -> None:
    parsed = {
        "pg.stat_wal": PgStatWal(
            wal_records=1_000_000,
            wal_fpi=5000,
            wal_bytes=2**30,
            wal_buffers_full=37,
            wal_write=98000,
            wal_sync=97500,
        )
    }
    out = wal_buffers_full(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.internals.wal_buffers_full"


def test_wal_buffers_full_silent_when_zero() -> None:
    parsed = {
        "pg.stat_wal": PgStatWal(
            wal_records=500,
            wal_fpi=0,
            wal_bytes=65536,
            wal_buffers_full=0,
            wal_write=40,
            wal_sync=40,
        )
    }
    assert wal_buffers_full(parsed) == []


def test_wal_buffers_full_silent_when_no_data() -> None:
    assert wal_buffers_full({}) == []


# ---------------------------------------------------------------
# checkpoint_req_ratio_high: from bgwriter (pre-PG17)
# ---------------------------------------------------------------

def _bgwriter_pre17(timed: int, req: int) -> PgBgwriter:
    return PgBgwriter(
        checkpoints_timed=timed,
        checkpoints_req=req,
        buffers_checkpoint=9000,
        buffers_clean=1200,
        maxwritten_clean=0,
        buffers_backend=500,
        buffers_backend_fsync=0,
        buffers_alloc=15000,
        stats_reset=None,
    )


def test_checkpoint_req_ratio_warns_above_threshold() -> None:
    # 6 requested out of 10 total = 60% > 50%
    parsed = {"pg.bgwriter": _bgwriter_pre17(timed=4, req=6)}
    out = checkpoint_req_ratio_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.internals.checkpoint_req_ratio"


def test_checkpoint_req_ratio_silent_below_threshold() -> None:
    # 4 requested out of 10 total = 40% < 50%
    parsed = {"pg.bgwriter": _bgwriter_pre17(timed=6, req=4)}
    assert checkpoint_req_ratio_high(parsed) == []


def test_checkpoint_req_ratio_silent_on_zero_checkpoints() -> None:
    parsed = {"pg.bgwriter": _bgwriter_pre17(timed=0, req=0)}
    assert checkpoint_req_ratio_high(parsed) == []


def test_checkpoint_req_ratio_from_checkpointer_pg17() -> None:
    # PG17+: use pg.checkpointer instead of pg.bgwriter
    parsed = {
        "pg.checkpointer": PgCheckpointer(
            num_timed=4,
            num_requested=6,
            write_time=8000.0,
            sync_time=400.0,
            buffers_written=11000,
        )
    }
    out = checkpoint_req_ratio_high(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"


def test_checkpoint_req_ratio_silent_when_no_data() -> None:
    assert checkpoint_req_ratio_high({}) == []


# ---------------------------------------------------------------
# bgwriter_backend_writes_dominant
# ---------------------------------------------------------------

def test_bgwriter_backend_dominant_warns() -> None:
    # buffers_backend (8000) >> buffers_clean (1000) +
    # buffers_checkpoint (2000) = 3000. 8000 > 3000*0.5=1500 → warn
    parsed = {
        "pg.bgwriter": PgBgwriter(
            checkpoints_timed=10,
            checkpoints_req=1,
            buffers_checkpoint=2000,
            buffers_clean=1000,
            maxwritten_clean=0,
            buffers_backend=8000,
            buffers_backend_fsync=0,
            buffers_alloc=20000,
            stats_reset=None,
        )
    }
    out = bgwriter_backend_writes_dominant(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.internals.bgwriter_backend_dominant"


def test_bgwriter_backend_dominant_silent_when_below_threshold() -> None:
    parsed = {
        "pg.bgwriter": PgBgwriter(
            checkpoints_timed=10,
            checkpoints_req=1,
            buffers_checkpoint=8000,
            buffers_clean=4000,
            maxwritten_clean=0,
            buffers_backend=500,
            buffers_backend_fsync=0,
            buffers_alloc=20000,
            stats_reset=None,
        )
    }
    assert bgwriter_backend_writes_dominant(parsed) == []


def test_bgwriter_backend_dominant_silent_when_no_backend_field() -> None:
    # PG17+ bgwriter has no buffers_backend → rule is silent.
    parsed = {
        "pg.bgwriter": PgBgwriter(
            checkpoints_timed=None,
            checkpoints_req=None,
            buffers_checkpoint=None,
            buffers_clean=1200,
            maxwritten_clean=3,
            buffers_backend=None,
            buffers_backend_fsync=None,
            buffers_alloc=15000,
            stats_reset=None,
        )
    }
    assert bgwriter_backend_writes_dominant(parsed) == []


def test_bgwriter_backend_dominant_silent_when_no_data() -> None:
    assert bgwriter_backend_writes_dominant({}) == []


# ---------------------------------------------------------------
# bgwriter_backend_fsync_nonzero
# ---------------------------------------------------------------

def test_bgwriter_backend_fsync_warns_when_nonzero() -> None:
    parsed = {
        "pg.bgwriter": PgBgwriter(
            checkpoints_timed=10,
            checkpoints_req=1,
            buffers_checkpoint=2000,
            buffers_clean=500,
            maxwritten_clean=0,
            buffers_backend=4000,
            buffers_backend_fsync=7,
            buffers_alloc=15000,
            stats_reset=None,
        )
    }
    out = bgwriter_backend_fsync_nonzero(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.internals.bgwriter_backend_fsync"


def test_bgwriter_backend_fsync_silent_when_zero() -> None:
    parsed = {
        "pg.bgwriter": PgBgwriter(
            checkpoints_timed=10,
            checkpoints_req=1,
            buffers_checkpoint=2000,
            buffers_clean=500,
            maxwritten_clean=0,
            buffers_backend=4000,
            buffers_backend_fsync=0,
            buffers_alloc=15000,
            stats_reset=None,
        )
    }
    assert bgwriter_backend_fsync_nonzero(parsed) == []


def test_bgwriter_backend_fsync_silent_when_no_data() -> None:
    assert bgwriter_backend_fsync_nonzero({}) == []


def test_bgwriter_backend_fsync_silent_when_field_absent() -> None:
    # PG17+ bgwriter has no buffers_backend_fsync field.
    parsed = {
        "pg.bgwriter": PgBgwriter(
            checkpoints_timed=None,
            checkpoints_req=None,
            buffers_checkpoint=None,
            buffers_clean=1200,
            maxwritten_clean=3,
            buffers_backend=None,
            buffers_backend_fsync=None,
            buffers_alloc=15000,
            stats_reset=None,
        )
    }
    assert bgwriter_backend_fsync_nonzero(parsed) == []
