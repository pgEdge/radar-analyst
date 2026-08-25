"""Internals & I/O Health rules over storage hygiene: wraparound,
dead rows, bloat, TOAST, duplicate/unused indexes, sequences."""

from __future__ import annotations

from typing import Any

from collections import defaultdict

from radar_analyst.analyze.humanize import format_size_bytes
from radar_analyst.parse.databases import DatabaseInfo
from radar_analyst.parse.pg_db_bloat import (
    BloatPerDb,
    PgStatTuplePerDb,
)
from radar_analyst.parse.pg_db_indexes import IndexesPerDb, IndexRow
from radar_analyst.parse.pg_db_sequences import SequencesPerDb
from radar_analyst.parse.pg_db_tables import TablesPerDb
from radar_analyst.parse.pg_settings import PgSettings
from radar_analyst.parse.pg_wal import PgArchiver
from radar_analyst.rules.base import Finding, register

# Wraparound is a critical event at age >= 2 billion (autovacuum's
# emergency threshold). PostgreSQL's hard ceiling is ~2.1B before
# the cluster refuses transactions. Warn at 500M (2.5× the default
# autovacuum_freeze_max_age of 200M: autovacuum should have run
# by now and hasn't); critical at 1.5B is well into "must act now".
_WRAPAROUND_WARN_AGE = 500_000_000
_WRAPAROUND_CRIT_AGE = 1_500_000_000

# Dead-row floor: tables with very few rows can show high dead
# ratios harmlessly during normal churn.
_DEAD_RATIO_WARN = 0.20
_DEAD_TUP_FLOOR = 1000
# A single hot table > 50% dead AND > 100k dead tuples is bad
# enough that we crit even if average across the cluster is fine.
_DEAD_RATIO_CRIT = 0.50
_DEAD_TUP_CRIT_FLOOR = 100_000

# TOAST-dominates-heap thresholds. Ratio-only gating fires
# noisily on tiny tables (an 8 KiB heap with a 144 KiB TOAST is
# 18× yet operationally meaningless).
# Gate on absolute TOAST size first so we only flag schema-design
# red flags worth a DBA's attention; ratio confirms TOAST genuinely
# dominates rather than just matching heap.
_TOAST_DOMINATES_FLOOR = 100 * 1024 * 1024  # 100 MiB
_TOAST_DOMINATES_RATIO = 2.0

# Autovacuum-lagging thresholds. Defaults mirror PostgreSQL:
# autovacuum_vacuum_threshold=50 + autovacuum_vacuum_scale_factor=0.2;
# the PG13+ insert-arm defaults are 1000 + 0.2 (insert_scale_factor).
# Used when pg.settings is missing the corresponding entries: keeps
# the rule operational on truncated snapshots.
_AV_VACUUM_THRESHOLD_DEFAULT = 50
_AV_VACUUM_SCALE_DEFAULT = 0.2
_AV_INSERT_THRESHOLD_DEFAULT = 1000
_AV_INSERT_SCALE_DEFAULT = 0.2
# Anything older than 1 hour while the table is over the
# autovacuum eligibility threshold is "autovacuum is blocked or
# unable to keep up": distinct from `tables_high_dead_rows`,
# which fires on percentage regardless of why.
_AV_LAGGING_AGE_S = 3600


@register("Internals & I/O Health")
def txid_wraparound_high(parsed: dict[str, Any]) -> list[Finding]:
    """Critical when any database's xid age approaches the hard
    wraparound ceiling.

    Threshold tiers:
    - age >= 1.5B → critical (autovacuum's emergency vacuum has
      probably already kicked in; manual intervention warranted).
    - age >= 500M → warning (operator runway).
    """
    dbs: list[DatabaseInfo] | None = parsed.get("pg.databases")
    if not dbs:
        return []
    worst: DatabaseInfo | None = None
    worst_age = 0
    for d in dbs:
        if d.frozenxid_age is None:
            continue
        if d.frozenxid_age > worst_age:
            worst_age = d.frozenxid_age
            worst = d
    if worst is None or worst_age < _WRAPAROUND_WARN_AGE:
        return []
    severity = (
        "critical"
        if worst_age >= _WRAPAROUND_CRIT_AGE
        else "warning"
    )
    return [
        Finding(
            rule_id="pg.health.txid_wraparound_high",
            severity=severity,
            title=(
                f"TXID age on {worst.datname} is "
                f"{worst_age:,}"
            ),
            detail=(
                f"Database {worst.datname} has datfrozenxid age "
                f"{worst_age:,} (out of a hard ceiling near "
                "2.1 billion). Wraparound stops accepting new "
                "transactions cluster-wide. Check that "
                "autovacuum is running, that no long-running "
                "transactions are blocking xmin advance, and "
                "consider a manual VACUUM (FREEZE) on the "
                "oldest tables."
            ),
        )
    ]


