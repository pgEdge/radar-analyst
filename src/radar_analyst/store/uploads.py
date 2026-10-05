"""CRUD helpers for the ``radar.uploads`` table."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from radar_analyst.model import UploadListing
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

# An upload as the console lists it: the row plus the state and error
# of its most recent job and every verdict behind its roll-up,
# gathered in the one query so a page of fifty costs one round trip.
# The verdicts are the category briefs' and each database's, which
# the snapshot gains once the databases have been assessed; lax-mode
# jsonpath yields nothing for a snapshot without them.
_LISTING_SELECT = (
    "SELECT u.id, u.filename, u.storage_url, u.size_bytes, u.sha256, "
    "       u.hostname, u.archive_timestamp, u.created_at, "
    "       j.state AS job_state, j.error AS job_error, "
    "       COALESCE((SELECT array_agg(b.verdict) FROM radar.briefs b "
    "         WHERE b.upload_id = u.id), '{}') "
    "       || COALESCE((SELECT array_agg(v #>> '{}') "
    "         FROM radar.snapshots s, jsonb_path_query("
    "           s.data, '$.databases[*].brief_verdict') AS v "
    "         WHERE s.upload_id = u.id), '{}') AS verdicts "
    "FROM radar.uploads u "
    "LEFT JOIN LATERAL (SELECT state, error FROM radar.jobs "
    "    WHERE upload_id = u.id "
    "    ORDER BY started_at DESC NULLS FIRST LIMIT 1) j ON true "
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
) -> list[UploadListing]:
    """Return uploads newest-first, each with job state and verdicts."""
    return await fetch_all(
        pool,
        _LISTING_SELECT
        + "ORDER BY u.created_at DESC LIMIT %s OFFSET %s",
        (limit, offset),
        row_factory=class_row(UploadListing),
    )


async def set_upload_context(
    pool: AsyncConnectionPool,
    upload_id: UUID,
    *,
    hostname: str | None = None,
    archive_timestamp: datetime | None = None,
) -> None:
    """Record what is now known about the upload's origin.

    Only the values given are written; a value not given keeps what
    the row already holds, so the hostname read from the archive can
    replace the one read from its name without touching the time.
    """
    await execute(
        pool,
        "UPDATE radar.uploads SET "
        "  hostname = COALESCE(%s, hostname), "
        "  archive_timestamp = COALESCE(%s, archive_timestamp) "
        "WHERE id = %s",
        (hostname, archive_timestamp, upload_id),
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
) -> UploadListing | None:
    """Fetch a single upload by id, or None if not found."""
    return await fetch_one(
        pool,
        _LISTING_SELECT + "WHERE u.id = %s",
        (upload_id,),
        row_factory=class_row(UploadListing),
    )
