"""CRUD helpers for the ``radar.briefs`` table."""

from __future__ import annotations

from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from radar_analyst.model import Brief
from radar_analyst.store.db import execute, fetch_all


async def insert_brief(
    pool: AsyncConnectionPool,
    *,
    brief_id: UUID,
    upload_id: UUID,
    category: str,
    provider: str,
    model: str,
    verdict: str | None,
    markdown: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> None:
    """Insert one brief row for an upload's category."""
    await execute(
        pool,
        "INSERT INTO radar.briefs "
        "(id, upload_id, category, provider, model, "
        " verdict, markdown, prompt_tokens, "
        " completion_tokens) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            brief_id,
            upload_id,
            category,
            provider,
            model,
            verdict,
            markdown,
            prompt_tokens,
            completion_tokens,
        ),
    )


async def list_briefs(
    pool: AsyncConnectionPool, upload_id: UUID
) -> list[Brief]:
    """Return every brief for *upload_id*, ordered by category."""
    return await fetch_all(
        pool,
        "SELECT id, upload_id, category, provider, "
        "       model, verdict, markdown, "
        "       prompt_tokens, completion_tokens, "
        "       created_at "
        "FROM radar.briefs "
        "WHERE upload_id = %s "
        "ORDER BY category",
        (upload_id,),
        row_factory=class_row(Brief),
    )


async def delete_briefs(
    pool: AsyncConnectionPool, upload_id: UUID
) -> int:
    """Delete every brief of *upload_id*; returns the row count."""
    return await execute(
        pool,
        "DELETE FROM radar.briefs WHERE upload_id = %s",
        (upload_id,),
    )
