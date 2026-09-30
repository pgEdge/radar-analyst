"""The /api/uploads routes: upload, list, read, delete, download.

``POST /api/uploads`` streams the request body straight into the
blob store (no full in-memory buffer), inserts a row into
``radar.uploads``, enqueues a ``queued`` job in ``radar.jobs``,
and returns ``{upload_id, job_id}``. The remaining routes list
uploads, read one upload's metadata / snapshot / assessment /
file inventory, stream single archive entries, delete an upload
behind the admin token, and assess an upload again from its stored
archive.
"""

import logging
import zipfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC
from typing import Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi import (
    File as FastAPIFile,
)
from fastapi.responses import StreamingResponse
from psycopg_pool import AsyncConnectionPool

from radar_analyst.analyze.assessment import rollup_verdict
from radar_analyst.analyze.runner import JobRunner
from radar_analyst.analyze.sources import sources_for_category
from radar_analyst.archive.naming import parse_archive_name
from radar_analyst.blob.base import BlobStore, download_to_temp
from radar_analyst.model import UploadListing
from radar_analyst.server.deps import (
    get_blob_store,
    get_job_runner,
    get_max_upload_bytes,
    get_pool,
    require_admin_token,
    require_upload,
)
from radar_analyst.store.briefs import delete_briefs, list_briefs
from radar_analyst.store.findings import delete_findings, list_findings
from radar_analyst.store.jobs import insert_job
from radar_analyst.store.snapshots import get_snapshot
from radar_analyst.store.uploads import (
    delete_upload,
    get_archive_files,
    insert_upload,
    list_uploads,
)


_logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["uploads"])

# Read this much from the UploadFile at a time when streaming to blob.
_READ_CHUNK = 1 * 1024 * 1024  # 1 MiB


# Local (PK\x03\x04) and empty-archive (PK\x05\x06) zip headers.
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")


async def _bounded_stream(
    upload: UploadFile, max_bytes: int
) -> AsyncIterator[bytes]:
    """Yield UploadFile chunks, enforcing type and size.

    The first bytes must carry zip magic (415 otherwise, since
    radar archives are zipfiles) and the running total must stay
    within *max_bytes* (413 otherwise).
    """
    total = 0
    first = True
    while True:
        chunk = await upload.read(_READ_CHUNK)
        if not chunk:
            break
        if first:
            if not chunk.startswith(_ZIP_MAGIC):
                raise HTTPException(
                    status_code=(
                        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
                    ),
                    detail="not a zip archive",
                )
            first = False
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    f"upload exceeds max_upload_bytes "
                    f"({max_bytes})"
                ),
            )
        yield chunk
    if first:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="empty upload: not a zip archive",
        )


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def post_upload(
    file: UploadFile = FastAPIFile(...),
    pool: AsyncConnectionPool = Depends(get_pool),
    store: BlobStore = Depends(get_blob_store),
    max_bytes: int = Depends(get_max_upload_bytes),
    runner: JobRunner | None = Depends(get_job_runner),
) -> dict[str, str]:
    """Accept a radar zip, store it, enqueue analysis."""
    upload_id = uuid4()
    job_id = uuid4()
    key = f"{upload_id}.zip"
    result = await store.put(
        key, _bounded_stream(file, max_bytes)
    )
    # Once the blob is on disk, any failure before the upload row
    # is committed leaks storage: the file has no DB row pointing
    # to it, so it can never be cleaned up by a delete. Roll back
    # best-effort and re-raise so FastAPI returns the original
    # error to the client.
    # Radar names the archive after the host and the moment of
    # collection, so both are known before the archive is read. The
    # name carries no zone, so the time is taken as UTC.
    named = parse_archive_name(file.filename or "")
    try:
        await insert_upload(
            pool,
            upload_id=upload_id,
            filename=file.filename or key,
            storage_url=result.url,
            size_bytes=result.size,
            sha256=result.sha256,
            hostname=named.hostname if named else None,
            archive_timestamp=(
                named.collected_at.replace(tzinfo=UTC) if named else None
            ),
        )
        ai_provider = (
            runner.analyzer_name
            if runner is not None
            else None
        )
        await insert_job(
            pool,
            job_id=job_id,
            upload_id=upload_id,
            ai_provider=ai_provider,
        )
    except BaseException:
        try:
            await store.delete(result.url)
        except Exception as exc:
            _logger.warning(
                "blob rollback failed for %s: %s",
                upload_id,
                exc,
            )
        raise
    if runner is not None:
        runner.start(
            upload_id=upload_id,
            job_id=job_id,
            storage_url=result.url,
        )
    return {
        "upload_id": str(upload_id),
        "job_id": str(job_id),
    }


