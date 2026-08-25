"""CRUD helpers for the ``radar.jobs`` table."""

from uuid import UUID

from psycopg.rows import class_row
from psycopg_pool import AsyncConnectionPool

from radar_analyst.model import Job
from radar_analyst.store.db import execute, fetch_one

# Allowed job states; not enforced by the DB (plain TEXT column) so
# the rule lives here in code. The orchestrator drives every
# transition through these states.
JOB_STATES = frozenset(
    {"queued", "parsing", "ruling", "analyzing", "done", "failed"}
)


def _require_valid_state(state: str) -> None:
    if state not in JOB_STATES:
        raise ValueError(f"invalid job state: {state}")


async def insert_job(
    pool: AsyncConnectionPool,
    *,
    job_id: UUID,
    upload_id: UUID,
    ai_provider: str | None,
    state: str = "queued",
) -> None:
    """Insert one job row, refusing states outside JOB_STATES."""
    _require_valid_state(state)
    await execute(
        pool,
        "INSERT INTO radar.jobs "
        "(id, upload_id, state, ai_provider) "
        "VALUES (%s, %s, %s, %s)",
        (job_id, upload_id, state, ai_provider),
    )


async def update_job_state(
    pool: AsyncConnectionPool,
    job_id: UUID,
    *,
    state: str,
    phase: str | None = None,
    error: str | None = None,
) -> None:
    """Transition a job to *state*, optionally setting phase/error.

    Timestamps (``started_at`` / ``finished_at``) are populated
    automatically based on the transition: first non-``queued`` state
    sets ``started_at``; terminal states (``done``/``failed``) set
    ``finished_at``.
    """
    _require_valid_state(state)
    terminal = state in {"done", "failed"}
    await execute(
        pool,
        "UPDATE radar.jobs SET "
        "  state = %s, "
        "  phase = COALESCE(%s, phase), "
        "  error = COALESCE(%s, error), "
        "  started_at = COALESCE(started_at, now()), "
        "  finished_at = CASE WHEN %s "
        "    THEN now() ELSE finished_at END "
        "WHERE id = %s",
        (state, phase, error, terminal, job_id),
    )


async def get_job(
    pool: AsyncConnectionPool, job_id: UUID
) -> Job | None:
    """Fetch a single job by id, or None if not found."""
    return await fetch_one(
        pool,
        "SELECT id, upload_id, state, phase, started_at, "
        "       finished_at, error, ai_provider "
        "FROM radar.jobs WHERE id = %s",
        (job_id,),
        row_factory=class_row(Job),
    )