@register("Internals & I/O Health")
def invalid_databases(parsed: dict[str, Any]) -> list[Finding]:
    """Critical when any database has ``datconnlimit = -2``.

    A ``-2`` connection limit means the database was being
    dropped when the cluster crashed and is now in a
    transitional state: it can't be connected to and can't be
    cleanly dropped without manual catalog cleanup.
    """
    dbs: list[DatabaseInfo] | None = parsed.get("pg.databases")
    if not dbs:
        return []
    invalid = [d.datname for d in dbs if d.datconnlimit == -2]
    if not invalid:
        return []
    return [
        Finding(
            rule_id="pg.health.invalid_databases",
            severity="critical",
            title=(
                f"{len(invalid)} database(s) in invalid state"
            ),
            detail=(
                "Databases with datconnlimit = -2 are stuck "
                "mid-drop after a crash and need manual "
                f"recovery: {', '.join(invalid)}. They can't "
                "be reconnected to or dropped cleanly without "
                "DBA intervention (typically pg_database "
                "catalog surgery in single-user mode)."
            ),
        )
    ]


@register("Internals & I/O Health")
def tables_high_dead_rows(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Warn when user tables have a high dead-row ratio.

    Iterates every per-database tables snapshot. Warns at >20%
    dead with >1k tuples either side, and elevates to critical
    for any single table that is >50% dead with >100k dead
    tuples, because the operator wants to know about that one
    specifically, even if cluster average is fine.
    """
    tpd_by_db: dict[str, TablesPerDb] = (
        parsed.get("pg.db.tables") or {}
    )
    if not tpd_by_db:
        return []
    offenders: list[tuple[str, str, float, int]] = []
    crit_offenders: list[tuple[str, str, float, int]] = []
    for db, tpd in tpd_by_db.items():
        for row in tpd.rows:
            denom = row.n_live_tup + row.n_dead_tup
            if (
                row.n_live_tup < _DEAD_TUP_FLOOR
                and row.n_dead_tup < _DEAD_TUP_FLOOR
            ):
                continue
            ratio = row.dead_ratio
            if ratio < _DEAD_RATIO_WARN or denom == 0:
                continue
            entry = (db, row.fqname, ratio, row.n_dead_tup)
            offenders.append(entry)
            if (
                ratio >= _DEAD_RATIO_CRIT
                and row.n_dead_tup >= _DEAD_TUP_CRIT_FLOOR
            ):
                crit_offenders.append(entry)
    if not offenders:
        return []
    severity = "critical" if crit_offenders else "warning"
    offenders.sort(key=lambda x: -x[2])
    top = offenders[:5]
    examples = "; ".join(
        f"{db}/{name} {ratio * 100:.0f}% dead "
        f"({dead:,} tuples)"
        for db, name, ratio, dead in top
    )
    suffix = (
        f" (+{len(offenders) - 5} more)"
        if len(offenders) > 5
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.tables_high_dead_rows",
            severity=severity,
            title=(
                f"{len(offenders)} table(s) above "
                "20% dead rows"
            ),
            detail=(
                "High dead-tuple percentages waste space and "
                "degrade scan performance. Top offenders: "
                f"{examples}{suffix}. Tune autovacuum "
                "(autovacuum_vacuum_scale_factor / "
                "autovacuum_vacuum_insert_scale_factor on "
                "PG13+) or run a manual VACUUM."
            ),
        )
    ]


def _av_int_setting(
    settings: PgSettings | None, name: str, default: int
) -> int:
    if settings is None:
        return default
    s = settings.get(name)
    if s is None or not s.setting:
        return default
    try:
        return int(s.setting)
    except ValueError:
        return default


def _av_float_setting(
    settings: PgSettings | None, name: str, default: float
) -> float:
    if settings is None:
        return default
    s = settings.get(name)
    if s is None or not s.setting:
        return default
    try:
        return float(s.setting)
    except ValueError:
        return default


def _autovacuum_overdue(
    tpd_by_db: dict[str, TablesPerDb],
    settings: PgSettings | None,
) -> list[tuple[str, str, int, int]]:
    """Tables past an autovacuum arm with a stale last run.

    PG runs autovacuum when EITHER arm trips, not when both do.
    The dead-tup arm uses the vacuum threshold, the
    insert-since-vacuum arm the insert threshold; either
    condition plus the age gate fires.
    """
    vac_t = _av_int_setting(
        settings,
        "autovacuum_vacuum_threshold",
        _AV_VACUUM_THRESHOLD_DEFAULT,
    )
    vac_s = _av_float_setting(
        settings,
        "autovacuum_vacuum_scale_factor",
        _AV_VACUUM_SCALE_DEFAULT,
    )
    ins_t = _av_int_setting(
        settings,
        "autovacuum_vacuum_insert_threshold",
        _AV_INSERT_THRESHOLD_DEFAULT,
    )
    ins_s = _av_float_setting(
        settings,
        "autovacuum_vacuum_insert_scale_factor",
        _AV_INSERT_SCALE_DEFAULT,
    )
    offenders: list[tuple[str, str, int, int]] = []
    for db, tpd in tpd_by_db.items():
        for row in tpd.rows:
            age = row.last_autovacuum_age_seconds
            if age is None or age <= _AV_LAGGING_AGE_S:
                continue
            vac_elig = vac_t + vac_s * row.reltuples
            ins_elig = ins_t + ins_s * row.reltuples
            dead_overdue = row.n_dead_tup > vac_elig
            ins_overdue = (
                row.n_ins_since_vacuum is not None
                and row.n_ins_since_vacuum > ins_elig
            )
            if dead_overdue or ins_overdue:
                offenders.append(
                    (db, row.fqname, row.n_dead_tup, age)
                )
    return offenders


@register("Internals & I/O Health")
def autovacuum_lagging(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when a table is eligible for autovacuum but it didn't run.

    Eligibility (PG13+ two-arm): fire if EITHER arm is over:
      vacuum_threshold + vacuum_scale * reltuples
      OR
      insert_threshold + insert_scale * reltuples
    AND ``last_autovacuum_age_seconds > 3600`` (radar 0.5.0+).

    Distinct from ``tables_high_dead_rows`` (which fires on
    percentage regardless of why): this rule fires when
    autovacuum is *supposed* to have run by now and didn't:
    i.e. autovacuum is blocked, the workers are saturated, or
    a long transaction is holding the xmin horizon back.

    Pre-0.5.0 zips don't carry ``last_autovacuum_age_seconds``;
    the parser fills None and the rule silently skips so we
    don't over-fire on missing data.
    """
    tpd_by_db: dict[str, TablesPerDb] = (
        parsed.get("pg.db.tables") or {}
    )
    if not tpd_by_db:
        return []
    offenders = _autovacuum_overdue(
        tpd_by_db, parsed.get("pg.settings")
    )
    if not offenders:
        return []
    offenders.sort(key=lambda t: -t[3])  # oldest age first
    top = offenders[:5]
    examples = "; ".join(
        f"{db}/{name} "
        f"({dead:,} dead tup, last autovac "
        f"{age // 3600}h{(age % 3600) // 60:02d}m ago)"
        for db, name, dead, age in top
    )
    suffix = (
        f" (+{len(offenders) - 5} more)"
        if len(offenders) > 5
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.autovacuum_lagging",
            severity="warning",
            title=(
                f"{len(offenders)} table(s) overdue for "
                "autovacuum"
            ),
            detail=(
                "These tables are past the autovacuum "
                "eligibility threshold AND haven't been "
                f"autovacuumed in over an hour: {examples}"
                f"{suffix}. Common causes: a long transaction "
                "holding xmin back, workers saturated by huge "
                "tables, or a table with "
                "autovacuum_enabled = off in reloptions. "
                "Investigate pg_stat_progress_vacuum, the "
                "longest-running transaction, and "
                "autovacuum_max_workers."
            ),
        )
    ]


