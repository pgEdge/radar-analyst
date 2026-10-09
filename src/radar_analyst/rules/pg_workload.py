"""Cluster-level workload rules (Workload category).

Driven by parsers in :mod:`radar_analyst.parse.pg_activity` plus
``pg.settings`` for the ``max_connections`` divisor. These rules are
strictly cluster-wide; per-database workload signals live in
:mod:`radar_analyst.rules.pg_db` and are dispatched separately.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from radar_analyst.parse.databases import (
    DatabaseXactStats,
    DbStatDatabase,
)
from radar_analyst.parse.pg_activity import (
    PgActivity,
    PreparedXacts,
    RunningActivityMaxage,
    collected_at,
    oldest_client_query_age_s,
)
from radar_analyst.parse.pg_settings import PgSettings
from radar_analyst.parse.pg_stat_ssl import StatSsl
from radar_analyst.parse.pg_stat_statements import StatementRow
from radar_analyst.rules.base import (
    Finding,
    register,
    tier,
)


_ROLLBACK_WARN_RATIO = 0.05  # > 5 % rollback rate
_ROLLBACK_MIN_XACTS = 500    # ignore low-traffic clusters
_XACT_RATE_WARN_TPS = 1000   # > 1000 TPS sustained

# 10 min warn / 30 min crit for queries; 1 h warn / 2 h crit
# for xacts. Anything past 2 h is already actively wrecking
# vacuum horizon advancement on every table the cluster touches.
_LONG_QUERY_WARN_S = 10 * 60
_LONG_QUERY_CRIT_S = 30 * 60
_LONG_XACT_WARN_S = 60 * 60
_LONG_XACT_CRIT_S = 2 * 60 * 60
_CONN_SAT_WARN = 0.80
_CONN_SAT_CRIT = 0.95
# Slow-query thresholds: fire when more than 10 distinct
# statements have a mean execution time above 1 second.
_SLOW_QUERY_MEAN_MS = 1000.0
_SLOW_QUERY_COUNT_WARN = 10
# Lock-wait thresholds: warn above 30 s; critical at 5 min,
# where a held lock is producing operationally visible
# application stalls.
_LOCK_WAIT_WARN_S = 30.0
_LOCK_WAIT_CRIT_S = 300.0


def _format_seconds(s: float) -> str:
    if s < 60:
        return f"{s:.0f} s"
    if s < 3600:
        return f"{s / 60:.1f} min"
    if s < 86400:
        return f"{s / 3600:.2f} h"
    return f"{s / 86400:.2f} d"


@register("Workload")
def long_xact_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn (>1 h) / critical (>2 h) on the oldest open xact.

    Long transactions hold xmin back, blocking vacuum and bloating
    every table they touch indirectly. Source: ``max_xact_age`` from
    ``pg.running_activity_maxage``.
    """
    m: RunningActivityMaxage | None = parsed.get(
        "pg.running_activity_maxage"
    )
    if m is None or m.max_xact_age_s is None:
        return []
    age = m.max_xact_age_s
    sev = tier(age, warn=_LONG_XACT_WARN_S, crit=_LONG_XACT_CRIT_S)
    if sev is None:
        return []
    return [
        Finding(
            rule_id="pg.activity.long_xact",
            severity=sev,
            title=(
                f"Oldest open transaction is "
                f"{_format_seconds(age)}"
            ),
            detail=(
                "Long-running transactions hold xmin back, which "
                "prevents vacuum from reclaiming dead tuples on "
                "EVERY table: not just the ones the transaction "
                "touched. Identify the offending session via "
                "pg_stat_activity (pid, application_name, "
                "client_addr, query) and either commit/abort it "
                "or set idle_in_transaction_session_timeout / "
                "statement_timeout for the workload."
            ),
        )
    ]


@register("Workload")
def long_query_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn (>10 min) / critical (>30 min) on the oldest query.

    Only client backends count: a walsender's replication command
    runs for the life of the connection and is not a query.
    """
    age = oldest_client_query_age_s(
        parsed.get("pg.running_activity_maxage"),
        parsed.get("pg.running_activity"),
    )
    if age is None:
        return []
    sev = tier(age, warn=_LONG_QUERY_WARN_S, crit=_LONG_QUERY_CRIT_S)
    if sev is None:
        return []
    return [
        Finding(
            rule_id="pg.activity.long_query",
            severity=sev,
            title=(
                f"Oldest running query has been executing for "
                f"{_format_seconds(age)}"
            ),
            detail=(
                "A query running this long is either a missing "
                "index, a runaway report, or a blocked statement. "
                "Inspect the corresponding pg_stat_activity row "
                "and decide whether to cancel it or tune the "
                "underlying query / index. For OLTP workloads "
                "consider a global statement_timeout."
            ),
        )
    ]


@register("Workload")
def prepared_xacts_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when any prepared (2PC) transaction is open.

    Stranded 2PC transactions hold locks indefinitely and pin
    xmin, so any non-zero count is reported. No snapshot ``now``
    is available to compare ``prepared`` timestamps against, so
    the rule fires on count rather than age.
    """
    p: PreparedXacts | None = parsed.get("pg.prepared_xacts")
    if p is None or p.total == 0:
        return []
    gid_hint = (
        f" (oldest gid={p.oldest_gid})" if p.oldest_gid else ""
    )
    return [
        Finding(
            rule_id="pg.activity.prepared_xacts",
            severity="warning",
            title=(
                f"{p.total} prepared (2PC) transaction(s) "
                f"open{gid_hint}"
            ),
            detail=(
                "Open prepared transactions hold all the locks "
                "the original transaction acquired AND pin xmin, "
                "preventing vacuum. If no external transaction "
                "coordinator is going to commit or roll them "
                "back, do so manually with ROLLBACK PREPARED. If "
                "you don't use 2PC, consider setting "
                "max_prepared_transactions = 0."
            ),
        )
    ]


