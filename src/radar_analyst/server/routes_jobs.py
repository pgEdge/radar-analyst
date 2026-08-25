"""GET /api/jobs/{id} and SSE stream at /api/jobs/{id}/events."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from radar_analyst.model import Job
from radar_analyst.server.deps import get_sse_hub, require_job
from radar_analyst.server.sse import SSEHub

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
) -> EventSourceResponse:
    """Progress-event stream for one job."""
    async def gen() -> AsyncIterator[dict[str, str]]:
        # If the job already finished, emit one terminal event and
        # close: there's no live stream to join and we don't want
        # the client to hang.
        """Yield the job's events, replaying terminal states."""
        if job.state == "done":
            yield {"data": json.dumps({"type": "done"})}
            return
        if job.state == "failed":
            yield {
                "data": json.dumps(
                    {
                        "type": "error",
                        "message": (
                            job.error or "job failed"
                        ),
                    }
                )
            }
            return
        async with hub.subscribe(job.id) as sub:
            async for event in sub.events():
                yield {"data": json.dumps(event)}

    return EventSourceResponse(gen())
