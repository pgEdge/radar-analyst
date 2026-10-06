"""Shared helpers for the tests."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from radar_analyst.analyze.runner import JobRunner
from radar_analyst.blob.localfs import LocalFsStore
from radar_analyst.server.app import create_app
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.db import apply_migrations


async def build_app(
    pool: AsyncConnectionPool,
    tmp_path: Path,
    *,
    max_upload_bytes: int = 100 * 1024 * 1024,
    admin_token: str | None = None,
    sse_hub: SSEHub | None = None,
) -> tuple[FastAPI, LocalFsStore]:
    """A migrated app plus its localfs store, for route tests."""
    await apply_migrations(pool)
    store = LocalFsStore(data_dir=tmp_path)
    app = create_app(
        pool=pool,
        blob_store=store,
        max_upload_bytes=max_upload_bytes,
        admin_token=admin_token,
        sse_hub=sse_hub,
    )
    return app, store


async def finish_job(runner: JobRunner, job_id: UUID) -> None:
    """Wait for the analysis task of *job_id* to finish."""
    task = runner.task_for(job_id)
    if task is None:
        return
    # A failure is persisted to the job, which the test reads.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(task, timeout=10.0)


@contextlib.asynccontextmanager
async def silent_server() -> AsyncGenerator[int, None]:
    """Yield the port of a local server that never answers a request."""

    async def silent(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.read()

    server = await asyncio.start_server(silent, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
