"""CRUD helpers for the ``radar.findings`` table."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID, uuid4

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from radar_analyst.model import FindingRow
from radar_analyst.rules.base import Finding
from radar_analyst.store.db import execute, fetch_all


async def insert_findings(
    pool: AsyncConnectionPool,
    *,
    upload_id: UUID,
    category: str,
    findings: Iterable[Finding],
) -> None:
    """Insert one category's findings for *upload_id*."""
    rows = [
        (
            uuid4(),
            upload_id,
            f.rule_id,
            category,
            f.severity,
            f.title,
            f.detail,
        )
        for f in findings
    ]
    if not rows:
        return
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.executemany(
            "INSERT INTO radar.findings "
            "(id, upload_id, rule_id, category, severity, "
            " title, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            rows,
        )


async def list_findings(
    pool: AsyncConnectionPool, upload_id: UUID
) -> list[FindingRow]:
    """Return every finding for *upload_id*.

    Ordered by category, then worst severity first, so a caller
    grouping by category gets each group ready to display.
    """
    return await fetch_all(
        pool,
        "SELECT id, upload_id, rule_id, category, severity, "
        "       title, detail "
        "FROM radar.findings "
        "WHERE upload_id = %s "
        "ORDER BY category, "
        "         CASE severity "
        "           WHEN 'critical' THEN 0 "
        "           WHEN 'warning' THEN 1 "
        "           WHEN 'info' THEN 2 "
        "           ELSE 3 END, "
        "         title",
        (upload_id,),
        row_factory=class_row(FindingRow),
    )


async def delete_findings(
    pool: AsyncConnectionPool, upload_id: UUID
) -> int:
    """Delete every finding of *upload_id*; returns the row count."""
    return await execute(
        pool,
        "DELETE FROM radar.findings WHERE upload_id = %s",
        (upload_id,),
    )