@register("Internals & I/O Health")
def autovacuum_disabled_per_table(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Critical when any user table has autovacuum_enabled = off.

    Per-table autovacuum disable is a TXID-wraparound footgun:
    even one such table can age out and stop the whole cluster.
    """
    tpd_by_db: dict[str, TablesPerDb] = (
        parsed.get("pg.db.tables") or {}
    )
    if not tpd_by_db:
        return []
    offenders: list[str] = []
    for db, tpd in tpd_by_db.items():
        for row in tpd.rows:
            if row.autovacuum_disabled:
                offenders.append(f"{db}/{row.fqname}")
    if not offenders:
        return []
    shown = ", ".join(offenders[:10])
    suffix = (
        f" (+{len(offenders) - 10} more)"
        if len(offenders) > 10
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.autovacuum_disabled_per_table",
            severity="critical",
            title=(
                f"{len(offenders)} table(s) with "
                "autovacuum_enabled = off"
            ),
            detail=(
                "Disabling autovacuum on a table at the "
                "reloptions level risks bloat AND TXID "
                f"wraparound: {shown}{suffix}. Re-enable "
                "with ALTER TABLE … RESET "
                "(autovacuum_enabled), or commit to a strict "
                "external VACUUM schedule."
            ),
        )
    ]


def _toast_offenders(
    tpd_by_db: dict[str, TablesPerDb],
) -> list[tuple[str, str, int, int]]:
    """Tables whose TOAST size clears the floor and the ratio.

    Ratio is undefined when heap=0, but a multi-100-MiB TOAST
    with no heap is still a strong signal: count it as dominant.
    """
    offenders: list[tuple[str, str, int, int]] = []
    for db, tpd in tpd_by_db.items():
        for row in tpd.rows:
            ts = row.toast_size or 0
            if ts < _TOAST_DOMINATES_FLOOR:
                continue
            heap = row.heap_size
            if (
                heap > 0
                and (ts / heap) < _TOAST_DOMINATES_RATIO
            ):
                continue
            offenders.append((db, row.fqname, heap, ts))
    return offenders


@register("Internals & I/O Health")
def toast_dominates_heap(
    parsed: dict[str, Any],
) -> list[Finding]:
    """Info when a table's TOAST relation dwarfs its main heap.

    Signals a likely schema-design issue: large TEXT/BYTEA/JSONB
    columns paying decompression cost on every read, working-set
    blowup, often "blobs in DB instead of object store". Gated on
    absolute TOAST size so noise from tiny tables (e.g. an 8 KiB
    heap with 144 KiB TOAST) doesn't fire: only flags cases an
    operator would actually want to investigate.
    """
    tpd_by_db: dict[str, TablesPerDb] = (
        parsed.get("pg.db.tables") or {}
    )
    if not tpd_by_db:
        return []
    offenders = _toast_offenders(tpd_by_db)
    if not offenders:
        return []
    offenders.sort(key=lambda x: -x[3])
    top = offenders[:5]
    examples = "; ".join(
        f"{db}/{name} (heap {format_size_bytes(h)}, "
        f"toast {format_size_bytes(t)})"
        for db, name, h, t in top
    )
    suffix = (
        f" (+{len(offenders) - 5} more)"
        if len(offenders) > 5
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.toast_dominates_heap",
            severity="info",
            title=(
                f"{len(offenders)} table(s) where TOAST "
                "dominates main heap"
            ),
            detail=(
                "Large TEXT/BYTEA/JSONB columns are pushing most "
                "of the table's bytes into TOAST. Reads pay "
                "decompression cost, the working set inflates, "
                "and storing blobs in PostgreSQL is often a "
                "schema-design choice worth revisiting (object "
                f"storage, lo_*, external column store): "
                f"{examples}{suffix}."
            ),
        )
    ]


@register("Internals & I/O Health")
def duplicate_indexes(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when two or more user indexes share the same dedup key.

    Indexes with identical
    ``(indrelid, indclass, indkey, indexprs, indpred)`` are
    semantic duplicates regardless of name. Wastes disk and
    write throughput; only one should be kept.

    Pre-0.5.0 radar zips don't carry the dedup-key columns
    (radar's per-db ``indexes.tsv`` was just schemaname /
    tablename / indexname / indexdef back then). The parser
    fills missing columns with empty strings, which would
    otherwise collapse every index into one giant false-
    positive duplicate group. Detect that situation by checking
    whether any row has a non-empty ``indrelid``: that field is
    always populated on supported radar versions and never
    legitimately empty: and skip silently if the column is
    missing across the board.
    """
    idx_by_db: dict[str, IndexesPerDb] = (
        parsed.get("pg.db.indexes") or {}
    )
    if not idx_by_db:
        return []
    have_dedup_data = any(
        row.indrelid
        for ipd in idx_by_db.values()
        for row in ipd.rows
    )
    if not have_dedup_data:
        return []
    groups: list[tuple[str, list[IndexRow]]] = []
    for db, ipd in idx_by_db.items():
        bucket: dict[
            tuple[str, str, str, str, str], list[IndexRow]
        ] = defaultdict(list)
        for row in ipd.rows:
            bucket[row.dedup_key].append(row)
        for members in bucket.values():
            if len(members) > 1:
                groups.append((db, members))
    if not groups:
        return []
    # Top groups by total wasted bytes (everything beyond one).
    groups.sort(
        key=lambda dm: -sum(
            r.index_size for r in dm[1][1:]
        )
    )
    top = groups[:5]
    examples = "; ".join(
        f"{db} → "
        + ", ".join(r.fqname for r in members)
        for db, members in top
    )
    suffix = (
        f" (+{len(groups) - 5} more groups)"
        if len(groups) > 5
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.duplicate_indexes",
            severity="warning",
            title=(
                f"{len(groups)} duplicate-index group(s) "
                "found"
            ),
            detail=(
                "Each group below holds two or more indexes "
                "with identical key signatures. "
                f"Examples: {examples}{suffix}. Drop the "
                "redundant ones after confirming none are "
                "primary keys / referenced by foreign keys."
            ),
        )
    ]


