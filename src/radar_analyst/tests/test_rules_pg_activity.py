"""Tests for the pg_stat_activity / blocking-lock rules."""

from radar_analyst.parse.pg_activity import PgActivity
from radar_analyst.rules.pg_activity import (
    blocking_locks_present,
    idle_in_transaction_present,
)


def _activity(idle_in_tx: int) -> PgActivity:
    return PgActivity(
        total=idle_in_tx + 1,
        by_state={"active": 1, "idle in transaction": idle_in_tx},
        idle_in_transaction=idle_in_tx,
        wait_events={},
        by_database={},
    )


def test_idle_in_transaction_fires_on_any_session() -> None:
    parsed = {"pg.running_activity": _activity(2)}
    out = idle_in_transaction_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "warning"
    assert out[0].rule_id == "pg.activity.idle_in_transaction"
    assert "2 session(s)" in out[0].title


def test_idle_in_transaction_silent_at_zero() -> None:
    parsed = {"pg.running_activity": _activity(0)}
    assert idle_in_transaction_present(parsed) == []


def test_idle_in_transaction_silent_without_data() -> None:
    assert idle_in_transaction_present({}) == []


def test_blocking_locks_fire_critical() -> None:
    parsed = {"pg.blocking_locks": 3}
    out = blocking_locks_present(parsed)
    assert len(out) == 1
    assert out[0].severity == "critical"
    assert out[0].rule_id == "pg.activity.blocking_locks"
    assert "3 blocking lock chain(s)" in out[0].title


def test_blocking_locks_silent_at_zero() -> None:
    assert blocking_locks_present({"pg.blocking_locks": 0}) == []


def test_blocking_locks_silent_without_data() -> None:
    assert blocking_locks_present({}) == []