@register("Workload")
def connection_saturation(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn (>=80 %) / critical (>=95 %) of ``max_connections``."""
    a: PgActivity | None = parsed.get("pg.running_activity")
    settings: PgSettings | None = parsed.get("pg.settings")
    if a is None or settings is None or a.total <= 0:
        return []
    mc = settings.get("max_connections")
    if mc is None:
        return []
    try:
        cap = int(mc.setting)
    except ValueError:
        return []
    if cap <= 0:
        return []
    ratio = a.total / cap
    sev = tier(ratio, warn=_CONN_SAT_WARN, crit=_CONN_SAT_CRIT)
    if sev is None:
        return []
    return [
        Finding(
            rule_id="pg.activity.connection_saturation",
            severity=sev,
            title=(
                f"{a.total} of {cap} connections in use "
                f"({ratio * 100:.0f}%)"
            ),
            detail=(
                "Approaching max_connections risks new sessions "
                "being refused, which usually surfaces as "
                "application errors. Either raise "
                "max_connections (and shared_buffers / work_mem "
                "in proportion) or: much better: front the "
                "database with a connection pooler such as "
                "PgBouncer in transaction-pooling mode."
            ),
        )
    ]


@register("Workload")
def rollback_ratio_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when the cluster-wide rollback ratio exceeds 5 %.

    Cumulative ``xact_commit`` / ``xact_rollback`` from
    ``pg_stat_database`` summed across all databases. A high
    rollback ratio usually indicates application-side error
    storms (constraint violations, serialisation failures,
    deadlocks caught in code).
    """
    xact: dict[str, DatabaseXactStats] | None = parsed.get(
        "pg.databases_xact"
    )
    if not xact:
        return []
    total_commits = sum(
        x.xact_commit for x in xact.values()
    )
    total_rollbacks = sum(
        x.xact_rollback for x in xact.values()
    )
    total = total_commits + total_rollbacks
    if total < _ROLLBACK_MIN_XACTS:
        return []
    ratio = total_rollbacks / total
    if ratio <= _ROLLBACK_WARN_RATIO:
        return []
    return [
        Finding(
            rule_id="pg.workload.rollback_ratio_high",
            severity="warning",
            title=(
                f"Cluster rollback ratio is {ratio:.1%} "
                f"({total_rollbacks:,} of {total:,})"
            ),
            detail=(
                "A rollback rate above 5% across the cluster "
                "usually indicates application-side error storms "
                "(constraint violations, serialisation failures, "
                "deadlocks caught in code). Review application "
                "logs for the source of the failed transactions."
            ),
        )
    ]


def _database_rates(
    at: datetime,
    xact: dict[str, DatabaseXactStats],
    stat_db: dict[str, DbStatDatabase],
) -> dict[str, float]:
    """Transactions per second in each database with a known start.

    A database's pg_stat_database counters run from its own
    stats_reset. With none on record they could cover any length of
    time, so that database is left out.
    """
    rates: dict[str, float] = {}
    for name, x in xact.items():
        s = stat_db.get(name)
        if s is None or s.stats_reset is None or s.stats_reset >= at:
            continue
        elapsed = (at - s.stats_reset).total_seconds()
        rates[name] = (x.xact_commit + x.xact_rollback) / elapsed
    return rates


@register("Workload")
def xact_rate_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when the sustained transaction rate exceeds 1000 TPS.

    Each database's commits and rollbacks are divided by the time
    from its own ``pg_stat_database.stats_reset`` to radar's
    collection, both by the server's clock, and the rates are
    summed. An archive can be assessed any time after it was
    collected, so the analyst's own clock has no part in it.
    """
    at = collected_at(
        parsed.get("pg.running_activity_maxage"),
        parsed.get("pg.running_activity"),
    )
    xact: dict[str, DatabaseXactStats] | None = parsed.get(
        "pg.databases_xact"
    )
    if at is None or not xact:
        return []
    rates = _database_rates(
        at, xact, parsed.get("pg.db.stat_database") or {}
    )
    tps = sum(rates.values())
    if tps <= _XACT_RATE_WARN_TPS:
        return []
    return [
        Finding(
            rule_id="pg.workload.xact_rate_high",
            severity="warning",
            title=(
                f"Sustained transaction rate is "
                f"{tps:,.0f} TPS"
            ),
            detail=(
                f"Averaged {tps:,.0f} transactions/second in "
                f"{', '.join(sorted(rates))}, each since its "
                "pg_stat_database statistics were last reset. "
                "High sustained TPS increases WAL generation, "
                "checkpoint pressure, and replication lag risk. "
                "Verify that connection pooling, batching, "
                "and autovacuum are tuned for this load."
            ),
        )
    ]


@register("Workload")
def connections_without_ssl(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when any backend is connected without SSL.

    Local Unix-socket connections legitimately don't carry SSL
    and aren't a concern; we only flag the count and let the
    operator inspect (the application_name + client_addr
    columns are in the snapshot).
    """
    ssl: StatSsl | None = parsed.get("pg.stat_ssl")
    if ssl is None:
        return []
    insecure = ssl.insecure()
    if not insecure:
        return []
    # Local sockets typically have empty client_addr; surface
    # remote-only connection counts separately as the more
    # actionable signal.
    remote = [
        c for c in insecure
        if c.client_addr and c.client_addr.strip() not in (
            "/tmp", "127.0.0.1", "::1"
        )
    ]
    severity = "warning" if remote else "info"
    apps: dict[str, int] = {}
    for c in remote or insecure:
        key = c.application_name or "(unnamed)"
        apps[key] = apps.get(key, 0) + 1
    breakdown = ", ".join(
        f"{name}: {count}"
        for name, count in sorted(
            apps.items(), key=lambda kv: -kv[1]
        )[:5]
    )
    scope = "remote" if remote else "local-only"
    return [
        Finding(
            rule_id="pg.workload.connections_without_ssl",
            severity=severity,
            title=(
                f"{len(insecure)} backend(s) connected "
                f"without SSL ({scope})"
            ),
            detail=(
                "Backends without SSL transmit credentials "
                "and query data unencrypted. Top "
                f"applications: {breakdown}. Tighten "
                "pg_hba.conf so non-local entries require "
                "``hostssl``, then bounce the affected "
                "clients."
            ),
        )
    ]


@register("Workload")
def slow_query_count_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when many distinct statements run slowly.

    Counts statements in ``pg_stat_statements`` whose
    ``mean_exec_time`` exceeds 1 s and warns above 10 of them.
    Silently does nothing if the extension isn't installed
    (radar's stat_statements TSVs are absent).
    """
    rows: list[StatementRow] | None = parsed.get(
        "pg.stat_statements.calls"
    )
    if not rows:
        return []
    slow = [r for r in rows if r.mean_exec_time > _SLOW_QUERY_MEAN_MS]
    if len(slow) <= _SLOW_QUERY_COUNT_WARN:
        return []
    slow.sort(key=lambda r: -r.mean_exec_time)
    examples_lines: list[str] = []
    for r in slow[:5]:
        snippet = (r.query or "").replace("\n", " ").strip()
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        examples_lines.append(
            f"{r.mean_exec_time:.0f} ms mean ({r.calls:,} calls): "
            f"{snippet}"
        )
    examples = "; ".join(examples_lines)
    return [
        Finding(
            rule_id="pg.workload.slow_query_count_high",
            severity="warning",
            title=(
                f"{len(slow)} statements with mean exec time "
                "> 1 s"
            ),
            detail=(
                "pg_stat_statements is reporting many "
                "individually slow query shapes. Top by mean "
                f"exec time: {examples}. Consider EXPLAIN "
                "ANALYZE on each, then index / rewrite / "
                "raise work_mem as appropriate. If this is "
                "newly elevated, correlate with recent "
                "deployments or schema changes."
            ),
        )
    ]


@register("Workload")
def lock_wait_time_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn (>30 s) / critical (>5 min) on the longest current lock wait.

    Source: ``max_lock_wait_age`` on
    ``pg.running_activity_maxage`` (radar 0.5.0+). Older zips
    don't carry the column: the field is None and the rule
    silently no-ops. Distinct from
    ``pg.activity.blocking_locks`` (which counts blocked
    backends but doesn't tell you how long they've been
    waiting).
    """
    m: RunningActivityMaxage | None = parsed.get(
        "pg.running_activity_maxage"
    )
    if m is None or m.max_lock_wait_age_s is None:
        return []
    age = m.max_lock_wait_age_s
    sev = tier(age, warn=_LOCK_WAIT_WARN_S, crit=_LOCK_WAIT_CRIT_S)
    if sev is None:
        return []
    return [
        Finding(
            rule_id="pg.activity.lock_wait_time",
            severity=sev,
            title=(
                "Longest current lock wait is "
                f"{_format_seconds(age)}"
            ),
            detail=(
                "At least one backend is blocked waiting for a "
                "lock held by another session. Identify the "
                "blocker via pg_stat_activity (wait_event_type "
                "= 'Lock') joined to pg_locks; long lock waits "
                "compound: every blocker creates a queue. "
                "Consider lowering lock_timeout for the "
                "affected role(s) or reducing transaction "
                "scope on the blocker."
            ),
        )
    ]
