"""Assessment orchestrator.

Given a downloaded radar zip, this walks the archive, parses the
file kinds that have parsers, builds a system context plus
per-category "facts" blocks, runs the deterministic rules, and
fires one LLM call per category (plus one per qualifying
database). Each stage emits progress events and updates the job
row so the console can track progress in real time.

A category whose sources are absent from the archive is persisted
as UNKNOWN instead of being skipped, so an assessment always
carries every category.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from radar_analyst.ai.base import AIError, Analyzer, Request
from radar_analyst.ai.prompts import (
    SystemContext,
    render_db_user_prompt,
    render_system_prompt,
    render_user_prompt,
)
from radar_analyst.analyze.categories import CATEGORIES, Category
from radar_analyst.analyze.facts import (
    build_category_facts,
    build_db_facts,
    build_system_context,
)
from radar_analyst.analyze.parsing import read_and_parse
from radar_analyst.parse.databases import (
    DatabaseBlkStats,
    DatabaseChecksums,
    DatabaseConflictStats,
    DatabaseInfo,
    DatabaseTupleStats,
    DbStatDatabase,
)
from radar_analyst.parse.pg_activity import (
    PgActivity,
)
from radar_analyst.rules import (
    apply_finding_floor,
    rank_to_verdict,
    run_for_category,
    severity_rank,
)
from radar_analyst.rules.pg_db import run_per_db_rules
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.briefs import insert_brief
from radar_analyst.store.jobs import update_job_state
from radar_analyst.store.snapshots import upsert_snapshot
from radar_analyst.store.uploads import set_archive_files


_logger = logging.getLogger(__name__)


_UNKNOWN_MARKDOWN = (
    "No data for this category in this archive. The verdict "
    "stays UNKNOWN rather than guessing from absent evidence."
)

_NO_DB_ISSUES_MARKDOWN = (
    "**[HEALTHY]**\n\n"
    "No issues observed for this database."
)


# Metric keys the per-db inline rules consume.
_RULE_INPUT_KEYS = (
    "cache_hit_ratio",
    "blks_read",
    "blks_hit",
    "deadlocks",
    "temp_files",
    "temp_bytes",
    "confl_lock",
    "confl_deadlock",
)

# Sort order for the summary list: worst first, then stable by
# name across runs. Severity comes from rank_to_verdict, so only
# these three values occur.
_SEVERITY_SORT = {"CRITICAL": 0, "WARNING": 1, "HEALTHY": 2}


def _checksum_finding(cs: DatabaseChecksums) -> dict[str, str]:
    """The critical finding for data-page checksum failures."""
    return {
        "rule_id": "pg.db.checksum_failures",
        "severity": "critical",
        "title": (
            f"{cs.checksum_failures} data-page "
            "checksum failure(s)"
        ),
        "detail": (
            "Checksum mismatches indicate "
            "storage-level corruption (disk, "
            "controller, filesystem). Last failure "
            f"at {cs.checksum_last_failure or 'unknown'}. "
            "Take a backup immediately, identify the "
            "affected relations with pg_checksum tools "
            "or log scraping, and escalate hardware "
            "investigation."
        ),
    }


def _db_schema_counts(
    parsed: dict[str, Any], name: str
) -> dict[str, Any]:
    """Schema-object counts for one database.

    A count is None when radar didn't ship the file for that
    database. Most kinds arrive as ``{dbname: int}``;
    ``pg.db.tables`` / ``pg.db.indexes`` /
    ``pg.db.subscription_tables`` carry full row sets, so their
    counts come from ``len()``.
    """
    def _len_of(kind: str) -> int | None:
        per_db: dict[str, Any] = parsed.get(kind) or {}
        return len(per_db[name]) if name in per_db else None

    def _count(kind: str) -> int | None:
        per_db: dict[str, int] = parsed.get(kind) or {}
        return per_db.get(name)

    extensions: dict[str, list[str]] = (
        parsed.get("pg.db.extensions") or {}
    )
    return {
        "table_count": _len_of("pg.db.tables"),
        "index_count": _len_of("pg.db.indexes"),
        "partitioned_tables_count": _count(
            "pg.db.partitioned_tables"
        ),
        "partitions_count": _count("pg.db.partitions"),
        "publication_count": _count("pg.db.publications"),
        "subscription_count": _len_of(
            "pg.db.subscription_tables"
        ),
        "trigger_count": _count("pg.db.triggers"),
        "function_count": _count("pg.db.funcs"),
        "procedure_count": _count("pg.db.procs"),
        "type_count": _count("pg.db.types"),
        "extensions": extensions.get(name) or [],
    }


def _db_metrics(
    parsed: dict[str, Any], name: str
) -> dict[str, Any]:
    """Activity and workload counters for one database."""
    bs: DatabaseBlkStats | None = (
        parsed.get("pg.databases_blk") or {}
    ).get(name)
    ts: DatabaseTupleStats | None = (
        parsed.get("pg.databases_tup") or {}
    ).get(name)
    sd: DbStatDatabase | None = (
        parsed.get("pg.db.stat_database") or {}
    ).get(name)
    cx: DatabaseConflictStats | None = (
        parsed.get("pg.database_conflicts") or {}
    ).get(name)
    total_blocks = (bs.blks_hit + bs.blks_read) if bs else 0
    cache_hit_ratio = (
        bs.blks_hit / total_blocks
        if bs is not None and total_blocks > 0
        else None
    )
    return {
        "cache_hit_ratio": cache_hit_ratio,
        "blks_read": bs.blks_read if bs else 0,
        "blks_hit": bs.blks_hit if bs else 0,
        "deadlocks": sd.deadlocks if sd else 0,
        "temp_files": sd.temp_files if sd else 0,
        "temp_bytes": sd.temp_bytes if sd else 0,
        "confl_lock": cx.confl_lock if cx else 0,
        "confl_deadlock": cx.confl_deadlock if cx else 0,
        # Workload shape, for LLM context; not rule-gated.
        "tup_returned": ts.tup_returned if ts else 0,
        "tup_fetched": ts.tup_fetched if ts else 0,
        "tup_inserted": ts.tup_inserted if ts else 0,
        "tup_updated": ts.tup_updated if ts else 0,
        "tup_deleted": ts.tup_deleted if ts else 0,
    }


def _summarize_db(
    db: DatabaseInfo,
    parsed: dict[str, Any],
    sessions: dict[str, int],
) -> dict[str, Any]:
    """The snapshot summary row for one database."""
    name = db.datname
    findings: list[dict[str, str]] = []
    cs: DatabaseChecksums | None = (
        parsed.get("pg.databases_checksums") or {}
    ).get(name)
    if cs is not None and cs.checksum_failures > 0:
        findings.append(_checksum_finding(cs))
    metrics = _db_metrics(parsed, name)
    rule_input: dict[str, Any] = {"datname": name}
    rule_input.update(
        {k: metrics[k] for k in _RULE_INPUT_KEYS}
    )
    findings.extend(run_per_db_rules(rule_input))
    severity = rank_to_verdict(
        max(
            (severity_rank(f["severity"]) for f in findings),
            default=0,
        )
    )
    sizes: dict[str, str] = (
        parsed.get("pg.database_sizes") or {}
    )
    row: dict[str, Any] = {
        "datname": name,
        "size": sizes.get(name, ""),
    }
    row.update(_db_schema_counts(parsed, name))
    row["active_sessions"] = sessions.get(name, 0)
    row.update(metrics)
    row["checksum_failures"] = (
        cs.checksum_failures if cs else 0
    )
    row["findings"] = findings
    row["severity"] = severity
    return row


def _build_database_summaries(
    parsed: dict[str, Any],
) -> list[dict[str, Any]]:
    """One summary dict per user-accessible database.

    Aggregates: size, schema counts, extensions, per-db activity
    (sessions, cache-hit ratio, deadlocks, temp files, recovery
    conflicts, tuple traffic), and per-db rule findings. Template
    databases are filtered out via ``datistemplate``.
    """
    dbs: list[DatabaseInfo] = parsed.get("pg.databases") or []
    if not dbs:
        return []
    activity: PgActivity | None = parsed.get(
        "pg.running_activity"
    )
    sessions = activity.by_database if activity else {}
    out = [
        _summarize_db(db, parsed, sessions)
        for db in dbs
        if not db.datistemplate
    ]
    out.sort(
        key=lambda d: (
            _SEVERITY_SORT.get(d["severity"], 3),
            d["datname"],
        )
    )
    return out


async def _analyze_db(
    db: dict[str, Any],
    analyzer: Analyzer,
    system_prompt: str,
) -> tuple[str, str | None]:
    """Run the conditional per-db LLM analysis for *db*.

    Returns *(markdown, verdict)*. The LLM is invoked only when
    at least one rule finding fired. Databases with no findings get
    the static "no issues observed" card: no LLM tokens burned.
    """
    findings: list[dict[str, str]] = db.get("findings") or []

    if not findings:
        return _NO_DB_ISSUES_MARKDOWN, "HEALTHY"

    facts = build_db_facts(db)
    user_prompt = render_db_user_prompt(
        db_name=db["datname"],
        findings=findings,
        facts=facts,
    )
    try:
        result = await analyzer.analyze(
            Request(
                category=f"Database: {db['datname']}",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                cache_static=True,
            )
        )
        markdown = result.markdown
        verdict = result.verdict
    except AIError as e:
        _logger.error(
            "AI failed for database %s: %s", db["datname"], e
        )
        markdown = (
            f"Brief unavailable for this database: {e}"
        )
        verdict = None

    # Severity floor: the verdict can never be below the worst
    # finding, and a database always carries one even when the
    # provider never answered.
    verdict = apply_finding_floor(
        verdict, (f["severity"] for f in findings)
    )

    return markdown, verdict


def _build_snapshot(
    parsed: dict[str, Any],
    ctx: SystemContext,
    parsed_kinds: list[str],
    unknown: list[str],
) -> dict[str, Any]:
    """The persisted snapshot document for one upload."""
    meta = parsed.get("radar.meta")
    return {
        "hostname": ctx.hostname,
        "os": ctx.os,
        "kernel": ctx.kernel,
        "cpu_count": ctx.cpu_count,
        "cpu_model": (
            parsed.get("sys.lscpu", {}).get("Model name")
            or ""
        ),
        "total_ram": ctx.total_ram,
        "host_uptime": ctx.host_uptime,
        "pg_started": ctx.pg_started,
        "is_container": ctx.is_container,
        "hypervisor": ctx.hypervisor,
        "runtime": ctx.runtime,
        "cloud_provider": ctx.cloud_provider,
        "k8s_namespace": parsed.get(
            "sys.container.k8s_namespace"
        )
        or "",
        "pg_version": ctx.pg_version,
        "radar_version": (
            meta.version if meta is not None else None
        ),
        "radar_commit": (
            meta.commit if meta is not None else None
        ),
        "databases": _build_database_summaries(parsed),
        "parsed_kinds": parsed_kinds,
        "unknown_entries": unknown,
    }


async def _analyze_category(
    cat: Category,
    parsed: dict[str, Any],
    system_prompt: str,
    analyzer: Analyzer,
) -> tuple[str, str | None, int | None, int | None]:
    """One category's brief: markdown, verdict, token counts.

    A category with no facts short-circuits to UNKNOWN without an
    LLM call, because "not collected" is more honest than asking
    the model to assess nothing. An AIError leaves the brief
    missing while the finding floor still decides the verdict.
    """
    facts = build_category_facts(cat, parsed)
    findings = run_for_category(cat.name, parsed)
    if facts is None:
        return _UNKNOWN_MARKDOWN, "UNKNOWN", None, None
    finding_dicts = [
        {
            "severity": f.severity,
            "rule_id": f.rule_id,
            "title": f.title,
            "detail": f.detail,
        }
        for f in findings
    ]
    user_prompt = render_user_prompt(
        category=cat.name,
        findings=finding_dicts,
        facts=facts,
    )
    verdict: str | None
    ptokens: int | None
    ctokens: int | None
    try:
        result = await analyzer.analyze(
            Request(
                category=cat.name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                cache_static=True,
            )
        )
        markdown = result.markdown
        verdict = result.verdict
        ptokens = result.prompt_tokens
        ctokens = result.completion_tokens
    except AIError as e:
        _logger.error("AI failed for %s: %s", cat.name, e)
        markdown = (
            f"Brief unavailable for this category: {e}"
        )
        verdict = None
        ptokens = None
        ctokens = None
    # Severity floor: the final verdict can never be below the
    # max finding severity. LLMs can ignore calibration prompts;
    # this is the deterministic guard rail. It also carries the
    # category through an LLM outage: findings alone decide the
    # verdict.
    verdict = apply_finding_floor(
        verdict, (f.severity for f in findings)
    )
    return markdown, verdict, ptokens, ctokens


async def _analyze_databases(
    *,
    databases: list[dict[str, Any]],
    snapshot: dict[str, Any],
    upload_id: UUID,
    job_id: UUID,
    pool: AsyncConnectionPool,
    analyzer: Analyzer,
    hub: SSEHub,
    system_prompt: str,
) -> None:
    """Per-database briefs, written back into *snapshot*."""
    await update_job_state(
        pool,
        job_id,
        state="analyzing",
        phase="per-db analysis",
    )
    hub.publish(
        job_id,
        {"type": "phase", "phase": "analyzing databases"},
    )
    db_results = list(
        await asyncio.gather(
            *[
                _analyze_db(db, analyzer, system_prompt)
                for db in databases
            ]
        )
    )
    for db, (md, tag) in zip(databases, db_results, strict=True):
        db["brief_markdown"] = md
        db["brief_verdict"] = tag
    # Persist snapshot with per-db analysis fields added.
    await upsert_snapshot(
        pool, upload_id=upload_id, data=snapshot
    )


async def _enter_phase(
    pool: AsyncConnectionPool,
    job_id: UUID,
    hub: SSEHub,
    *,
    state: str,
    phase: str,
    event: str,
) -> None:
    """Persist a job state transition and publish its event."""
    await update_job_state(
        pool, job_id, state=state, phase=phase
    )
    hub.publish(job_id, {"type": "phase", "phase": event})


async def _fail_job(
    pool: AsyncConnectionPool,
    job_id: UUID,
    hub: SSEHub,
    error: Exception,
) -> None:
    """Persist a job failure and publish the error event."""
    _logger.exception(
        "orchestrator failed for job %s", job_id
    )
    await update_job_state(
        pool, job_id, state="failed", error=str(error)
    )
    hub.publish(
        job_id, {"type": "error", "message": str(error)}
    )


async def _analyze_categories(
    *,
    parsed: dict[str, Any],
    system_prompt: str,
    upload_id: UUID,
    job_id: UUID,
    pool: AsyncConnectionPool,
    analyzer: Analyzer,
    hub: SSEHub,
) -> None:
    """One brief per category: analyze, persist, publish."""
    for idx, cat in enumerate(CATEGORIES):
        hub.publish(
            job_id,
            {
                "type": "phase",
                "phase": (
                    f"analyzing {cat.name} "
                    f"({idx + 1}/{len(CATEGORIES)})"
                ),
            },
        )
        (
            markdown,
            verdict,
            ptokens,
            ctokens,
        ) = await _analyze_category(
            cat, parsed, system_prompt, analyzer
        )
        await insert_brief(
            pool,
            brief_id=uuid4(),
            upload_id=upload_id,
            category=cat.name,
            provider=analyzer.name,
            model=analyzer.model,
            verdict=verdict,
            markdown=markdown,
            prompt_tokens=ptokens,
            completion_tokens=ctokens,
        )
        hub.publish(
            job_id,
            {
                "type": "brief",
                "category": cat.name,
                "verdict": verdict,
            },
        )


async def orchestrate(
    *,
    upload_id: UUID,
    job_id: UUID,
    zip_path: Path,
    pool: AsyncConnectionPool,
    analyzer: Analyzer,
    hub: SSEHub,
) -> None:
    """Run the full analysis pipeline for a single upload.

    Emits progress events and persists job state / snapshot /
    briefs as it goes. Catches exceptions, marks the job
    ``failed``, and publishes an ``error`` event before
    re-raising (so the background task hook in the caller can log
    it as a task failure too).
    """
    try:
        await _enter_phase(
            pool,
            job_id,
            hub,
            state="parsing",
            phase="reading archive",
            event="parsing",
        )
        (
            parsed,
            unknown,
            parsed_kinds,
            present,
            inventory,
        ) = read_and_parse(zip_path)
        await set_archive_files(pool, upload_id, inventory)

        ctx = build_system_context(parsed, present)
        snapshot = _build_snapshot(
            parsed, ctx, parsed_kinds, unknown
        )
        await upsert_snapshot(
            pool, upload_id=upload_id, data=snapshot
        )

        await _enter_phase(
            pool,
            job_id,
            hub,
            state="analyzing",
            phase="calling LLM per category",
            event="analyzing",
        )

        system_prompt = render_system_prompt(ctx)
        await _analyze_categories(
            parsed=parsed,
            system_prompt=system_prompt,
            upload_id=upload_id,
            job_id=job_id,
            pool=pool,
            analyzer=analyzer,
            hub=hub,
        )

        # Per-database conditional LLM analysis.
        databases: list[dict[str, Any]] = (
            snapshot.get("databases") or []
        )
        if databases:
            await _analyze_databases(
                databases=databases,
                snapshot=snapshot,
                upload_id=upload_id,
                job_id=job_id,
                pool=pool,
                analyzer=analyzer,
                hub=hub,
                system_prompt=system_prompt,
            )

        await update_job_state(
            pool,
            job_id,
            state="done",
            phase="complete",
        )
        hub.publish(job_id, {"type": "done"})
    except Exception as e:
        await _fail_job(pool, job_id, hub, e)
        raise
