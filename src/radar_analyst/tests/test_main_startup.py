"""What the entrypoint does at startup.

An assessment that was running when the analyst stopped cannot be
resumed: the task that ran it went with the process. Left as it is,
its job would read as running forever, so startup marks every such
job failed and the console offers to assess the upload again.

Startup also logs where it connects, without the password that the
database URL holds.
"""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import AsyncConnectionPool

import radar_analyst.main as main_mod
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.jobs import get_job, insert_job
from radar_analyst.store.uploads import insert_upload


def _production_env(
    monkeypatch: pytest.MonkeyPatch, dsn: str, data_dir: Path
) -> None:
    """Configure the entrypoint as a deployment would, with the mock."""
    monkeypatch.setenv("RADAR_ANALYST_STATE_DB_URL", dsn)
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(data_dir))
    monkeypatch.setenv("RADAR_ANALYST_TEST", "1")
    monkeypatch.setenv("RADAR_ANALYST_AI_PROVIDER", "mock")
    monkeypatch.delenv("RADAR_ANALYST_ADMIN_TOKEN", raising=False)


async def test_jobs_left_unfinished_by_the_previous_run_are_failed(
    fresh_pool: AsyncConnectionPool,
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await apply_migrations(fresh_pool)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="radar-db01-20260401-120000.zip",
        storage_url=f"file:///tmp/{upload_id}.zip",
        size_bytes=1024,
        sha256="e" * 64,
        hostname="db01",
        archive_timestamp=None,
    )
    job_id = uuid4()
    await insert_job(
        fresh_pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="mock",
        state="analyzing",
    )
    _production_env(monkeypatch, postgres_dsn, tmp_path)

    app = main_mod.build_production_app()
    with TestClient(app):
        pass

    job = await get_job(fresh_pool, job_id)
    assert job is not None
    assert job.state == "failed"
    assert job.error == main_mod.INTERRUPTED_ERROR
    assert job.finished_at is not None


async def test_the_startup_log_names_the_database_without_its_password(
    fresh_pool: AsyncConnectionPool,
    postgres_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _production_env(monkeypatch, postgres_dsn, tmp_path)
    info = conninfo_to_dict(postgres_dsn)

    app = main_mod.build_production_app()
    with caplog.at_level(logging.INFO), TestClient(app):
        pass

    assert postgres_dsn not in caplog.text
    connecting = [
        r.getMessage()
        for r in caplog.records
        if r.getMessage().startswith("connecting to")
    ]
    assert connecting == [f"connecting to {info['host']}:{info['port']}"]
