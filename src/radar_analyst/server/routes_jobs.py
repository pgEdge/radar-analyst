"""GET /api/jobs/{id} and SSE stream at /api/jobs/{id}/events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from psycopg_pool import AsyncConnectionPool
from sse_starlette.sse import EventSourceResponse

from radar_analyst.model import Job
from radar_analyst.server.deps import get_pool, get_sse_hub, require_job
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.jobs import get_job


router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs/{job_id}")
async def get_job_status(
    job: Job = Depends(require_job),
) -> dict[str, Any]:
    """One job's state, phase, timestamps, and error."""
    return {
        "id": str(job.id),
        "upload_id": str(job.upload_id),
        "state": job.state,
        "phase": job.phase,
        "started_at": (
            job.started_at.isoformat()
            if job.started_at
            else None
        ),
        "finished_at": (
            job.finished_at.isoformat()
            if job.finished_at
            else None
        ),
        "error": job.error,
        "ai_provider": job.ai_provider,
    }


@router.get("/jobs/{job_id}/events")
async def stream_job_events(
    job: Job = Depends(require_job),
    hub: SSEHub = Depends(get_sse_hub),
    pool: AsyncConnectionPool = Depends(get_pool),
) -> EventSourceResponse:
    """Progress-event stream for one job."""
    async def gen() -> AsyncIterator[dict[str, str]]:
        """Yield the job's events, replaying terminal states."""
        async with hub.subscribe(job.id) as sub:
            # Read the state only once subscribed. A job saves its
            # final state before it publishes the final event, so a
            # job that finished since the lookup is seen here, and
            # one that finishes later reaches the subscription.
            current = await get_job(pool, job.id)
            if current is not None and current.state == "done":
                yield {"data": json.dumps({"type": "done"})}
                return
            if current is None or current.state == "failed":
                message = (
                    current.error or "job failed"
                    if current is not None
                    else "job not found"
                )
                yield {
                    "data": json.dumps(
                        {"type": "error", "message": message}
                    )
                }
                return
            async for event in sub.events():
                yield {"data": json.dumps(event)}

    return EventSourceResponse(gen())
