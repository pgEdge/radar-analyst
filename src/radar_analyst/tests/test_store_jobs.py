"""Tests for job row CRUD."""

from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import apply_migrations
from radar_analyst.store.jobs import (
    fail_interrupted_jobs,
    get_job,
    insert_job,
    update_job_state,
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


async def test_insert_and_get_job(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    job_id = uuid4()
    await insert_job(
        fresh_pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="claude",
    )
    row = await get_job(fresh_pool, job_id)
    assert row is not None
    assert row.id == job_id
    assert row.upload_id == upload_id
    assert row.state == "queued"
    assert row.ai_provider == "claude"


async def test_update_job_state_transitions(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    job_id = uuid4()
    await insert_job(
        fresh_pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="claude",
    )
    await update_job_state(
        fresh_pool, job_id, state="parsing", phase="reading zip"
    )
    row = await get_job(fresh_pool, job_id)
    assert row is not None
    assert row.state == "parsing"
    assert row.phase == "reading zip"


async def test_update_job_state_with_error(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    job_id = uuid4()
    await insert_job(
        fresh_pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="claude",
    )
    await update_job_state(
        fresh_pool, job_id, state="failed", error="boom"
    )
    row = await get_job(fresh_pool, job_id)
    assert row is not None
    assert row.state == "failed"
    assert row.error == "boom"


async def test_fail_interrupted_jobs_marks_every_unfinished_job(
    fresh_pool: AsyncConnectionPool,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = await _seed_upload(fresh_pool)
    states = ("queued", "parsing", "analyzing", "done", "failed")
    jobs = {state: uuid4() for state in states}
    for state, job_id in jobs.items():
        await insert_job(
            fresh_pool,
            job_id=job_id,
            upload_id=upload_id,
            ai_provider="claude",
            state=state,
        )
    await update_job_state(
        fresh_pool, jobs["failed"], state="failed", error="boom"
    )

    count = await fail_interrupted_jobs(fresh_pool, error="stopped")

    assert count == 3
    for state in ("queued", "parsing", "analyzing"):
        row = await get_job(fresh_pool, jobs[state])
        assert row is not None
        assert row.state == "failed"
        assert row.error == "stopped"
        assert row.finished_at is not None
    done = await get_job(fresh_pool, jobs["done"])
    assert done is not None
    assert done.state == "done"
    assert done.error is None
    failed = await get_job(fresh_pool, jobs["failed"])
    assert failed is not None
    assert failed.error == "boom"
