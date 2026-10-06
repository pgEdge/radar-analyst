"""Tests for findings row CRUD."""

from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from radar_analyst.rules.base import Finding
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.findings import (
    delete_findings,
    insert_findings,
    list_findings,
)
from radar_analyst.store.uploads import delete_upload, insert_upload


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


def _finding(rule_id: str, severity: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        severity=severity,
        title=f"{rule_id} fired",
        detail="what to do about it",
    )


async def test_insert_and_list_findings(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    await insert_findings(
        fresh_pool,
        upload_id=upload_id,
        category="PostgreSQL Configuration",
        findings=[
            _finding("pg.config.b", "info"),
            _finding("pg.config.a", "critical"),
        ],
    )
    await insert_findings(
        fresh_pool,
        upload_id=upload_id,
        category="Host & OS",
        findings=[_finding("host.swap", "warning")],
    )

    rows = await list_findings(fresh_pool, upload_id)

    # Ordered by category, then worst severity first.
    assert [(r.category, r.rule_id) for r in rows] == [
        ("Host & OS", "host.swap"),
        ("PostgreSQL Configuration", "pg.config.a"),
        ("PostgreSQL Configuration", "pg.config.b"),
    ]
    first = rows[0]
    assert first.upload_id == upload_id
    assert first.severity == "warning"
    assert first.title == "host.swap fired"
    assert first.detail == "what to do about it"


async def test_inserting_no_findings_writes_nothing(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)

    await insert_findings(
        fresh_pool,
        upload_id=upload_id,
        category="Host & OS",
        findings=[],
    )

    assert await list_findings(fresh_pool, upload_id) == []


async def test_delete_findings_removes_only_that_uploads_rows(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    kept = await _seed_upload(fresh_pool)
    cleared = await _seed_upload(fresh_pool)
    for upload_id in (kept, cleared):
        await insert_findings(
            fresh_pool,
            upload_id=upload_id,
            category="Host & OS",
            findings=[_finding("host.swap", "warning")],
        )

    await delete_findings(fresh_pool, cleared)

    assert await list_findings(fresh_pool, cleared) == []
    assert len(await list_findings(fresh_pool, kept)) == 1


async def test_findings_go_with_their_upload(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    await insert_findings(
        fresh_pool,
        upload_id=upload_id,
        category="Host & OS",
        findings=[_finding("host.swap", "warning")],
    )

    await delete_upload(fresh_pool, upload_id)

    assert await list_findings(fresh_pool, upload_id) == []
