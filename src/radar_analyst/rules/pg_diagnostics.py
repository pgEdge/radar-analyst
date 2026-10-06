"""Deterministic rules for progress and diagnostics data."""

from __future__ import annotations

from typing import Any

from radar_analyst.parse.pg_diagnostics import PgRole, ProgressRow
from radar_analyst.rules.base import Finding, register


# System roles: postgres is the expected superuser; pg_* prefix
# roles are internal PostgreSQL system roles.
_SYSTEM_SUPERUSERS = {"postgres"}
_SYSTEM_ROLE_PREFIX = "pg_"


@register("Internals & I/O Health")
def superuser_count_high(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when any superuser beyond ``postgres`` exists.

    ``postgres`` is the expected superuser on every cluster. Any
    additional role with ``rolsuper=true`` (excluding system roles
    with the ``pg_`` prefix) is unusual and worth a security
    audit, and multiple superusers make privilege review
    difficult.
    """
    roles: list[PgRole] | None = parsed.get("pg.roles")
    if not roles:
        return []
    extra = [
        r for r in roles
        if r.rolsuper
        and r.rolname not in _SYSTEM_SUPERUSERS
        and not r.rolname.startswith(_SYSTEM_ROLE_PREFIX)
    ]
    if not extra:
        return []
    names = ", ".join(r.rolname for r in extra)
    return [
        Finding(
            rule_id="pg.superuser_count_high",
            severity="warning",
            title=(
                f"{len(extra)} unexpected superuser role(s): "
                f"{names}"
            ),
            detail=(
                f"The following role(s) have superuser "
                f"privilege beyond the expected 'postgres' "
                f"account: {names}. Superuser bypass all "
                "access controls. Revoke SUPERUSER from roles "
                "that do not require it, and use predefined "
                "roles (pg_read_all_data, pg_write_all_data, "
                "pg_monitor) instead."
            ),
        )
    ]


@register("Internals & I/O Health")
def replication_role_present(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when a non-system role has the REPLICATION attribute.

    The REPLICATION attribute allows a role to connect in
    replication mode and read the WAL stream. It should be granted
    only to a dedicated replication role, not to application roles.
    Having it on unexpected roles is a permissions smell and an
    audit risk.
    """
    roles: list[PgRole] | None = parsed.get("pg.roles")
    if not roles:
        return []
    flagged = [
        r for r in roles
        if r.rolreplication
        and r.rolname not in _SYSTEM_SUPERUSERS
        and not r.rolname.startswith(_SYSTEM_ROLE_PREFIX)
    ]
    if not flagged:
        return []
    names = ", ".join(r.rolname for r in flagged)
    return [
        Finding(
            rule_id="pg.replication_role_present",
            severity="warning",
            title=(
                f"Non-system role(s) with REPLICATION "
                f"attribute: {names}"
            ),
            detail=(
                f"Role(s) {names} have the REPLICATION "
                "attribute set. This allows connecting in "
                "replication mode and reading the WAL stream. "
                "Ensure this is a dedicated replication role "
                "and not an application role that was "
                "accidentally granted REPLICATION. Revoke with: "
                f"ALTER ROLE <name> NOREPLICATION."
            ),
        )
    ]


# ---------------------------------------------------------------
# Progress-operation rules: DBA needs visibility into heavy
# maintenance operations that were active at snapshot time.
# ---------------------------------------------------------------

def _progress_dbs(rows: list[ProgressRow]) -> str:
    """Summarise databases and phases from progress rows."""
    dbs = sorted({r.datname for r in rows if r.datname})
    phases = sorted({r.phase for r in rows if r.phase})
    parts: list[str] = []
    if dbs:
        parts.append(f"db(s): {', '.join(dbs)}")
    if phases:
        parts.append(f"phase(s): {', '.join(phases)}")
    return "; ".join(parts) if parts else ""


# Vacuum early-progress threshold: if <10 % of blocks done,
# the vacuum may be stuck or just started on a very large table.
_VACUUM_EARLY_PCT = 0.10


@register("Internals & I/O Health")
def vacuum_in_progress(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Report when VACUUM is active at snapshot time.

    ``stat_progress_vacuum`` only has rows while a vacuum runs.
    If ``blocks_done / blocks_total < 10 %``, warn: the vacuum
    is either very early or potentially stuck on a large table.
    """
    rows: list[ProgressRow] | None = parsed.get(
        "pg.stat_progress_vacuum"
    )
    if not rows:
        return []
    # Check for early-progress condition.
    early = any(
        r.blocks_total is not None
        and r.blocks_total > 0
        and r.blocks_done is not None
        and r.blocks_done / r.blocks_total < _VACUUM_EARLY_PCT
        for r in rows
    )
    sev = "warning" if early else "info"
    ctx = _progress_dbs(rows)
    early_note = (
        " At least one vacuum has completed < 10% of its "
        "target: it may be stuck or processing a very "
        "large table."
        if early else ""
    )
    return [
        Finding(
            rule_id="pg.vacuum_in_progress",
            severity=sev,
            title=(
                f"{len(rows)} active VACUUM operation(s) "
                "at snapshot time"
            ),
            detail=(
                f"{len(rows)} VACUUM operation(s) were "
                f"running when radar captured this snapshot. "
                f"{ctx}.{early_note} Active vacuums hold "
                "back xmin advancement and can cause table "
                "bloat on other tables if they run for a "
                "long time."
            ),
        )
    ]


@register("Internals & I/O Health")
def create_index_in_progress(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Report when CREATE INDEX is active at snapshot time.

    Index builds consume significant CPU and I/O. Concurrent
    index builds (``CREATE INDEX CONCURRENTLY``) also hold a
    weak lock that can still block schema changes.
    """
    rows: list[ProgressRow] | None = parsed.get(
        "pg.stat_progress_create_index"
    )
    if not rows:
        return []
    ctx = _progress_dbs(rows)
    return [
        Finding(
            rule_id="pg.create_index_in_progress",
            severity="info",
            title=(
                f"{len(rows)} active CREATE INDEX "
                "operation(s) at snapshot time"
            ),
            detail=(
                f"{len(rows)} index build(s) were running "
                f"when radar captured this snapshot. {ctx}. "
                "Index builds are I/O- and CPU-intensive; "
                "concurrent builds hold a weak lock that "
                "blocks schema changes on the target table."
            ),
        )
    ]


@register("Internals & I/O Health")
def analyze_in_progress(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Report when ANALYZE is active at snapshot time.

    A long-running ANALYZE on a large table can indicate
    statistics collection falling behind or manual ANALYZE on a
    partitioned parent with many children.
    """
    rows: list[ProgressRow] | None = parsed.get(
        "pg.stat_progress_analyze"
    )
    if not rows:
        return []
    ctx = _progress_dbs(rows)
    return [
        Finding(
            rule_id="pg.analyze_in_progress",
            severity="info",
            title=(
                f"{len(rows)} active ANALYZE operation(s) "
                "at snapshot time"
            ),
            detail=(
                f"{len(rows)} ANALYZE operation(s) were "
                f"running when radar captured this snapshot. "
                f"{ctx}. A long-running ANALYZE may indicate "
                "stale statistics on a large table or a "
                "manual ANALYZE on a partitioned parent."
            ),
        )
    ]


@register("Internals & I/O Health")
def basebackup_in_progress(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Report when pg_basebackup is active at snapshot time.

    A running base backup consumes a WAL sender slot and
    network bandwidth. On a busy primary this can affect
    replication throughput.
    """
    rows: list[ProgressRow] | None = parsed.get(
        "pg.stat_progress_basebackup"
    )
    if not rows:
        return []
    return [
        Finding(
            rule_id="pg.basebackup_in_progress",
            severity="info",
            title=(
                f"{len(rows)} active base backup(s) "
                "at snapshot time"
            ),
            detail=(
                f"{len(rows)} pg_basebackup operation(s) "
                "were running when radar captured this "
                "snapshot. Base backups consume a WAL sender "
                "slot and network bandwidth; on a busy "
                "primary this can affect replication "
                "throughput to standbys."
            ),
        )
    ]


@register("Internals & I/O Health")
def cluster_or_copy_in_progress(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Report when CLUSTER or COPY is active at snapshot time.

    CLUSTER rewrites an entire table (exclusive lock). COPY
    is a bulk-load operation that can generate heavy WAL and
    I/O. Both are worth noting for DBA awareness.
    """
    cluster: list[ProgressRow] | None = parsed.get(
        "pg.stat_progress_cluster"
    )
    copy: list[ProgressRow] | None = parsed.get(
        "pg.stat_progress_copy"
    )
    rows = (cluster or []) + (copy or [])
    if not rows:
        return []
    ops: list[str] = []
    if cluster:
        ops.append(f"{len(cluster)} CLUSTER")
    if copy:
        ops.append(f"{len(copy)} COPY")
    ctx = _progress_dbs(rows)
    return [
        Finding(
            rule_id="pg.cluster_or_copy_in_progress",
            severity="info",
            title=(
                f"{' + '.join(ops)} operation(s) "
                "at snapshot time"
            ),
            detail=(
                f"Heavy I/O operation(s) were running when "
                f"radar captured this snapshot: "
                f"{', '.join(ops)}. {ctx}. CLUSTER rewrites "
                "a table with an exclusive lock; COPY is a "
                "bulk-load that generates heavy WAL traffic."
            ),
        )
    ]