@register("Internals & I/O Health")
def invalid_indexes(parsed: dict[str, Any]) -> list[Finding]:
    """Critical when any user index has indisvalid = false.

    Invalid indexes can't be used by the planner; they're
    typically left over from a failed CREATE INDEX
    CONCURRENTLY. Drop or REINDEX.
    """
    idx_by_db: dict[str, IndexesPerDb] = (
        parsed.get("pg.db.indexes") or {}
    )
    if not idx_by_db:
        return []
    bad: list[str] = []
    for db, ipd in idx_by_db.items():
        for row in ipd.rows:
            if not row.indisvalid:
                bad.append(f"{db}/{row.fqname}")
    if not bad:
        return []
    shown = ", ".join(bad[:10])
    suffix = (
        f" (+{len(bad) - 10} more)" if len(bad) > 10 else ""
    )
    return [
        Finding(
            rule_id="pg.health.invalid_indexes",
            severity="critical",
            title=(
                f"{len(bad)} invalid index(es): "
                "planner can't use them"
            ),
            detail=(
                "Invalid indexes are dead weight: dropped "
                "from query plans but still maintained on "
                f"every write. {shown}{suffix}. REINDEX "
                "INDEX <name> CONCURRENTLY (or DROP if the "
                "index is no longer needed)."
            ),
        )
    ]