def _upload_dict(upload: UploadListing) -> dict[str, object]:
    return {
        "id": str(upload.id),
        "filename": upload.filename,
        "storage_url": upload.storage_url,
        "size_bytes": upload.size_bytes,
        "sha256": upload.sha256,
        "hostname": upload.hostname,
        "archive_timestamp": (
            upload.archive_timestamp.isoformat()
            if upload.archive_timestamp
            else None
        ),
        "created_at": upload.created_at.isoformat(),
        "state": upload.job_state,
        "verdict": rollup_verdict(upload.verdicts),
    }


@router.get("/uploads")
async def list_uploads_route(
    limit: int = 50,
    offset: int = 0,
    pool: AsyncConnectionPool = Depends(get_pool),
) -> dict[str, object]:
    """Paginated uploads, newest first."""
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rows = await list_uploads(pool, limit=limit, offset=offset)
    return {
        "items": [_upload_dict(u) for u in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/uploads/{upload_id}")
async def get_upload_route(
    upload: UploadListing = Depends(require_upload),
) -> dict[str, object]:
    """One upload's metadata."""
    return _upload_dict(upload)


@router.delete(
    "/uploads/{upload_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_token)],
)
async def delete_upload_route(
    upload: UploadListing = Depends(require_upload),
    pool: AsyncConnectionPool = Depends(get_pool),
    store: BlobStore = Depends(get_blob_store),
) -> Response:
    # Blob removal is best-effort: the DB row is the source of
    # truth, so a missing blob (already cleaned up, store
    # migrated) must not block the user-facing delete. Anything
    # else: perms, quota, S3 auth: is logged so orphaned blobs
    # leave a trail instead of vanishing silently.
    """Delete an upload, its blob, and cascaded rows."""
    try:
        await store.delete(upload.storage_url)
    except FileNotFoundError:
        pass
    except Exception as exc:
        _logger.warning(
            "blob delete failed for %s: %s", upload.id, exc
        )
    await delete_upload(pool, upload.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/uploads/{upload_id}/assess",
    status_code=status.HTTP_202_ACCEPTED,
)
async def assess_again_route(
    upload: UploadListing = Depends(require_upload),
    pool: AsyncConnectionPool = Depends(get_pool),
    runner: JobRunner | None = Depends(get_job_runner),
) -> dict[str, str]:
    """Assess the upload again from its stored archive.

    The previous briefs and findings are removed first, so the
    assessment page never shows two results side by side; the new
    run replaces the snapshot when it writes one. Refused with 409
    while an assessment of the upload is still running.
    """
    running = upload.job_state is not None and (
        upload.job_state not in ("done", "failed")
    )
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this upload is still being assessed",
        )
    await delete_briefs(pool, upload.id)
    await delete_findings(pool, upload.id)
    job_id = uuid4()
    await insert_job(
        pool,
        job_id=job_id,
        upload_id=upload.id,
        ai_provider=(
            runner.analyzer_name if runner is not None else None
        ),
    )
    if runner is not None:
        runner.start(
            upload_id=upload.id,
            job_id=job_id,
            storage_url=upload.storage_url,
        )
    return {
        "upload_id": str(upload.id),
        "job_id": str(job_id),
    }


@router.get("/uploads/{upload_id}/snapshot")
async def get_snapshot_route(
    upload_id: UUID,
    pool: AsyncConnectionPool = Depends(get_pool),
) -> dict[str, object]:
    """The upload's parsed snapshot document."""
    data = await get_snapshot(pool, upload_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="snapshot not found",
        )
    return data


@router.get("/uploads/{upload_id}/assessment")
async def get_assessment_route(
    upload_id: UUID,
    pool: AsyncConnectionPool = Depends(get_pool),
) -> dict[str, object]:
    """The upload's briefs plus the roll-up verdict over them.

    An upload that hasn't been assessed yet returns an empty brief
    list and a null verdict rather than a 404, because the console
    polls this while the job is still running.
    """
    rows = await list_briefs(pool, upload_id)
    inventory = (
        await get_archive_files(pool, upload_id) or []
    )
    findings: dict[str, list[dict[str, str | None]]] = {}
    for f in await list_findings(pool, upload_id):
        findings.setdefault(f.category, []).append(
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "title": f.title,
                "detail": f.detail,
            }
        )
    return {
        "verdict": rollup_verdict([r.verdict for r in rows]),
        "briefs": [
            {
                "id": str(r.id),
                "category": r.category,
                "provider": r.provider,
                "model": r.model,
                "verdict": r.verdict,
                "markdown": r.markdown,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "created_at": r.created_at.isoformat(),
                "findings": findings.get(r.category, []),
                "sources": sources_for_category(
                    r.category, inventory
                ),
            }
            for r in rows
        ],
    }


