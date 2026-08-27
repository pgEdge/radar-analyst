"""Deterministic rules for the Replication category."""

from __future__ import annotations

from typing import Any

from radar_analyst.parse.pg_settings import PgSettings
from radar_analyst.parse.pg_stat_replication_slots import (
    StatReplicationSlots,
)
from radar_analyst.parse.pg_wal import (
    ReplicationReplica,
    ReplicationSlots,
    Subscription,
    WalPosition,
    lsn_to_int,
)
from radar_analyst.rules.base import Finding, register, top_n


# Lag thresholds for streaming replicas (time-based).
_LAG_WARN_S = 5 * 60.0    # 5 min
_LAG_CRIT_S = 30 * 60.0   # 30 min

# Byte-lag thresholds for streaming replicas.
_LAG_BYTES_WARN = 100 * 1024 * 1024    # 100 MiB
_LAG_BYTES_CRIT = 1024 * 1024 * 1024   # 1 GiB

# WAL a slot is pinning. The warning tier is max_wal_size rather
# than a fixed size: a slot holding one checkpoint cycle's worth of
# WAL is doing its job, and a slot outrunning that cycle is the
# condition that fills a disk. The floor keeps the rule quiet on
# hosts with a small max_wal_size, where one cycle is not yet
# worth reporting.
_RETAINED_WARN_FLOOR = 1024 * 1024 * 1024        # 1 GiB
_RETAINED_CRIT = 10 * 1024 * 1024 * 1024         # 10 GiB
_MAX_WAL_SIZE_DEFAULT_MB = 1024                  # PG default

# States that are transient and expected during normal operation.
_OK_STATES = frozenset({"streaming", "catchup", "backup"})


@register("Replication")
def inactive_slot_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn on replication slots with no consumer."""
    slots: ReplicationSlots | None = parsed.get(
        "pg.replication_slots"
    )
    if slots is None:
        return []
    out: list[Finding] = []
    if slots.inactive:
        names = ", ".join(
            s.slot_name for s in slots.inactive
        )
        out.append(
            Finding(
                rule_id="pg.repl.slot_inactive",
                severity=(
                    "critical" if slots.lost else "warning"
                ),
                title=(
                    f"{len(slots.inactive)} inactive "
                    "replication slot(s)"
                ),
                detail=(
                    f"Inactive slot(s): {names}. Inactive "
                    "slots pin WAL retention indefinitely; if "
                    "the consumer is gone for good, drop the "
                    "slot. A slot with wal_status='lost' has "
                    "already missed required WAL and cannot "
                    "resume."
                ),
            )
        )
    return out


@register("Replication")
def replica_not_streaming(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when any streaming replica is in an unexpected state.

    ``catchup`` and ``backup`` are legitimate transient states;
    ``startup`` and ``stopping`` indicate the replica is not
    receiving WAL.
    """
    replicas: list[ReplicationReplica] | None = parsed.get(
        "pg.replication"
    )
    if not replicas:
        return []
    problem = [r for r in replicas if r.state not in _OK_STATES]
    if not problem:
        return []
    names = ", ".join(
        f"{r.application_name} ({r.state})"
        for r in problem
    )
    return [
        Finding(
            rule_id="pg.repl.replica_not_streaming",
            severity="warning",
            title=(
                f"{len(problem)} replica(s) not in "
                "streaming/catchup state"
            ),
            detail=(
                f"Replica(s) with unexpected state: {names}. "
                "A replica in 'startup' or 'stopping' is not "
                "receiving WAL; investigate pg_stat_replication "
                "and the standby server logs."
            ),
        )
    ]


