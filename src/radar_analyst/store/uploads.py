"""CRUD helpers for the ``radar.uploads`` table."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from radar_analyst.model import Upload
from radar_analyst.store.db import (
    execute,
    fetch_all,
    fetch_one,
    fetch_scalar,
)

_UPLOAD_COLUMNS = (
    "id, filename, storage_url, size_bytes, sha256, hostname, "
    "archive_timestamp, created_at"
)


async def insert_upload(
    pool: AsyncConnectionPool,
    *,
    upload_id: UUID,
    filename: str,
    storage_url: str,
    size_bytes: int,
    sha256: str,
    hostname: str | None,
    archive_timestamp: datetime | None,
) -> None:
    """Insert one upload row keyed by *upload_id*."""
    await execute(
        pool,
        "INSERT INTO radar.uploads "
        "(id, filename, storage_url, size_bytes, sha256, "
        " hostname, archive_timestamp) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            upload_id,
            filename,
            storage_url,
            size_bytes,
            sha256,
            hostname,
            archive_timestamp,
        ),
    )


async def list_uploads(
    pool: AsyncConnectionPool,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Upload]:
    """Return uploads ordered newest-first, paginated."""
    return await fetch_all(
        pool,
        f"SELECT {_UPLOAD_COLUMNS} FROM radar.uploads "
        "ORDER BY created_at DESC LIMIT %s OFFSET %s",
        (limit, offset),
        row_factory=class_row(Upload),
    )


async def delete_upload(
    pool: AsyncConnectionPool, upload_id: UUID
) -> bool:
    """Delete an upload row.

    The foreign-key cascades in radar.jobs / snapshots / findings /
    briefs do the rest. Returns True if a row was deleted.
    """
    affected = await execute(
        pool,
        "DELETE FROM radar.uploads WHERE id = %s",
        (upload_id,),
    )
    return affected > 0


async def set_archive_files(
    pool: AsyncConnectionPool,
    upload_id: UUID,
    files: list[dict[str, Any]],
) -> None:
    """Persist the archive inventory snapshot for *upload_id*.

    Each entry shape: ``{path, kind, dbname, size}``. Unknown
    (coverage-canary) entries are stored with ``kind = None``.
    Overwrites any existing inventory for the upload.
    """
    await execute(
        pool,
        "UPDATE radar.uploads SET archive_files = %s::jsonb "
        "WHERE id = %s",
        (json.dumps(files), upload_id),
    )


async def get_archive_files(
    pool: AsyncConnectionPool, upload_id: UUID
) -> list[dict[str, Any]] | None:
    """Return the archive inventory for *upload_id*, or None.

    Returns ``None`` for both "no such upload" and "upload exists
    but inventory not yet persisted": callers needing to
    distinguish should also call :func:`get_upload`.
    """
    files: list[dict[str, Any]] | None = await fetch_scalar(
        pool,
        "SELECT archive_files FROM radar.uploads WHERE id = %s",
        (upload_id,),
    )
    return files


async def get_upload(
    pool: AsyncConnectionPool, upload_id: UUID
) -> Upload | None:
    """Fetch a single upload by id, or None if not found."""
    return await fetch_one(
        pool,
        f"SELECT {_UPLOAD_COLUMNS} FROM radar.uploads "
        "WHERE id = %s",
        (upload_id,),
        row_factory=class_row(Upload),
    )
