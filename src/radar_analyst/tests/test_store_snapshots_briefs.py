"""Tests for snapshots + briefs CRUD."""

from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.briefs import (
    insert_brief,
    list_briefs,
)
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.snapshots import (
    get_snapshot,
    upsert_snapshot,
)
from radar_analyst.store.uploads import insert_upload


async def _seed_upload(pool: AsyncConnectionPool) -> UUID:
    upload_id = uuid4()
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename="x.zip",
        storage_url="file:///tmp/x.zip",
        size_bytes=1,
        sha256="a" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    return upload_id


async def test_upsert_and_get_snapshot(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    data = {
        "hostname": "db01",
        "os": "Ubuntu 24.04",
        "pg_version": "PostgreSQL 17.2",
        "unknown_entries": [],
    }
    await upsert_snapshot(
        fresh_pool, upload_id=upload_id, data=data
    )
    got = await get_snapshot(fresh_pool, upload_id)
    assert got == data


async def test_upsert_snapshot_replaces_existing(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    await upsert_snapshot(
        fresh_pool, upload_id=upload_id, data={"v": 1}
    )
    await upsert_snapshot(
        fresh_pool, upload_id=upload_id, data={"v": 2}
    )
    got = await get_snapshot(fresh_pool, upload_id)
    assert got == {"v": 2}


async def test_insert_and_list_briefs(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    await insert_brief(
        fresh_pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Host & OS",
        provider="mock",
        model="mock-v0",
        verdict="HEALTHY",
        markdown="**[HEALTHY]**\nall good",
        prompt_tokens=100,
        completion_tokens=20,
    )
    await insert_brief(
        fresh_pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Replication",
        provider="mock",
        model="mock-v0",
        verdict="HEALTHY",
        markdown="no replication configured",
        prompt_tokens=50,
        completion_tokens=10,
    )
    rows = await list_briefs(fresh_pool, upload_id)
    assert len(rows) == 2
    categories = {r.category for r in rows}
    assert categories == {"Host & OS", "Replication"}
