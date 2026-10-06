"""Background job runner for analysis pipelines.

The HTTP upload endpoint returns as soon as the zipfile is streamed to
the blob store and the DB rows are written; the actual analysis runs
here as an :class:`asyncio.Task` tracked in a per-runner dict.

One runner instance is shared app-wide (installed on
``app.state.job_runner``). Concurrency is bounded by a semaphore
(default 4 parallel jobs) so that a burst of uploads can't exhaust
the LLM provider's rate limits or the Postgres pool.

A live :class:`asyncio.Task` is retained per job_id for the duration of
the run so tests can await it; it's cleaned up from the dict on
completion.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from radar_analyst.ai.base import Analyzer
from radar_analyst.analyze.orchestrator import fail_job, orchestrate
from radar_analyst.blob.base import BlobStore, download_to_temp
from radar_analyst.server.sse import SSEHub


_logger = logging.getLogger(__name__)


class JobRunner:
    """Background driver running one analysis task per job."""
    def __init__(  # noqa: D107
        self,
        *,
        pool: AsyncConnectionPool,
        blob_store: BlobStore,
        analyzer: Analyzer,
        hub: SSEHub,
        concurrency: int = 4,
    ) -> None:
        self._pool = pool
        self._blob = blob_store
        self._analyzer = analyzer
        self._hub = hub
        self._sem = asyncio.Semaphore(concurrency)
        self._tasks: dict[UUID, asyncio.Task[None]] = {}

    @property
    def analyzer_name(self) -> str:
        """Name of the AI provider this runner analyzes with."""
        return self._analyzer.name

    def start(
        self,
        *,
        upload_id: UUID,
        job_id: UUID,
        storage_url: str,
    ) -> asyncio.Task[None]:
        """Kick off the analysis pipeline and return the Task handle."""
        task = asyncio.create_task(
            self._run(
                upload_id=upload_id,
                job_id=job_id,
                storage_url=storage_url,
            ),
            name=f"radar-analyst-job-{job_id}",
        )
        self._tasks[job_id] = task
        task.add_done_callback(
            lambda _t: self._tasks.pop(job_id, None)
        )
        return task

    def task_for(
        self, job_id: UUID
    ) -> asyncio.Task[None] | None:
        """The live task for *job_id*, or None once finished."""
        return self._tasks.get(job_id)

    async def _run(
        self,
        *,
        upload_id: UUID,
        job_id: UUID,
        storage_url: str,
    ) -> None:
        async with self._sem:
            # Download the zip from the blob store to a tempfile so
            # this runner works against any BlobStore implementation
            # (not just localfs).
            try:
                tmp_path = await download_to_temp(
                    self._blob, storage_url
                )
            except Exception as e:
                await fail_job(
                    self._pool,
                    job_id,
                    self._hub,
                    RuntimeError(
                        f"the stored archive could not be read: {e}"
                    ),
                )
                return
            try:
                await orchestrate(
                    upload_id=upload_id,
                    job_id=job_id,
                    zip_path=tmp_path,
                    pool=self._pool,
                    analyzer=self._analyzer,
                    hub=self._hub,
                )
            except Exception:
                # The orchestrator has already persisted
                # job=failed and emitted the error event, so the
                # exception is swallowed here: the wrapper task
                # must not warn about a never-retrieved
                # exception. This log line is the operator trail.
                _logger.exception("job %s failed", job_id)
            finally:
                tmp_path.unlink(missing_ok=True)
