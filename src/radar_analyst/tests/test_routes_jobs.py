"""Tests for GET /api/jobs/{id} and its SSE stream."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.jobs import insert_job, update_job_state
from radar_analyst.store.uploads import insert_upload
from radar_analyst.tests.helpers import build_app


async def _seed(pool: AsyncConnectionPool) -> tuple[UUID, UUID]:
    upload_id = uuid4()
    job_id = uuid4()
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename="x.zip",
        storage_url=f"file:///tmp/{upload_id}.zip",
        size_bytes=0,
        sha256="a" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    await insert_job(
        pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="mock",
    )
    return upload_id, job_id


async def test_get_job_status_returns_state(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    _, job_id = await _seed(fresh_pool)
    with TestClient(app) as client:
        resp = client.get(f"/api/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(job_id)
    assert body["state"] == "queued"
    assert body["ai_provider"] == "mock"


async def test_get_job_404_for_missing_id(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get(f"/api/jobs/{uuid4()}")
    assert resp.status_code == 404


async def test_sse_stream_replays_done_state_for_finished_job(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    # A job that's already `done` when a client subscribes must get
    # a terminal event and close, not hang.
    app, _ = await build_app(fresh_pool, tmp_path)
    _, job_id = await _seed(fresh_pool)
    await update_job_state(
        fresh_pool, job_id, state="done", phase="complete"
    )
    with TestClient(app) as client:
        with client.stream(
            "GET", f"/api/jobs/{job_id}/events"
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()
    # sse-starlette formats events as "data: {...}\n\n"
    assert "data:" in body
    data_line = next(
        line for line in body.splitlines() if line.startswith("data:")
    )
    payload = json.loads(data_line.removeprefix("data:").strip())
    assert payload == {"type": "done"}


async def test_sse_stream_replays_error_state(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    _, job_id = await _seed(fresh_pool)
    await update_job_state(
        fresh_pool,
        job_id,
        state="failed",
        error="something broke",
    )
    with TestClient(app) as client:
        with client.stream(
            "GET", f"/api/jobs/{job_id}/events"
        ) as resp:
            assert resp.status_code == 200
            body = resp.read().decode()
    data_line = next(
        line for line in body.splitlines() if line.startswith("data:")
    )
    payload = json.loads(data_line.removeprefix("data:").strip())
    assert payload["type"] == "error"
    assert "something broke" in payload["message"]


async def test_sse_404_for_missing_job(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get(f"/api/jobs/{uuid4()}/events")
    assert resp.status_code == 404


async def test_stream_delivers_live_events_mid_run(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    # A running job's stream must deliver events as they are
    # published, not only replay a terminal state.
    import asyncio

    import httpx

    from radar_analyst.server.sse import SSEHub

    hub = SSEHub()
    app, _ = await build_app(fresh_pool, tmp_path, sse_hub=hub)
    upload_id, job_id = await _seed(fresh_pool)
    await update_job_state(
        fresh_pool, job_id, state="parsing", phase="reading"
    )

    transport = httpx.ASGITransport(app=app)

    async def _consume() -> list[dict[str, str]]:
        collected: list[dict[str, str]] = []
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            async with client.stream(
                "GET", f"/api/jobs/{job_id}/events"
            ) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    collected.append(
                        json.loads(line[5:].strip())
                    )
                    if collected[-1].get("type") == "done":
                        break
        return collected

    consumer = asyncio.create_task(_consume())
    # Let the stream subscribe before events are published.
    await asyncio.sleep(0.1)
    hub.publish(job_id, {"type": "phase", "phase": "parsing"})
    hub.publish(job_id, {"type": "done"})
    events = await asyncio.wait_for(consumer, timeout=5.0)
    assert events[0] == {"type": "phase", "phase": "parsing"}
    assert events[-1] == {"type": "done"}
