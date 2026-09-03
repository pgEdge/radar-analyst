"""FastAPI dependency-injection providers.

Kept separate from ``app.py`` so tests can override them via
``app.dependency_overrides`` without reaching into app internals.
"""

import hmac
from typing import TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from psycopg_pool import AsyncConnectionPool

from radar_analyst.analyze.runner import JobRunner
from radar_analyst.blob.base import BlobStore
from radar_analyst.model import Job, UploadListing
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.jobs import get_job
from radar_analyst.store.uploads import get_upload


_T = TypeVar("_T")


def _from_state(request: Request, attr: str, typ: type[_T]) -> _T:
    """Return a configured ``app.state`` attribute, or fail loudly.

    Misconfiguration is a server bug, so the failure is a
    RuntimeError (500) rather than an HTTP 4xx.
    """
    val = getattr(request.app.state, attr, None)
    if val is None:
        raise RuntimeError(f"{attr} not configured on app.state")
    if not isinstance(val, typ):
        raise RuntimeError(
            f"app.state.{attr} does not satisfy {typ.__name__}"
        )
    return val


def get_pool(request: Request) -> AsyncConnectionPool:
    """The shared async connection pool."""
    return _from_state(request, "pool", AsyncConnectionPool)


def get_blob_store(request: Request) -> BlobStore:
    """The configured blob store.

    Checked bespoke because ``BlobStore`` is a Protocol, which
    ``_from_state``'s ``type[...]`` parameter cannot carry.
    """
    store = getattr(request.app.state, "blob_store", None)
    if store is None:
        raise RuntimeError(
            "blob_store not configured on app.state"
        )
    if not isinstance(store, BlobStore):
        raise RuntimeError(
            "app.state.blob_store does not satisfy BlobStore"
        )
    return store


def get_max_upload_bytes(request: Request) -> int:
    """The configured upload size ceiling in bytes."""
    return _from_state(request, "max_upload_bytes", int)


def get_sse_hub(request: Request) -> SSEHub:
    """The in-process progress-event hub."""
    return _from_state(request, "sse_hub", SSEHub)


def require_admin_token(request: Request) -> None:
    """Authenticate destructive routes with a shared bearer token.

    The token is configured server-side via the ``admin_token``
    arg to :func:`create_app` (sourced from
    ``RADAR_ANALYST_ADMIN_TOKEN``). Clients must send it as
    ``Authorization: Bearer <token>``.

    Fails closed: if no token is configured the route returns 503
    rather than being silently open. There is no role separation:
    every authenticated caller is treated as admin.
    """
    configured = getattr(request.app.state, "admin_token", None)
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin auth not configured",
        )
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Compare as bytes: hmac.compare_digest on str raises
    # TypeError for non-ASCII content, which would otherwise
    # turn a 401 into a 500 for any client (or attacker) that
    # sends non-ASCII bytes in the Authorization header.
    if not hmac.compare_digest(
        token.encode("utf-8"), configured.encode("utf-8")
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_job_runner(request: Request) -> JobRunner | None:
    """Return the configured JobRunner, or None if uploads are view-only.

    Returning None instead of raising lets tests that only care about
    upload-row insertion skip wiring a runner without every route
    growing a conditional import guard.
    """
    runner = getattr(request.app.state, "job_runner", None)
    if runner is None:
        return None
    assert isinstance(runner, JobRunner)
    return runner


async def require_upload(
    upload_id: UUID,
    pool: AsyncConnectionPool = Depends(get_pool),
) -> UploadListing:
    """Resolve the ``upload_id`` path parameter, or 404."""
    upload = await get_upload(pool, upload_id)
    if upload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="upload not found",
        )
    return upload


async def require_job(
    job_id: UUID,
    pool: AsyncConnectionPool = Depends(get_pool),
) -> Job:
    """Resolve the ``job_id`` path parameter, or 404."""
    job = await get_job(pool, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="job not found",
        )
    return job