@register("Replication")
def replica_lag_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn / critical when any replica's replay_lag exceeds threshold.

    Emits one finding per lagging replica so the DBA can see all of
    them. Uses ``replay_lag`` (wall-clock time from WAL flush on
    primary to replay confirmation from replica). NULL lag (replica
    fully caught up or not yet reporting) is skipped.
    """
    replicas: list[ReplicationReplica] | None = parsed.get(
        "pg.replication"
    )
    if not replicas:
        return []
    out: list[Finding] = []
    for r in replicas:
        if r.replay_lag_s is None:
            continue
        if r.replay_lag_s < _LAG_WARN_S:
            continue
        sev = (
            "critical"
            if r.replay_lag_s >= _LAG_CRIT_S
            else "warning"
        )
        mins = r.replay_lag_s / 60
        out.append(
            Finding(
                rule_id="pg.repl.replica_lag",
                severity=sev,
                title=(
                    f"Replica {r.application_name!r} "
                    f"replay_lag = {mins:.1f} min"
                ),
                detail=(
                    f"Streaming replica "
                    f"'{r.application_name}' "
                    f"({r.client_addr}) has a replay lag of "
                    f"{mins:.1f} minutes. "
                    "Possible causes: replica under load, "
                    "network delay, or large transaction storm "
                    "on the primary. If lag is growing, check "
                    "standby I/O and pg_stat_activity on the "
                    "replica."
                ),
            )
        )
    return out


@register("Replication")
def subscription_not_running(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when a logical subscription has no active apply worker.

    A subscription with ``pid = NULL`` in pg_stat_subscription is
    enabled but its worker has exited: typically after a replication
    error. The subscription will not receive further changes until it
    is re-enabled or the error is resolved.
    """
    subs: list[Subscription] | None = parsed.get(
        "pg.subscriptions"
    )
    if not subs:
        return []
    stuck = [s for s in subs if s.pid is None]
    if not stuck:
        return []
    names = ", ".join(s.subname for s in stuck)
    return [
        Finding(
            rule_id="pg.repl.subscription_not_running",
            severity="warning",
            title=(
                f"{len(stuck)} subscription(s) not running"
            ),
            detail=(
                f"Subscription(s) with no active worker: "
                f"{names}. The apply worker has exited; common "
                "causes are a replication conflict, a missing "
                "table on the subscriber, or a manual "
                "pg_subscription disable. Check the subscriber "
                "logs and re-enable with "
                "ALTER SUBSCRIPTION … ENABLE after resolving "
                "the error."
            ),
        )
    ]


@register("Replication")
def lag_bytes_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn / critical when any replica's byte lag exceeds threshold.

    Emits one finding per lagging replica. Uses ``sent_lsn -
    replay_lsn`` as the byte-lag estimate. NULL or missing LSN
    fields are skipped.
    """
    replicas: list[ReplicationReplica] | None = parsed.get(
        "pg.replication"
    )
    if not replicas:
        return []
    out: list[Finding] = []
    for r in replicas:
        lag = r.lsn_lag_bytes
        if lag is None or lag < _LAG_BYTES_WARN:
            continue
        sev = (
            "critical"
            if lag >= _LAG_BYTES_CRIT
            else "warning"
        )
        mb = lag / (1024 * 1024)
        out.append(
            Finding(
                rule_id="pg.repl.lag_bytes",
                severity=sev,
                title=(
                    f"Replica {r.application_name!r} "
                    f"byte lag = {mb:.0f} MiB"
                ),
                detail=(
                    f"Streaming replica "
                    f"'{r.application_name}' "
                    f"({r.client_addr}) has "
                    f"{mb:.0f} MiB of unapplied WAL "
                    f"(sent_lsn − replay_lsn). "
                    "Possible causes: replica I/O bound, "
                    "large transaction replay, or the "
                    "replica is paused. Check "
                    "pg_stat_replication on the primary "
                    "and pg_stat_activity on the standby."
                ),
            )
        )
    return out


def _max_wal_size_bytes(settings: PgSettings | None) -> int:
    """``max_wal_size`` in bytes, defaulting to PostgreSQL's 1 GiB.

    pg_settings reports it in megabytes.
    """
    mb = _MAX_WAL_SIZE_DEFAULT_MB
    if settings is not None:
        s = settings.get("max_wal_size")
        if s is not None and s.setting:
            try:
                mb = int(s.setting)
            except ValueError:
                mb = _MAX_WAL_SIZE_DEFAULT_MB
    return mb * 1024 * 1024


@register("Replication")
def slot_retaining_wal(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when a replication slot is pinning a lot of WAL.

    The other slot rules ask whether a consumer exists.
    ``slot_inactive`` and ``replica_disconnected`` fire when one is
    missing, and ``lag_bytes`` measures replicas that are connected.
    None of them covers an active slot whose consumer is merely
    slow: it retains WAL without limit while every other rule stays
    quiet, and the first symptom is a full pg_wal.

    Retained bytes is ``current_wal_lsn − restart_lsn``. Both are in
    the archive, so this needs no data radar does not already
    collect.
    """
    slots: ReplicationSlots | None = parsed.get(
        "pg.replication_slots"
    )
    wp: WalPosition | None = parsed.get("pg.wal_position")
    if slots is None or not slots.all or wp is None:
        return []
    # pg_current_wal_lsn() is primary-side: on a standby the value
    # is not comparable with a slot's restart_lsn.
    if wp.is_in_recovery:
        return []
    current = lsn_to_int(wp.current_wal_lsn)
    if current is None:
        return []
    warn_at = max(
        _RETAINED_WARN_FLOOR,
        _max_wal_size_bytes(parsed.get("pg.settings")),
    )
    out: list[Finding] = []
    for s in slots.all:
        start = lsn_to_int(s.restart_lsn)
        if start is None or current <= start:
            continue
        retained = current - start
        if retained < warn_at:
            continue
        sev = (
            "critical" if retained >= _RETAINED_CRIT else "warning"
        )
        gib = retained / (1024 ** 3)
        out.append(
            Finding(
                rule_id="pg.repl.slot_retaining_wal",
                severity=sev,
                title=(
                    f"Slot {s.slot_name!r} is retaining "
                    f"{gib:.1f} GiB of WAL"
                ),
                detail=(
                    f"{s.slot_type.capitalize()} slot "
                    f"'{s.slot_name}' has restart_lsn "
                    f"{s.restart_lsn} against a current WAL "
                    f"position of {wp.current_wal_lsn}, so it is "
                    f"holding {gib:.1f} GiB that cannot be "
                    "recycled. The slot is "
                    f"{'active' if s.active else 'inactive'}: an "
                    "active slot retaining this much means its "
                    "consumer is falling behind rather than "
                    "absent. Check the consumer, and consider "
                    "max_slot_wal_keep_size so a stalled "
                    "consumer costs the slot instead of the "
                    "filesystem."
                ),
            )
        )
    return out


