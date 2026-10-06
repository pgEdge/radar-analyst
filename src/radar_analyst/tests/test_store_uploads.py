"""Tests for upload row CRUD."""

from datetime import datetime
from typing import Any
from uuid import uuid4

from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.briefs import insert_brief
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.jobs import insert_job, update_job_state
from radar_analyst.store.snapshots import upsert_snapshot
from radar_analyst.store.uploads import (
    get_archive_files,
    get_upload,
    insert_upload,
    list_uploads,
    set_archive_files,
    set_upload_hostname,
)


async def test_insert_and_get_upload(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="radar-host-20260401-120000.zip",
        storage_url="file:///tmp/x.zip",
        size_bytes=12345,
        sha256="deadbeef" * 8,
        hostname="host",
        archive_timestamp=None,
    )
    row = await get_upload(fresh_pool, upload_id)
    assert row is not None
    assert row.id == upload_id
    assert row.filename == "radar-host-20260401-120000.zip"
    assert row.size_bytes == 12345
    assert row.hostname == "host"


async def test_get_missing_upload_returns_none(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    row = await get_upload(fresh_pool, uuid4())
    assert row is None


async def test_set_and_get_archive_files(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    files: list[dict[str, Any]] = [
        {
            "path": "postgresql/configuration.tsv",
            "kind": "pg.settings",
            "dbname": None,
            "size": 12345,
        },
        {
            "path": "databases/foo/extensions.tsv",
            "kind": "pg.db.extensions",
            "dbname": "foo",
            "size": 67,
        },
        {
            "path": "weird/unknown.txt",
            "kind": None,
            "dbname": None,
            "size": 5,
        },
    ]
    await set_archive_files(fresh_pool, upload_id, files)
    out = await get_archive_files(fresh_pool, upload_id)
    assert out == files


async def test_archive_files_unset_for_new_upload(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    out = await get_archive_files(fresh_pool, upload_id)
    assert out is None


async def test_archive_files_returns_none_for_missing_upload(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    out = await get_archive_files(fresh_pool, uuid4())
    assert out is None


async def test_set_upload_hostname_keeps_the_collection_time(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    when = datetime(2026, 9, 3, 16, 44, 50)
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname="from-the-name",
        archive_timestamp=when,
    )
    await set_upload_hostname(fresh_pool, upload_id, "db1")
    row = await get_upload(fresh_pool, upload_id)
    assert row is not None
    assert row.hostname == "db1"
    assert row.archive_timestamp == when


async def test_an_upload_carries_why_its_latest_job_failed(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname="db1",
        archive_timestamp=None,
    )
    job_id = uuid4()
    await insert_job(
        fresh_pool, job_id=job_id, upload_id=upload_id, ai_provider="mock"
    )
    await update_job_state(
        fresh_pool, job_id, state="failed", error="File is not a zip file"
    )

    row = await get_upload(fresh_pool, upload_id)

    assert row is not None
    assert row.job_state == "failed"
    assert row.job_error == "File is not a zip file"


async def test_list_uploads_carries_job_state_and_verdicts(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname="db1",
        archive_timestamp=None,
    )
    job_id = uuid4()
    await insert_job(
        fresh_pool, job_id=job_id, upload_id=upload_id, ai_provider="mock"
    )
    await update_job_state(fresh_pool, job_id, state="done")
    for category, verdict in (
        ("Host & OS", "HEALTHY"),
        ("PostgreSQL Configuration", "WARNING"),
        ("Replication", None),
    ):
        await insert_brief(
            fresh_pool,
            brief_id=uuid4(),
            upload_id=upload_id,
            category=category,
            provider="mock",
            model="mock-v0",
            verdict=verdict,
            markdown="x",
            prompt_tokens=None,
            completion_tokens=None,
        )

    rows = await list_uploads(fresh_pool)

    assert len(rows) == 1
    assert rows[0].id == upload_id
    assert rows[0].job_state == "done"
    assert sorted(v or "" for v in rows[0].verdicts) == [
        "",
        "HEALTHY",
        "WARNING",
    ]


async def test_list_uploads_carries_the_assessed_database_verdicts(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname="db1",
        archive_timestamp=None,
    )
    await insert_brief(
        fresh_pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Host & OS",
        provider="mock",
        model="mock-v0",
        verdict="WARNING",
        markdown="x",
        prompt_tokens=None,
        completion_tokens=None,
    )
    await upsert_snapshot(
        fresh_pool,
        upload_id=upload_id,
        data={
            "databases": [
                {"datname": "app", "brief_verdict": "CRITICAL"},
                {"datname": "reports", "brief_verdict": "HEALTHY"},
                {"datname": "pending", "severity": "CRITICAL"},
            ]
        },
    )

    rows = await list_uploads(fresh_pool)

    assert sorted(v or "" for v in rows[0].verdicts) == [
        "CRITICAL",
        "HEALTHY",
        "WARNING",
    ]


async def test_list_uploads_without_a_job_or_briefs(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )

    rows = await list_uploads(fresh_pool)

    assert rows[0].job_state is None
    assert rows[0].verdicts == []