@router.get("/uploads/{upload_id}/files")
async def list_files_route(
    upload: UploadListing = Depends(require_upload),
    pool: AsyncConnectionPool = Depends(get_pool),
) -> dict[str, object]:
    """Inventory of every entry in the upload's radar zip.

    Returns the persisted ``archive_files`` snapshot: populated
    by the orchestrator at analysis-time. An upload that exists
    but hasn't been analysed yet returns ``items: []``.
    """
    inventory = (
        await get_archive_files(pool, upload.id) or []
    )
    return {"items": inventory}


_DOWNLOAD_CHUNK = 64 * 1024


def _content_type_for(path: str) -> str:
    if path.endswith(".tsv"):
        return "text/tab-separated-values; charset=utf-8"
    if path.endswith((".out", ".conf", ".done", ".txt")):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _path_in_inventory(
    path: str, inventory: list[dict[str, Any]]
) -> bool:
    return any(e.get("path") == path for e in inventory)


@router.get("/uploads/{upload_id}/files/{archive_path:path}")
async def download_file_route(
    archive_path: str,
    upload: UploadListing = Depends(require_upload),
    pool: AsyncConnectionPool = Depends(get_pool),
    blob: BlobStore = Depends(get_blob_store),
) -> StreamingResponse:
    """Stream a single entry out of the upload's radar zip.

    The requested path must appear in the persisted inventory.
    Anything else (including ``..`` traversal attempts) is a
    plain 404: the inventory is the whitelist.
    """
    inventory = (
        await get_archive_files(pool, upload.id) or []
    )
    if not _path_in_inventory(archive_path, inventory):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="file not in upload inventory",
        )

    tmp_path = await download_to_temp(
        blob, upload.storage_url
    )

    def iter_entry() -> Iterator[bytes]:
        # A sync generator on purpose: Starlette iterates sync
        # bodies on a worker thread, keeping blocking zipfile
        # reads off the event loop. The tempfile is removed when
        # the generator closes, including on client disconnect.
        """Yield the entry's bytes off the event loop."""
        try:
            with zipfile.ZipFile(tmp_path) as zf:
                try:
                    info = zf.getinfo(archive_path)
                except KeyError:
                    return
                with zf.open(info) as raw:
                    while True:
                        chunk = raw.read(_DOWNLOAD_CHUNK)
                        if not chunk:
                            return
                        yield chunk
        finally:
            tmp_path.unlink(missing_ok=True)

    basename = archive_path.rsplit("/", 1)[-1] or "file"
    headers = {
        "content-disposition": (
            f'attachment; filename="{basename}"'
        ),
    }
    return StreamingResponse(
        iter_entry(),
        media_type=_content_type_for(archive_path),
        headers=headers,
    )


__all__ = ["UUID", "router"]