@register("Replication")
def replica_disconnected(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when a physical replication slot has no connected replica.

    Cross-references ``pg.replication_slots`` (physical slots) with
    ``pg.replication`` (currently connected replicas). A physical slot
    whose ``slot_name`` does not appear as any replica's
    ``application_name`` indicates the replica has disconnected while
    the slot is still retaining WAL.
    """
    slots: ReplicationSlots | None = parsed.get(
        "pg.replication_slots"
    )
    if slots is None:
        return []
    replicas: list[ReplicationReplica] = (
        parsed.get("pg.replication") or []
    )
    connected = {r.application_name for r in replicas}
    gone = [
        s for s in slots.all
        if s.slot_type == "physical"
        and s.slot_name not in connected
    ]
    if not gone:
        return []
    names = ", ".join(s.slot_name for s in gone)
    return [
        Finding(
            rule_id="pg.repl.replica_disconnected",
            severity="warning",
            title=(
                f"{len(gone)} physical replication slot(s) "
                "have no connected replica"
            ),
            detail=(
                f"Physical slot(s) with no matching replica "
                f"in pg_stat_replication: {names}. The replica "
                "is not currently streaming; WAL is being "
                "retained by the slot. If the replica is "
                "permanently gone, drop the slot to release "
                "WAL retention (SELECT pg_drop_replication_slot"
                "('name'))."
            ),
        )
    ]


@register("Replication")
def logical_replication_spilling(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when logical replication slots are spilling to disk.

    Spills happen when a transaction exceeds
    ``logical_decoding_work_mem`` and PostgreSQL has to write
    decoded WAL to ``pg_replslot`` instead of streaming it
    directly. Frequent spilling indicates either large
    transactions on the publisher or an undersized
    ``logical_decoding_work_mem`` on PG14+.
    """
    stats: StatReplicationSlots | None = parsed.get(
        "pg.stat_replication_slots"
    )
    if stats is None:
        return []
    spilling = stats.spilling()
    if not spilling:
        return []
    spilling.sort(key=lambda s: -s.spill_bytes)
    examples, suffix = top_n(
        spilling,
        lambda s: (
            f"{s.slot_name} ({s.spill_count:,} spills, "
            f"{s.spill_bytes / (1024 * 1024):.0f} MiB)"
        ),
    )
    return [
        Finding(
            rule_id="pg.repl.logical_spilling",
            severity="warning",
            title=(
                f"{len(spilling)} logical slot(s) spilling "
                "to disk"
            ),
            detail=(
                "Logical decoding wrote partial transactions "
                "to disk because they exceeded "
                "``logical_decoding_work_mem``. "
                f"Top offenders: {examples}{suffix}. Either "
                "raise ``logical_decoding_work_mem`` on the "
                "publisher (PG14+) or reduce the size of the "
                "transactions being decoded."
            ),
        )
    ]
