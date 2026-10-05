"""FastAPI application factory for radar-analyst."""

import psycopg
from fastapi import FastAPI, HTTPException, status
from psycopg_pool import AsyncConnectionPool

from radar_analyst import __version__
from radar_analyst.analyze.runner import JobRunner
from radar_analyst.blob.base import BlobStore
from radar_analyst.server.routes_config import router as config_router
from radar_analyst.server.routes_jobs import router as jobs_router
from radar_analyst.server.routes_uploads import router as uploads_router
from radar_analyst.server.sse import SSEHub
from radar_analyst.server.static import mount_static


# How long /readyz waits for a connection. It stays under the 5 s
# timeout of the image's healthcheck, so a database that does not
# answer reads as not ready rather than as a probe that hangs.
_READY_TIMEOUT = 3.0


def create_app(
    *,
    pool: AsyncConnectionPool | None = None,
    blob_store: BlobStore | None = None,
    sse_hub: SSEHub | None = None,
    job_runner: JobRunner | None = None,
    max_upload_bytes: int = 100 * 1024 * 1024,
    serve_static: bool = True,
    admin_token: str | None = None,
) -> FastAPI:
    """Build and return the radar-analyst FastAPI application.

    ``pool`` and ``blob_store`` are optional to keep simple smoke tests
    (e.g. the /healthz test) free of DB/filesystem fixtures. Routes that
    need them (``/api/uploads`` etc.) will raise at request time if they
    weren't provided.

    ``sse_hub`` defaults to a fresh in-process hub; tests inject their
    own when they want to observe events. ``job_runner`` is the
    background-analysis driver; if omitted, uploads land in the DB but
    no analysis runs (useful for unit-testing just the upload surface).
    """
    app = FastAPI(
        title="radar-analyst",
        version=__version__,
        description=(
            "Analyzes radar diagnostic zipfiles with deterministic "
            "rules plus per-category LLM synthesis."
        ),
    )
    app.state.pool = pool
    app.state.blob_store = blob_store
    app.state.sse_hub = sse_hub if sse_hub is not None else SSEHub()
    app.state.job_runner = job_runner
    app.state.max_upload_bytes = max_upload_bytes
    app.state.admin_token = admin_token

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness probe: static ok."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        """Readiness probe: ok only while the database answers."""
        pool = app.state.pool
        if pool is None:
            raise HTTPException(
                status_code=(
                    status.HTTP_503_SERVICE_UNAVAILABLE
                ),
                detail="db pool not initialized",
            )
        try:
            async with pool.connection(timeout=_READY_TIMEOUT) as conn:
                await conn.execute("SELECT 1")
        except psycopg.Error:
            raise HTTPException(
                status_code=(
                    status.HTTP_503_SERVICE_UNAVAILABLE
                ),
                detail="database not answering",
            ) from None
        return {"status": "ready"}

    app.include_router(uploads_router)
    app.include_router(jobs_router)
    app.include_router(config_router)

    # Registered after the real API routers and before the console
    # mount, so a mistyped API path gets a JSON 404 instead of
    # falling through to the catch-all and being answered in HTML.
    @app.api_route(
        "/api/{_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def api_not_found(_path: str) -> None:
        """JSON 404 for unmatched /api paths."""
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="not found",
        )

    # The console is mounted LAST so every API route above wins and
    # the mount catches only what is left.
    if serve_static:
        mount_static(app)

    return app
