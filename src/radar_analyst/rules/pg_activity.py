"""Deterministic rules for the Workload category (pg_stat_activity + locks)."""

from __future__ import annotations

from typing import Any

from radar_analyst.parse.pg_activity import PgActivity
from radar_analyst.rules.base import Finding, register


@register("Workload")
def idle_in_transaction_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn on any idle-in-transaction session."""
    a: PgActivity | None = parsed.get("pg.running_activity")
    if a is None or a.idle_in_transaction == 0:
        return []
    return [
        Finding(
            rule_id="pg.activity.idle_in_transaction",
            severity="warning",
            title=(
                f"{a.idle_in_transaction} session(s) "
                "idle in transaction"
            ),
            detail=(
                "Idle-in-transaction sessions hold row and "
                "relation locks and block vacuum from reclaiming "
                "dead tuples. Investigate the client using "
                "pg_stat_activity (query + application_name + "
                "client_addr); consider setting "
                "idle_in_transaction_session_timeout."
            ),
        )
    ]


@register("Workload")
def blocking_locks_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Critical on any blocking lock chain."""
    n = parsed.get("pg.blocking_locks")
    if not n:
        return []
    return [
        Finding(
            rule_id="pg.activity.blocking_locks",
            severity="critical",
            title=(
                f"{n} blocking lock chain(s) at snapshot time"
            ),
            detail=(
                "At least one session is waiting on a lock held "
                "by another. Resolve via the pg_locks / "
                "pg_stat_activity blocking query; if recurrent, "
                "review transaction scope and indexing."
            ),
        )
    ]