@register("Internals & I/O Health")
def unused_indexes(parsed: dict[str, Any]) -> list[Finding]:
    """Info-level when sizable indexes have ``idx_scan = 0``.

    Fires only on indexes ≥ 64 MiB (smaller unused indexes
    aren't worth the operator's time). Primary keys are
    excluded: they must exist regardless of usage. Unique
    indexes are flagged so the operator knows to check FK
    references before dropping. The rule states the fact, and
    whether an index can be dropped is the operator's decision.
    """
    idx_by_db: dict[str, IndexesPerDb] = (
        parsed.get("pg.db.indexes") or {}
    )
    if not idx_by_db:
        return []
    candidates: list[tuple[str, IndexRow]] = []
    for db, ipd in idx_by_db.items():
        for row in ipd.rows:
            if row.indisprimary:
                continue
            if row.idx_scan != 0:
                continue
            if row.index_size < 64 * 1024 * 1024:
                continue
            candidates.append((db, row))
    if not candidates:
        return []
    candidates.sort(key=lambda dr: -dr[1].index_size)
    top = candidates[:10]
    examples = "; ".join(
        f"{db}/{row.fqname} "
        f"({row.index_size / (1024 * 1024):.0f} MiB"
        + (", unique" if row.indisunique else "")
        + ")"
        for db, row in top
    )
    suffix = (
        f" (+{len(candidates) - 10} more)"
        if len(candidates) > 10
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.unused_indexes",
            severity="info",
            title=(
                f"{len(candidates)} large index(es) with "
                "zero scans"
            ),
            detail=(
                f"{examples}{suffix}. idx_scan is 0. For "
                "unique indexes, check that no foreign keys "
                "reference the column set before dropping."
            ),
        )
    ]


