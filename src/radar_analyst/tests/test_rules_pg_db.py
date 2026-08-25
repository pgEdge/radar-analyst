"""Tests for per-database inline rules.

These rules don't go through the category REGISTRY: they're
invoked inline from ``_build_database_summaries`` with the
already-aggregated per-db dict.
"""

from radar_analyst.rules.pg_db import (
    cache_hit_low,
    deadlocks_nonzero,
    recovery_conflicts_nonzero,
    run_per_db_rules,
    temp_files_heavy,
)


def _db(**overrides: object) -> dict[str, object]:
    """Build a per-db summary dict with healthy defaults."""
    base: dict[str, object] = {
        "datname": "testdb",
        "commits": 0,
        "rollbacks": 0,
        "rollback_ratio": 0.0,
        "cache_hit_ratio": None,
        "blks_read": 0,
        "blks_hit": 0,
        "deadlocks": 0,
        "temp_files": 0,
        "temp_bytes": 0,
        "confl_lock": 0,
        "confl_deadlock": 0,
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------------
# cache_hit_low
# ------------------------------------------------------------------


def test_cache_hit_fires_when_below_95_with_traffic() -> None:
    db = _db(
        cache_hit_ratio=0.90,
        blks_hit=90_000,
        blks_read=10_000,
    )
    findings = cache_hit_low(db)
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"
    assert "cache_hit" in findings[0]["rule_id"]


def test_cache_hit_ignores_idle_database() -> None:
    # < 95% but only 50 block accesses: noise, not a signal.
    db = _db(
        cache_hit_ratio=0.5,
        blks_hit=25,
        blks_read=25,
    )
    assert cache_hit_low(db) == []


def test_cache_hit_silent_at_or_above_95() -> None:
    db = _db(
        cache_hit_ratio=0.98,
        blks_hit=980_000,
        blks_read=20_000,
    )
    assert cache_hit_low(db) == []


# ------------------------------------------------------------------
# deadlocks_nonzero
# ------------------------------------------------------------------


def test_deadlocks_fires_when_nonzero() -> None:
    db = _db(deadlocks=3)
    findings = deadlocks_nonzero(db)
    assert len(findings) == 1
    assert findings[0]["severity"] == "warning"


def test_deadlocks_silent_when_zero() -> None:
    assert deadlocks_nonzero(_db()) == []


# ------------------------------------------------------------------
# temp_files_heavy
# ------------------------------------------------------------------


def test_temp_files_fires_on_many_large_spills() -> None:
    db = _db(
        temp_files=200,
        temp_bytes=200 * 128 * 1024 * 1024,  # 128 MiB avg
    )
    findings = temp_files_heavy(db)
    assert len(findings) == 1


def test_temp_files_silent_on_small_spills() -> None:
    # Many files but each tiny.
    db = _db(
        temp_files=5_000,
        temp_bytes=5_000 * 1024,  # 1 KiB avg
    )
    assert temp_files_heavy(db) == []


def test_temp_files_silent_on_few_files() -> None:
    # Large files but not many.
    db = _db(
        temp_files=5,
        temp_bytes=5 * 1024 * 1024 * 1024,  # 1 GiB avg
    )
    assert temp_files_heavy(db) == []


# ------------------------------------------------------------------
# recovery_conflicts_nonzero
# ------------------------------------------------------------------


def test_recovery_conflicts_fires_on_confl_lock() -> None:
    findings = recovery_conflicts_nonzero(_db(confl_lock=2))
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"


def test_recovery_conflicts_fires_on_confl_deadlock() -> None:
    findings = recovery_conflicts_nonzero(
        _db(confl_deadlock=1)
    )
    assert len(findings) == 1
    assert findings[0]["severity"] == "critical"


def test_recovery_conflicts_silent_on_zero() -> None:
    assert recovery_conflicts_nonzero(_db()) == []


# ------------------------------------------------------------------
# run_per_db_rules aggregator
# ------------------------------------------------------------------


def test_aggregator_returns_flat_list_of_findings() -> None:
    db = _db(
        cache_hit_ratio=0.80,
        blks_hit=800_000,
        blks_read=200_000,
        deadlocks=5,
    )
    findings = run_per_db_rules(db)
    rule_ids = {f["rule_id"] for f in findings}
    assert "pg.db.cache_hit_low" in rule_ids
    assert "pg.db.deadlocks_nonzero" in rule_ids
