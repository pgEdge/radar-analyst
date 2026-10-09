"""Parsers for the 'Workload' category files (pg_stat_activity + locks).

Covers what radar collects from a stock PostgreSQL instance:

- ``running_activity.tsv``: per-session state + wait events.
- ``running_activity_maxage.tsv``: single-row aggregates of the
  oldest query / xact / backend.
- ``waits_sample.tsv``: every backend currently waiting (one row).
- ``connection_summary.tsv``: pre-aggregated state × wait_event_type.
- ``running_locks.tsv``: every granted lock (``pg_locks WHERE
  granted``).
- ``blocking_locks.tsv``: one row per blocking chain.
- ``prepared_xacts.tsv``: open prepared (2PC) transactions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from radar_analyst.parse.coerce import as_datetime_or_none
from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class PgActivity:
    """Aggregated pg_stat_activity state counts."""
    total: int = 0
    # state → count, e.g. {'active': 3, 'idle': 42, 'idle in transaction': 1}
    by_state: dict[str, int] = field(default_factory=dict)
    # Sessions currently in 'idle in transaction' or
    # 'idle in transaction (aborted)'.
    idle_in_transaction: int = 0
    # Wait events currently observed (non-null wait_event rows).
    wait_events: dict[str, int] = field(default_factory=dict)
    # Session count per database (excludes rows with empty datname,
    # which is typical for background worker types).
    by_database: dict[str, int] = field(default_factory=dict)
    # Earliest query_start among non-idle sessions, the rows radar's
    # max_query_age covers, and among active client backends.
    oldest_query_start: datetime | None = None
    oldest_client_query_start: datetime | None = None


def _oldest_query_starts(
    rows: list[dict[str, str]],
) -> tuple[datetime | None, datetime | None]:
    """Earliest non-idle and active-client-backend query_start."""
    starts: list[datetime] = []
    client: list[datetime] = []
    for row in rows:
        state = row.get("state", "")
        start = as_datetime_or_none(row.get("query_start"))
        if start is None or state in ("", "idle"):
            continue
        starts.append(start)
        if (
            state == "active"
            and row.get("backend_type") == "client backend"
        ):
            client.append(start)
    return min(starts, default=None), min(client, default=None)


def parse_running_activity(data: bytes) -> PgActivity:
    """Parse running_activity.tsv into PgActivity."""
    t = parse_tsv_bytes(data)
    if not t.rows or "state" not in t.columns:
        return PgActivity()
    by_state: dict[str, int] = {}
    idle_in_tx = 0
    wait_events: dict[str, int] = {}
    by_database: dict[str, int] = {}
    for row in t.rows:
        state = row.get("state", "") or "(unknown)"
        by_state[state] = by_state.get(state, 0) + 1
        if state.startswith("idle in transaction"):
            idle_in_tx += 1
        ev = row.get("wait_event", "")
        if ev:
            wait_events[ev] = wait_events.get(ev, 0) + 1
        db = row.get("datname", "")
        if db:
            by_database[db] = by_database.get(db, 0) + 1
    oldest, oldest_client = _oldest_query_starts(t.rows)
    return PgActivity(
        total=len(t.rows),
        by_state=by_state,
        idle_in_transaction=idle_in_tx,
        wait_events=wait_events,
        by_database=by_database,
        oldest_query_start=oldest,
        oldest_client_query_start=oldest_client,
    )


def parse_blocking_locks_count(data: bytes) -> int:
    """``blocking_locks.tsv`` is one row per blocking chain.

    A row count above zero is all the rule needs ("is anything
    blocked?"), so no structured decode is done.
    """
    t = parse_tsv_bytes(data)
    return len(t.rows)


# ---------------------------------------------------------------
# PostgreSQL interval parsing
# ---------------------------------------------------------------

# Postgres interval text format (default ``IntervalStyle = postgres``):
#
#   [-]N day[s] HH:MM:SS[.ffffff]
#   HH:MM:SS[.ffffff]
#   -HH:MM:SS[.ffffff]
#
# Months / years are not produced by clock_timestamp() - timestamp
# subtractions, so we don't need to handle them. If they ever
# appear we return None (can't pin to seconds without a calendar).
_INTERVAL_RE = re.compile(
    r"""
    ^\s*
    (?:(?P<days>-?\d+)\s+days?\s+)?      # optional "N day[s] "
    (?P<sign>-)?                         # optional sign on HH:MM:SS
    (?P<h>\d{1,9}):
    (?P<m>\d{2}):
    (?P<s>\d{2}(?:\.\d+)?)
    \s*$
    """,
    re.VERBOSE,
)


def parse_pg_interval_seconds(value: str | None) -> float | None:
    """Decode a Postgres interval text value to seconds.

    Returns ``None`` for empty / unparsable / month-bearing values.
    """
    if not value:
        return None
    m = _INTERVAL_RE.match(value)
    if m is None:
        return None
    days = int(m.group("days") or 0)
    sign = -1.0 if m.group("sign") == "-" else 1.0
    hours = int(m.group("h"))
    minutes = int(m.group("m"))
    seconds = float(m.group("s"))
    hms = sign * (hours * 3600 + minutes * 60 + seconds)
    return days * 86400.0 + hms


# ---------------------------------------------------------------
# running_activity_maxage
# ---------------------------------------------------------------


@dataclass(frozen=True)
class RunningActivityMaxage:
    """Oldest query/xact/backend/lock-wait ages."""
    max_query_age_s: float | None = None
    max_xact_age_s: float | None = None
    max_backend_age_s: float | None = None
    # ``max_lock_wait_age`` was added to radar's query in 0.5.0;
    # older zips don't carry the column, so the parser falls back
    # to None and the rule layer skips silently.
    max_lock_wait_age_s: float | None = None


def parse_running_activity_maxage(
    data: bytes,
) -> RunningActivityMaxage | None:
    """Parse the single-row maxage aggregate file.

    Returns ``None`` if the file is empty or has no data row.
    """
    t = parse_tsv_bytes(data)
    if not t.rows:
        return None
    row = t.rows[0]
    return RunningActivityMaxage(
        max_query_age_s=parse_pg_interval_seconds(
            row.get("max_query_age", "")
        ),
        max_xact_age_s=parse_pg_interval_seconds(
            row.get("max_xact_age", "")
        ),
        max_backend_age_s=parse_pg_interval_seconds(
            row.get("max_backend_age", "")
        ),
        max_lock_wait_age_s=parse_pg_interval_seconds(
            row.get("max_lock_wait_age", "")
        ),
    )


def collected_at(
    maxage: RunningActivityMaxage | None,
    activity: PgActivity | None,
) -> datetime | None:
    """When radar read pg_stat_activity, by the server's clock.

    radar records no collection time. Its ``max_query_age`` is
    clock_timestamp() less the oldest non-idle query_start, and
    radar's own session is always non-idle while it collects, so
    the oldest non-idle query_start plus that age is the moment of
    collection. None when either file is missing.
    """
    if (
        maxage is None
        or activity is None
        or maxage.max_query_age_s is None
        or activity.oldest_query_start is None
    ):
        return None
    return activity.oldest_query_start + timedelta(
        seconds=maxage.max_query_age_s
    )


def oldest_client_query_age_s(
    maxage: RunningActivityMaxage | None,
    activity: PgActivity | None,
) -> float | None:
    """Age of the oldest query a client backend is running.

    radar's ``max_query_age`` spans every non-idle session, a
    walsender's START_REPLICATION included, which runs for as long
    as its standby stays connected, so the age is taken from the
    oldest active client backend's query_start instead. None when
    no client backend is running a query.
    """
    at = collected_at(maxage, activity)
    if (
        at is None
        or activity is None
        or activity.oldest_client_query_start is None
    ):
        return None
    return (at - activity.oldest_client_query_start).total_seconds()


# ---------------------------------------------------------------
# waits_sample
# ---------------------------------------------------------------


@dataclass(frozen=True)
class WaitsSample:
    """Wait-event sample counts by type."""
    total: int = 0
    by_event_type: dict[str, int] = field(default_factory=dict)
    by_event: dict[str, int] = field(default_factory=dict)


def parse_waits_sample(data: bytes) -> WaitsSample:
    """Parse waits_sample.tsv into WaitsSample."""
    t = parse_tsv_bytes(data)
    if not t.rows:
        return WaitsSample()
    by_type: dict[str, int] = {}
    by_event: dict[str, int] = {}
    for row in t.rows:
        et = row.get("wait_event_type", "") or "(unknown)"
        by_type[et] = by_type.get(et, 0) + 1
        ev = row.get("wait_event", "") or "(unknown)"
        by_event[ev] = by_event.get(ev, 0) + 1
    return WaitsSample(
        total=len(t.rows),
        by_event_type=by_type,
        by_event=by_event,
    )


# ---------------------------------------------------------------
# connection_summary
# ---------------------------------------------------------------


@dataclass(frozen=True)
class ConnectionSummary:
    """Backend counts against max_connections."""
    total: int = 0
    # Every (state, wait_event_type, count) triple: preserved
    # so the prompt builder can render a compact grid.
    cells: list[tuple[str, str, int]] = field(default_factory=list)
    # Marginals for rule input:
    by_state: dict[str, int] = field(default_factory=dict)
    by_wait_event_type: dict[str, int] = field(default_factory=dict)


def parse_connection_summary(data: bytes) -> ConnectionSummary:
    """Parse connection_summary.tsv."""
    t = parse_tsv_bytes(data)
    if not t.rows:
        return ConnectionSummary()
    cells: list[tuple[str, str, int]] = []
    by_state: dict[str, int] = {}
    by_wet: dict[str, int] = {}
    total = 0
    for row in t.rows:
        state = row.get("state", "")
        wet = row.get("wait_event_type", "")
        try:
            n = int(row.get("count", "0") or 0)
        except ValueError:
            continue
        cells.append((state, wet, n))
        total += n
        s_key = state if state else "(unknown)"
        w_key = wet if wet else "(none)"
        by_state[s_key] = by_state.get(s_key, 0) + n
        by_wet[w_key] = by_wet.get(w_key, 0) + n
    return ConnectionSummary(
        total=total,
        cells=cells,
        by_state=by_state,
        by_wait_event_type=by_wet,
    )


# ---------------------------------------------------------------
# running_locks
# ---------------------------------------------------------------


@dataclass(frozen=True)
class RunningLocks:
    """Granted-lock counts by lock mode."""
    total: int = 0
    by_mode: dict[str, int] = field(default_factory=dict)
    by_locktype: dict[str, int] = field(default_factory=dict)


def parse_running_locks(data: bytes) -> RunningLocks:
    """Parse running_locks.tsv into RunningLocks."""
    t = parse_tsv_bytes(data)
    if not t.rows:
        return RunningLocks()
    by_mode: dict[str, int] = {}
    by_lt: dict[str, int] = {}
    for row in t.rows:
        mode = row.get("mode", "") or "(unknown)"
        by_mode[mode] = by_mode.get(mode, 0) + 1
        lt = row.get("locktype", "") or "(unknown)"
        by_lt[lt] = by_lt.get(lt, 0) + 1
    return RunningLocks(
        total=len(t.rows),
        by_mode=by_mode,
        by_locktype=by_lt,
    )


# ---------------------------------------------------------------
# prepared_xacts
# ---------------------------------------------------------------


@dataclass(frozen=True)
class PreparedXacts:
    """Prepared-transaction count and oldest age."""
    total: int = 0
    oldest_age_s: float | None = None
    oldest_gid: str | None = None


def parse_prepared_xacts(
    data: bytes, now_iso: str | None
) -> PreparedXacts:
    """Count prepared xacts and compute the oldest one's age.

    *now_iso* is a timestamp-with-tz string used as the reference
    "now" for age calculation when the caller has one. If
    ``None``, age is left unset; the count is still what the
    "any prepared xact present" rule fires on.
    """
    t = parse_tsv_bytes(data)
    if not t.rows:
        return PreparedXacts()
    total = len(t.rows)
    now = as_datetime_or_none(now_iso) if now_iso else None
    oldest_dt: datetime | None = None
    oldest_gid: str | None = None
    for row in t.rows:
        prep = as_datetime_or_none(row.get("prepared", ""))
        if prep is None:
            continue
        if oldest_dt is None or prep < oldest_dt:
            oldest_dt = prep
            oldest_gid = row.get("gid", "") or None
    age_s: float | None = None
    if now is not None and oldest_dt is not None:
        age_s = (now - oldest_dt).total_seconds()
    # When *now* is unknown but we still saw rows, surface the gid
    # so callers can at least name the offender.
    if oldest_gid is None and total > 0:
        oldest_gid = t.rows[0].get("gid", "") or None
    return PreparedXacts(
        total=total,
        oldest_age_s=age_s,
        oldest_gid=oldest_gid,
    )
