"""Shared dataclasses used across the service boundary."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Upload:
    """One row of ``radar.uploads``."""
    id: UUID
    filename: str
    storage_url: str
    size_bytes: int
    sha256: str
    hostname: str | None
    archive_timestamp: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class Job:
    """One row of ``radar.jobs``."""
    id: UUID
    upload_id: UUID
    state: str
    phase: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    ai_provider: str | None


@dataclass(frozen=True)
class Brief:
    """One row of ``radar.briefs``."""
    id: UUID
    upload_id: UUID
    category: str
    provider: str
    model: str
    verdict: str | None
    markdown: str
    prompt_tokens: int | None
    completion_tokens: int | None
    created_at: datetime
