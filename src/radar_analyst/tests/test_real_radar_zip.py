"""Validation test against a real radar zip.

Skipped by default; opt in by pointing ``RADAR_SAMPLE_ZIP`` at a
path that exists. Intended to validate that:

- the classifier has zero ``unknown_entries`` on a current radar
  version;
- each MVP parser decodes its real input cleanly;
- safety caps accommodate a pg_statviz-heavy archive without
  raising ``ZipSafetyError`` at walk time.

Running:

    RADAR_SAMPLE_ZIP=/path/to/radar-host-YYYYMMDD-HHMMSS.zip \
        .venv/bin/pytest -v src/radar_analyst/tests/test_real_radar_zip.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.archive.reader import (
    list_entries,
    open_entry,
    walk,
)
from radar_analyst.parse.meminfo import parse_meminfo
from radar_analyst.parse.pg_settings import parse_pg_settings
from radar_analyst.parse.pg_version import parse_version
from radar_analyst.parse.sysctl import PG_RELEVANT_KEYS, parse_sysctl


def _read_small(
    path: Path,
    entry: str,
    max_bytes: int = 1 * 1024 * 1024,
) -> bytes:
    """Test helper: read a small entry into bytes via open_entry."""
    with open_entry(path, entry, max_bytes=max_bytes) as fh:
        return fh.read(max_bytes + 1)


def _sample_path() -> Path | None:
    raw = os.environ.get("RADAR_SAMPLE_ZIP")
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else None


_SAMPLE = _sample_path()


pytestmark = pytest.mark.skipif(
    _SAMPLE is None,
    reason="RADAR_SAMPLE_ZIP not set or file missing",
)


def test_walk_has_no_unknown_entries() -> None:
    assert _SAMPLE is not None
    _, unknown = walk(_SAMPLE)
    # If this fails, add the surprising paths to the classifier's
    # fixed table in archive/reader.py.
    assert unknown == [], (
        f"classifier missed {len(unknown)} entries: "
        f"{unknown[:10]}"
    )


def test_walk_stays_within_safety_caps() -> None:
    # If limits are wrong they surface as ZipSafetyError here.
    assert _SAMPLE is not None
    entries = list_entries(_SAMPLE)
    assert entries, "expected at least one entry"


def test_pg_version_parser_matches_real_output() -> None:
    assert _SAMPLE is not None
    data = _read_small(_SAMPLE, "postgresql/version.tsv")
    info = parse_version(data)
    assert info is not None
    assert info.major > 0
    assert "PostgreSQL" in info.raw


def test_pg_settings_parser_matches_real_output() -> None:
    assert _SAMPLE is not None
    data = _read_small(_SAMPLE, "postgresql/configuration.tsv")
    settings = parse_pg_settings(data)
    # A live Postgres has hundreds of pg_settings rows.
    assert len(settings.all) > 100
    # A few key settings should always be present.
    for name in (
        "shared_buffers",
        "max_connections",
        "wal_level",
    ):
        assert settings.get(name) is not None, name


def test_sysctl_parser_matches_real_output() -> None:
    assert _SAMPLE is not None
    data = _read_small(_SAMPLE, "system/sysctl.out")
    out = parse_sysctl(data)
    # Whitelist is ~30 keys; a real Linux host has at least some of
    # them. We don't assert a strict count (non-Linux or kernel
    # variants may omit some), but require the filter worked.
    assert all(k in PG_RELEVANT_KEYS for k in out)
    assert len(out) > 0


def test_meminfo_parser_matches_real_output() -> None:
    assert _SAMPLE is not None
    data = _read_small(_SAMPLE, "system/proc/meminfo.out")
    info = parse_meminfo(data)
    assert info.get("MemTotal", 0) > 0
    assert info.get("MemAvailable", 0) > 0


async def test_orchestrator_runs_end_to_end_against_real_zip(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """Full pipeline: classify, parse, prompt, mock-LLM, persist.

    The mock provider is used so this test doesn't need real API
    keys; the value is in exercising the real classifier + real
    parsers against real radar output and confirming the orchestrator
    produces one analysis per category without raising.
    """
    assert _SAMPLE is not None
    from uuid import uuid4

    from radar_analyst.ai.mock import MockAdapter
    from radar_analyst.analyze.categories import CATEGORIES
    from radar_analyst.analyze.orchestrator import orchestrate
    from radar_analyst.server.sse import SSEHub
    from radar_analyst.store.briefs import list_briefs
    from radar_analyst.store.db import apply_migrations
    from radar_analyst.store.jobs import get_job, insert_job
    from radar_analyst.store.snapshots import get_snapshot
    from radar_analyst.store.uploads import insert_upload

    pool = fresh_pool
    await apply_migrations(pool)
    upload_id = uuid4()
    job_id = uuid4()
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename=_SAMPLE.name,
        storage_url=f"file://{_SAMPLE}",
        size_bytes=_SAMPLE.stat().st_size,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    await insert_job(
        pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="mock",
    )
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=_SAMPLE,
        pool=pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    job = await get_job(pool, job_id)
    assert job is not None
    assert job.state == "done"
    rows = await list_briefs(pool, upload_id)
    assert {r.category for r in rows} == {
        c.name for c in CATEGORIES
    }
    snap = await get_snapshot(pool, upload_id)
    assert snap is not None
    assert snap["unknown_entries"] == []
    assert "pg.version" in snap["parsed_kinds"]
    assert "sys.sysctl" in snap["parsed_kinds"]


def test_open_entry_streams_large_pg_statviz_without_buffer() -> None:
    """A 100+ MiB pg_statviz entry must be iterable chunk-by-chunk.

    We count rows via a streaming read, never holding the whole
    entry in memory at once. If the zip has no pg_statviz data,
    the test is a no-op (guarded by the existence check).
    """
    assert _SAMPLE is not None
    _, _ = walk(_SAMPLE)  # ensure walk itself doesn't blow up
    classified, _ = walk(_SAMPLE)
    pgsv = [
        c for c in classified if c.kind.startswith("pg_statviz.")
    ]
    if not pgsv:
        pytest.skip("sample has no pg_statviz data")
    entry = max(pgsv, key=lambda c: c.size)
    lines = 0
    bytes_seen = 0
    with open_entry(_SAMPLE, entry.path) as fh:
        for chunk in fh:
            bytes_seen += len(chunk)
            lines += chunk.count(b"\n")
    assert bytes_seen == entry.size
    assert lines > 0
