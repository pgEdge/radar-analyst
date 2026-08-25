"""End-to-end test: POST /api/uploads triggers orchestrated analysis.

Uses the MockAdapter + a JobRunner so the full pipeline (upload →
blob store → background orchestrator → snapshot + briefs → SSE
terminal event) runs without hitting any real LLM API.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.ai.mock import MockAdapter
from radar_analyst.analyze.categories import CATEGORIES
from radar_analyst.analyze.runner import JobRunner
from radar_analyst.blob.localfs import LocalFsStore
from radar_analyst.server.app import create_app
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.briefs import list_briefs
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.snapshots import get_snapshot


_SAMPLE_PG_VERSION = (
    "version\nPostgreSQL 17.2 on x86_64-pc-linux-gnu\n"
)
_SAMPLE_SYSCTL = "vm.swappiness = 10\n"
_SAMPLE_MEMINFO = "MemTotal:       16384000 kB\n"


def _build_radar_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "postgresql/version.tsv", _SAMPLE_PG_VERSION
        )
        zf.writestr("system/sysctl.out", _SAMPLE_SYSCTL)
        zf.writestr(
            "system/proc/meminfo.out", _SAMPLE_MEMINFO
        )
    return buf.getvalue()


async def _run_task_for_job(
    runner: JobRunner, job_id: UUID
) -> None:
    """Wait for the analysis task for this job to finish."""
    task = runner.task_for(job_id)
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=10.0)
    except Exception:  # noqa: BLE001
        # Errors are persisted to jobs.error; test inspects DB.
        pass


@pytest.mark.asyncio
async def test_upload_triggers_orchestrated_analysis_end_to_end(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    store = LocalFsStore(data_dir=tmp_path)
    hub = SSEHub()
    runner = JobRunner(
        pool=fresh_pool,
        blob_store=store,
        analyzer=MockAdapter(),
        hub=hub,
    )
    app = create_app(
        pool=fresh_pool,
        blob_store=store,
        sse_hub=hub,
        job_runner=runner,
    )
    payload = _build_radar_zip_bytes()
    # Use httpx.AsyncClient (not TestClient) so the background task
    # created inside the route runs on the same event loop as this
    # test: TestClient tears down its portal loop once the request
    # returns, which kills the task before it can complete.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/uploads",
            files={"file": ("radar.zip", payload)},
        )
    assert resp.status_code == 201
    body = resp.json()
    upload_id = UUID(body["upload_id"])
    job_id = UUID(body["job_id"])

    await _run_task_for_job(runner, job_id)

    # Job reached done.
    from radar_analyst.store.jobs import get_job

    job = await get_job(fresh_pool, job_id)
    assert job is not None
    assert job.state == "done"

    # Snapshot persisted with coverage canary.
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    assert snap["unknown_entries"] == []
    assert "pg.version" in snap["parsed_kinds"]

    # Analyses persisted for all 6 categories.
    rows = await list_briefs(fresh_pool, upload_id)
    cats = {r.category for r in rows}
    assert cats == {c.name for c in CATEGORIES}
    by_cat = {r.category: r for r in rows}
    # Categories with parsed data run through the mock LLM and
    # come back HEALTHY; the rest are short-circuited to UNKNOWN
    # without an LLM call.
    assert by_cat["Host & OS"].verdict == "HEALTHY"
    assert by_cat["Host & OS"].provider == "mock"
    for cat_name in (
        "Workload",
        "Internals & I/O Health",
        "Replication",
    ):
        assert by_cat[cat_name].verdict == "UNKNOWN"
