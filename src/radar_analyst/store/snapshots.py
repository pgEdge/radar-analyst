"""CRUD helpers for the ``radar.snapshots`` table.

One snapshot per upload, with upsert semantics so an orchestrator
re-run for the same upload replaces the earlier snapshot.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import execute, fetch_scalar


async def upsert_snapshot(
    pool: AsyncConnectionPool,
    *,
    upload_id: UUID,
    data: dict[str, Any],
) -> None:
    """Insert or replace the snapshot for *upload_id*."""
    await execute(
        pool,
        "INSERT INTO radar.snapshots (upload_id, data) "
        "VALUES (%s, %s) "
        "ON CONFLICT (upload_id) DO UPDATE "
        "SET data = EXCLUDED.data",
        (upload_id, Jsonb(data)),
    )


async def get_snapshot(
    pool: AsyncConnectionPool, upload_id: UUID
) -> dict[str, Any] | None:
    """Return the snapshot dict for *upload_id*, or None."""
    data = await fetch_scalar(
        pool,
        "SELECT data FROM radar.snapshots WHERE upload_id = %s",
        (upload_id,),
    )
    if data is None:
        return None
    # psycopg v3 returns JSONB as a Python dict already.
    assert isinstance(data, dict)
    return data
