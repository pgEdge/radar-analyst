"""Parsers for the WAL / replication slots / archiver side.

Covers:
- ``postgresql/archiver.tsv``         : pg_stat_archiver
- ``postgresql/replication_slots.tsv``: pg_replication_slots
- ``postgresql/replication.tsv``      : pg_stat_replication
  (streaming replicas visible from the primary)
- ``postgresql/wal_receiver.tsv``     : pg_stat_wal_receiver
  (WAL receiver on a standby)
- ``postgresql/subscriptions.tsv``    : pg_stat_subscription
  (logical replication subscription workers)
- ``postgresql/wal_position.tsv``     : WAL position and
  recovery state
- ``postgresql/replication_origin.tsv``:
  pg_replication_origin_status
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radar_analyst.parse.coerce import (
    row_int,
)
from radar_analyst.parse.pg_activity import parse_pg_interval_seconds
from radar_analyst.parse.tsv import parse_tsv_bytes


@dataclass(frozen=True)
class PgArchiver:
    """pg_stat_archiver counters."""
    archived_count: int = 0
    last_archived_wal: str = ""
    last_archived_time: str = ""
    failed_count: int = 0
    last_failed_wal: str = ""
    last_failed_time: str = ""

    @property
    def has_recent_failure(self) -> bool:
        """True when the most recent archive attempt failed.

        ``pg_stat_archiver`` records both ``last_archived_time`` and
        ``last_failed_time``; we treat "most recent failure after most
        recent success" as a live-failure signal worth warning on.
        """
        if not self.last_failed_time:
            return False
        if not self.last_archived_time:
            return self.failed_count > 0
        return self.last_failed_time > self.last_archived_time


def parse_archiver(data: bytes) -> PgArchiver | None:
    """Parse archiver.tsv into PgArchiver."""
    t = parse_tsv_bytes(data)
    if not t.rows:
        return None
    r = t.rows[0]

    return PgArchiver(
        archived_count=row_int(r, "archived_count"),
        last_archived_wal=r.get("last_archived_wal", "") or "",
        last_archived_time=r.get("last_archived_time", "")
        or "",
        failed_count=row_int(r, "failed_count"),
        last_failed_wal=r.get("last_failed_wal", "") or "",
        last_failed_time=r.get("last_failed_time", "") or "",
    )


@dataclass(frozen=True)
class ReplicationSlot:
    """One pg_replication_slots row."""
    slot_name: str
    slot_type: str
    database: str
    active: bool
    restart_lsn: str
    wal_status: str  # 'reserved' / 'extended' / 'unreserved' / 'lost'


@dataclass(frozen=True)
class ReplicationSlots:
    """All slots, with inactive and lost views."""
    all: list[ReplicationSlot] = field(default_factory=list)

    @property
    def inactive(self) -> list[ReplicationSlot]:
        """The slots not currently active."""
        return [s for s in self.all if not s.active]

    @property
    def lost(self) -> list[ReplicationSlot]:
        """The slots whose retained WAL is already lost."""
        return [s for s in self.all if s.wal_status == "lost"]


def parse_replication_slots(
    data: bytes,
) -> ReplicationSlots:
    """Parse replication_slots.tsv."""
    t = parse_tsv_bytes(data)
    slots: list[ReplicationSlot] = []
    for r in t.rows:
        name = r.get("slot_name", "")
        if not name:
            continue
        active_raw = (r.get("active", "") or "").lower()
        slots.append(
            ReplicationSlot(
                slot_name=name,
                slot_type=r.get("slot_type", ""),
                database=r.get("database", ""),
                active=active_raw in ("t", "true", "1"),
                restart_lsn=r.get("restart_lsn", "") or "",
                wal_status=r.get("wal_status", "") or "",
            )
        )
    return ReplicationSlots(all=slots)


# ---------------------------------------------------------------------------
# LSN arithmetic helper
# ---------------------------------------------------------------------------


def _lsn_to_int(lsn: str) -> int | None:
    """Convert a PostgreSQL LSN string (``X/YYYYYYYY``) to an int.

    Returns ``None`` for empty or unparseable input.
    """
    parts = lsn.split("/")
    if len(parts) != 2:
        return None
    try:
        return (int(parts[0], 16) << 32) | int(parts[1], 16)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# pg_stat_replication: streaming replica rows visible on the primary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplicationReplica:
    """One row from pg_stat_replication."""

    application_name: str
    client_addr: str
    state: str          # streaming | catchup | startup | backup | stopping
    sync_state: str     # async | potential | sync | quorum
    replay_lag_s: float | None  # None when replica is caught up / NULL

    # LSN columns: empty when absent / not reported
    sent_lsn: str = ""
    write_lsn: str = ""
    flush_lsn: str = ""
    replay_lsn: str = ""

    @property
    def lsn_lag_bytes(self) -> int | None:
        """Byte lag = sent_lsn − replay_lsn.

        Returns ``None`` when either LSN is absent or the
        difference is negative (should never happen in practice).
        """
        hi = _lsn_to_int(self.sent_lsn)
        lo = _lsn_to_int(self.replay_lsn)
        if hi is None or lo is None:
            return None
        diff = hi - lo
        return diff if diff >= 0 else None


def parse_replication(
    data: bytes,
) -> list[ReplicationReplica] | None:
    """Parse ``postgresql/replication.tsv``.

    Returns ``None`` for completely empty input (file absent);
    returns ``[]`` when the table is present but has no rows
    (no replicas connected).
    """
    raw = data.strip()
    if not raw:
        return None
    t = parse_tsv_bytes(data)
    out: list[ReplicationReplica] = []
    for r in t.rows:
        out.append(
            ReplicationReplica(
                application_name=(
                    r.get("application_name") or ""
                ),
                client_addr=r.get("client_addr") or "",
                state=r.get("state") or "",
                sync_state=r.get("sync_state") or "",
                replay_lag_s=parse_pg_interval_seconds(
                    r.get("replay_lag") or ""
                ),
                sent_lsn=r.get("sent_lsn") or "",
                write_lsn=r.get("write_lsn") or "",
                flush_lsn=r.get("flush_lsn") or "",
                replay_lsn=r.get("replay_lsn") or "",
            )
        )
    return out


# ---------------------------------------------------------------------------
# pg_current_wal_lsn / recovery status: wal_position.tsv
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalPosition:
    """Row from ``postgresql/wal_position.tsv``.

    Combines ``pg_current_wal_lsn()``, ``pg_is_in_recovery()``,
    and the recovery-LSN/timestamp functions into a single row.
    Fields are empty strings when the host is a primary and the
    recovery-side functions return NULL.
    """

    current_wal_lsn: str
    is_in_recovery: bool
    last_wal_receive_lsn: str = ""
    last_wal_replay_lsn: str = ""
    last_xact_replay_timestamp: str = ""


def parse_wal_position(data: bytes) -> WalPosition | None:
    """Parse ``postgresql/wal_position.tsv``.

    Returns ``None`` for completely empty input or a header-only
    file with no data rows.
    """
    t = parse_tsv_bytes(data)
    if not t.rows:
        return None
    r = t.rows[0]
    recovery_raw = (r.get("is_in_recovery") or "").lower()
    return WalPosition(
        current_wal_lsn=r.get("current_wal_lsn") or "",
        is_in_recovery=recovery_raw in ("t", "true", "1"),
        last_wal_receive_lsn=(
            r.get("last_wal_receive_lsn") or ""
        ),
        last_wal_replay_lsn=(
            r.get("last_wal_replay_lsn") or ""
        ),
        last_xact_replay_timestamp=(
            r.get("last_xact_replay_timestamp") or ""
        ),
    )


# ---------------------------------------------------------------------------
# pg_replication_origin_status: replication_origin.tsv
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplicationOrigin:
    """One row from ``postgresql/replication_origin.tsv``."""

    local_id: str
    external_id: str
    remote_lsn: str
    local_lsn: str


def parse_replication_origins(
    data: bytes,
) -> list[ReplicationOrigin] | None:
    """Parse ``postgresql/replication_origin.tsv``.

    Returns ``None`` for completely empty input; ``[]`` when the
    table is present but has no rows (no origins configured).
    """
    raw = data.strip()
    if not raw:
        return None
    t = parse_tsv_bytes(data)
    out: list[ReplicationOrigin] = []
    for r in t.rows:
        local_id = r.get("local_id") or ""
        if not local_id:
            continue
        out.append(
            ReplicationOrigin(
                local_id=local_id,
                external_id=r.get("external_id") or "",
                remote_lsn=r.get("remote_lsn") or "",
                local_lsn=r.get("local_lsn") or "",
            )
        )
    return out


# ---------------------------------------------------------------------------
# pg_stat_wal_receiver: WAL receiver on a standby
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalReceiver:
    """Single row from pg_stat_wal_receiver (standby-side)."""

    status: str         # streaming | catchup | stopped
    sender_host: str
    sender_port: int
    slot_name: str      # empty string when no slot


def parse_wal_receiver(data: bytes) -> WalReceiver | None:
    """Parse ``postgresql/wal_receiver.tsv``.

    Returns ``None`` if the file is absent or the table has no
    rows (i.e. this host is not a standby, or the receiver is not
    running).
    """
    t = parse_tsv_bytes(data)
    if not t.rows:
        return None
    r = t.rows[0]
    try:
        port = int(r.get("sender_port") or "0")
    except ValueError:
        port = 0
    return WalReceiver(
        status=r.get("status") or "",
        sender_host=r.get("sender_host") or "",
        sender_port=port,
        slot_name=r.get("slot_name") or "",
    )


# ---------------------------------------------------------------------------
# pg_stat_subscription: logical subscription workers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subscription:
    """One worker row from pg_stat_subscription."""

    subname: str
    pid: int | None     # None when the apply worker is not running


def parse_subscriptions(data: bytes) -> list[Subscription] | None:
    """Parse ``postgresql/subscriptions.tsv``.

    Returns ``None`` for completely empty input; ``[]`` when the
    table has no rows (no subscriptions).
    """
    raw = data.strip()
    if not raw:
        return None
    t = parse_tsv_bytes(data)
    # pg_stat_subscription has one row per worker; the main apply
    # worker has relid = NULL. We deduplicate by subname keeping the
    # apply-worker row (relid empty/null) so each subscription is
    # counted once for the "running?" check.
    by_name: dict[str, Subscription] = {}
    for r in t.rows:
        name = r.get("subname") or ""
        if not name:
            continue
        pid_raw = r.get("pid") or ""
        pid: int | None = None
        if pid_raw.strip():
            try:
                pid = int(pid_raw.strip())
            except ValueError:
                pass
        relid = r.get("relid") or ""
        is_apply_worker = relid.strip() == ""
        if name not in by_name or is_apply_worker:
            by_name[name] = Subscription(
                subname=name, pid=pid
            )
    return list(by_name.values())
