"""Tests for upload row CRUD."""

from typing import Any
from uuid import uuid4

from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.db import apply_migrations
from radar_analyst.store.uploads import (
    get_archive_files,
    get_upload,
    insert_upload,
    set_archive_files,
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