def _sequence_bands(
    seq_by_db: dict[str, SequencesPerDb],
) -> tuple[
    list[tuple[str, str, float]],
    list[tuple[str, str, float]],
    list[tuple[str, str, float]],
]:
    """Bucket sequences into <1% / <5% / <10% remaining bands."""
    crit: list[tuple[str, str, float]] = []
    warn: list[tuple[str, str, float]] = []
    notice: list[tuple[str, str, float]] = []
    for db, spd in seq_by_db.items():
        for row in spd.rows:
            pct = row.remaining_percent
            if pct is None:
                continue
            entry = (db, row.fqname, pct)
            if pct < 1.0:
                crit.append(entry)
            elif pct < 5.0:
                warn.append(entry)
            elif pct < 10.0:
                notice.append(entry)
    return crit, warn, notice


@register("Internals & I/O Health")
def sequence_exhaustion(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when bounded sequences are running out of values.

    Tiered thresholds:
    - <10% remaining → notice (info)
    - <5% remaining  → warning
    - <1% remaining  → critical
    Unbounded bigint sequences and never-used sequences are
    skipped: neither is at risk.
    """
    seq_by_db: dict[str, SequencesPerDb] = (
        parsed.get("pg.db.sequences") or {}
    )
    if not seq_by_db:
        return []
    crit, warn, notice = _sequence_bands(seq_by_db)
    if not (crit or warn or notice):
        return []
    if crit:
        severity, bucket, label = (
            "critical", crit, "<1% remaining"
        )
    elif warn:
        severity, bucket, label = (
            "warning", warn, "<5% remaining"
        )
    else:
        severity, bucket, label = (
            "info", notice, "<10% remaining"
        )
    bucket.sort(key=lambda t: t[2])
    examples = "; ".join(
        f"{db}/{name} ({pct:.2f}% left)"
        for db, name, pct in bucket[:5]
    )
    extra = (
        f" (+{len(bucket) - 5} more in same band)"
        if len(bucket) > 5
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.sequence_exhaustion",
            severity=severity,
            title=(
                f"{len(bucket)} sequence(s) {label}"
            ),
            detail=(
                "Bounded sequences nearing their max value will "
                "eventually fail nextval() and break inserts. "
                f"Closest to exhaustion: {examples}{extra}. "
                "Either widen the column type (int → bigint), "
                "set CYCLE on the sequence (with a unique-key "
                "tolerance plan), or reset to a safe minvalue."
            ),
        )
    ]


def _pgstattuple_offenders(
    pgs: dict[str, PgStatTuplePerDb],
    seen: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """Bloated tables per pgstattuple, recording each in *seen*."""
    offenders: list[tuple[str, str, str]] = []
    for db, per in pgs.items():
        for row in per.rows:
            if row.dead_tuple_percent < 20.0:
                continue
            if row.dead_tuple_len < 100 * 1024 * 1024:
                continue
            seen.add((db, row.fqname))
            offenders.append(
                (
                    db,
                    row.fqname,
                    f"{row.dead_tuple_percent:.0f}% dead "
                    f"({row.dead_tuple_len / (1024 * 1024):.0f}"
                    " MiB)",
                )
            )
    return offenders


def _heuristic_bloat_offenders(
    bloat: dict[str, BloatPerDb],
    seen: set[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """Bloated tables per the pg_stats estimate, minus *seen*."""
    offenders: list[tuple[str, str, str]] = []
    for db, bper in bloat.items():
        for brow in bper.rows:
            if (db, brow.fqname) in seen:
                continue
            if brow.table_bloat_ratio < 2.0:
                continue
            if brow.wastedbytes < 256 * 1024 * 1024:
                continue
            offenders.append(
                (
                    db,
                    brow.fqname,
                    f"~{brow.table_bloat_ratio:.1f}× pages "
                    f"({brow.wastedbytes / (1024 * 1024):.0f}"
                    " MiB wasted, est.)",
                )
            )
    return offenders


@register("Internals & I/O Health")
def bloat_high(parsed: dict[str, Any]) -> list[Finding]:
    """Warn on heavily bloated user tables.

    Prefers ``pgstattuple`` (authoritative) when present;
    otherwise falls back to the pg_stats heuristic.
    Both inputs run per-database so the rule iterates the
    union of the two dicts.

    Thresholds:
    - pgstattuple: dead_tuple_percent ≥ 20% AND
      dead_tuple_len ≥ 100 MiB → warning
    - heuristic:  table_bloat_ratio ≥ 2.0 (= 50% wasted) AND
      wastedbytes ≥ 256 MiB → warning
    The size floors prevent the rule firing on tiny tables
    where percentages are statistically meaningless.
    """
    pgs: dict[str, PgStatTuplePerDb] = (
        parsed.get("pg.db.pgstattuple") or {}
    )
    bloat: dict[str, BloatPerDb] = (
        parsed.get("pg.db.bloat") or {}
    )
    if not pgs and not bloat:
        return []

    seen: set[tuple[str, str]] = set()
    offenders = _pgstattuple_offenders(pgs, seen)
    offenders.extend(_heuristic_bloat_offenders(bloat, seen))
    if not offenders:
        return []
    examples = "; ".join(
        f"{db}/{name} ({summary})"
        for db, name, summary in offenders[:5]
    )
    suffix = (
        f" (+{len(offenders) - 5} more)"
        if len(offenders) > 5
        else ""
    )
    return [
        Finding(
            rule_id="pg.health.bloat_high",
            severity="warning",
            title=(
                f"{len(offenders)} table(s) with significant "
                "bloat"
            ),
            detail=(
                "Bloat wastes disk and slows scans. "
                f"Top offenders: {examples}{suffix}. Consider "
                "VACUUM (FULL) during a maintenance window, "
                "or pg_repack for online rewrite. Tune "
                "autovacuum_vacuum_scale_factor for the table "
                "if this recurs."
            ),
        )
    ]


@register("Internals & I/O Health")
def archiver_failing(parsed: dict[str, Any]) -> list[Finding]:
    """Warn when the WAL archiver reports failures."""
    a: PgArchiver | None = parsed.get("pg.archiver")
    if a is None or not a.has_recent_failure:
        return []
    return [
        Finding(
            rule_id="pg.wal.archiver_failures",
            severity="critical",
            title="WAL archiver has recent failures",
            detail=(
                f"failed_count = {a.failed_count}; "
                f"last_failed_time = {a.last_failed_time}; "
                f"last_archived_time = "
                f"{a.last_archived_time or '(never)'}. WAL will "
                "accumulate on pg_wal/ until archiving succeeds; "
                "if pg_wal fills the filesystem, the instance "
                "stops. Check archive_command + destination "
                "reachability."
            ),
        )
    ]
