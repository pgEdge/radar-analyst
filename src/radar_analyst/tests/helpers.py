"""Shared helpers for route-level tests."""

from pathlib import Path

from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

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
