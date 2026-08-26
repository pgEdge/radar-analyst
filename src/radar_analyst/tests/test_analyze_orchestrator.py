"""End-to-end tests for the orchestrator (using the mock AI provider)."""

import asyncio
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.ai.mock import MockAdapter
from radar_analyst.analyze.categories import CATEGORIES
from radar_analyst.analyze.orchestrator import orchestrate
from radar_analyst.analyze.parsing import read_and_parse
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.briefs import list_briefs
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.jobs import get_job, insert_job
from radar_analyst.store.snapshots import get_snapshot
from radar_analyst.store.uploads import insert_upload


_PG_VERSION = (
    "version\nPostgreSQL 17.2 on x86_64-pc-linux-gnu, "
    "compiled by gcc 13.2.0, 64-bit\n"
)

_PG_CONFIG = (
    "name\tsetting\tunit\tcategory\tshort_desc\n"
    "shared_buffers\t16384\t8kB\tResource Usage / Memory\t"
    "Sets shared memory buffer count.\n"
    "max_connections\t100\t\tConnections\t"
    "Sets max concurrent connections.\n"
)

_SYSCTL = (
    "abi.vsyscall32 = 1\n"
    "vm.swappiness = 10\n"
    "vm.overcommit_memory = 2\n"
    "kernel.shmmax = 18446744073692774399\n"
    "net.core.somaxconn = 4096\n"
)

_MEMINFO = (
    "MemTotal:       16384000 kB\n"
    "MemFree:         1024000 kB\n"
    "MemAvailable:    8192000 kB\n"
    "Buffers:          128000 kB\n"
    "Cached:          4096000 kB\n"
    "SwapTotal:       0 kB\n"
    "SwapFree:        0 kB\n"
)


def _make_radar_zip(tmp_path: Path) -> Path:
    """Build a minimal but realistic radar-style zip fixture."""
    z = tmp_path / "radar-test.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        zf.writestr("postgresql/configuration.tsv", _PG_CONFIG)
        zf.writestr("system/sysctl.out", _SYSCTL)
        zf.writestr("system/proc/meminfo.out", _MEMINFO)
        # One file with no registered parser, to exercise the
        # coverage canary.
        zf.writestr("something/unknown.bin", b"xxxx")
    return z


async def _seed(
    pool: AsyncConnectionPool, zip_path: Path
) -> tuple[UUID, UUID]:
    upload_id = uuid4()
    job_id = uuid4()
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename=zip_path.name,
        storage_url=f"file://{zip_path}",
        size_bytes=zip_path.stat().st_size,
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


@pytest.mark.asyncio
async def test_orchestrate_produces_briefs_for_all_categories(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    z = _make_radar_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    hub = SSEHub()
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=hub,
    )
    rows = await list_briefs(fresh_pool, upload_id)
    categories_persisted = {r.category for r in rows}
    categories_expected = {c.name for c in CATEGORIES}
    assert categories_persisted == categories_expected
    # Host & OS: mock LLM returns HEALTHY and no rule fires.
    # PostgreSQL Configuration: the fixture's shared_buffers
    # (128 MiB on 16 GiB RAM) triggers
    # pg.config.shared_buffers_low (warning), which floors the
    # tag to WARNING even though the mock returns HEALTHY.
    # Other four categories: short-circuited to UNKNOWN without
    # an LLM call (no parser data).
    by_cat = {r.category: r for r in rows}
    assert by_cat["Host & OS"].verdict == "HEALTHY"
    assert by_cat["Host & OS"].provider == "mock"
    assert (
        by_cat["PostgreSQL Configuration"].verdict
        == "WARNING"
    )
    for cat_name in (
        "Workload",
        "Internals & I/O Health",
        "Replication",
    ):
        assert by_cat[cat_name].verdict == "UNKNOWN"
        assert by_cat[cat_name].prompt_tokens is None


@pytest.mark.asyncio
async def test_orchestrate_marks_job_done(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    z = _make_radar_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    job = await get_job(fresh_pool, job_id)
    assert job is not None
    assert job.state == "done"
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_orchestrate_persists_snapshot_with_coverage_canary(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    z = _make_radar_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    assert snap["unknown_entries"] == [
        "something/unknown.bin"
    ]
    assert "pg.version" in snap["parsed_kinds"]
    assert "pg.settings" in snap["parsed_kinds"]
    assert "sys.sysctl" in snap["parsed_kinds"]
    assert "sys.proc.meminfo" in snap["parsed_kinds"]
    assert "PostgreSQL 17.2" in snap["pg_version"]
    # No radar.out in the fixture → pre-0.5.0 zip behaviour:
    # snapshot reports None instead of crashing.
    assert snap["radar_version"] is None
    assert snap["radar_commit"] is None


@pytest.mark.asyncio
async def test_orchestrate_captures_radar_meta_when_present(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    z = _make_radar_zip(tmp_path)
    # Inject radar.out into the existing fixture zip: same
    # format radar 0.5.0+ writes.
    with zipfile.ZipFile(z, "a") as zf:
        zf.writestr(
            "radar.out", b"version: v0.5.0\ncommit: abc1234\n"
        )
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    assert snap["radar_version"] == "v0.5.0"
    assert snap["radar_commit"] == "abc1234"


@pytest.mark.asyncio
async def test_orchestrate_emits_expected_sse_events(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    z = _make_radar_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    hub = SSEHub()

    events: list[dict[str, object]] = []

    async def consume() -> None:
        async with hub.subscribe(job_id) as sub:
            async for ev in sub.events():
                events.append(ev)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0.01)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=hub,
    )
    await asyncio.wait_for(consumer, timeout=2.0)

    types = [e["type"] for e in events]
    assert types[0] == "phase"
    assert types[-1] == "done"
    analysis_events = [
        e for e in events if e["type"] == "brief"
    ]
    assert len(analysis_events) == len(CATEGORIES)


@pytest.mark.asyncio
async def test_orchestrate_marks_job_failed_on_error(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    # A path that doesn't exist: orchestrate must catch and record.
    bogus = tmp_path / "does-not-exist.zip"
    upload_id = uuid4()
    job_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="x.zip",
        storage_url=f"file://{bogus}",
        size_bytes=0,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    await insert_job(
        fresh_pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="mock",
    )
    with pytest.raises(Exception):
        await orchestrate(
            upload_id=upload_id,
            job_id=job_id,
            zip_path=bogus,
            pool=fresh_pool,
            analyzer=MockAdapter(),
            hub=SSEHub(),
        )
    job = await get_job(fresh_pool, job_id)
    assert job is not None
    assert job.state == "failed"
    assert job.error


@pytest.mark.asyncio
async def test_orchestrate_marks_job_failed_on_corrupt_zip(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    corrupt = tmp_path / "corrupt.zip"
    corrupt.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    upload_id, job_id = await _seed(fresh_pool, corrupt)
    with pytest.raises(Exception):
        await orchestrate(
            upload_id=upload_id,
            job_id=job_id,
            zip_path=corrupt,
            pool=fresh_pool,
            analyzer=MockAdapter(),
            hub=SSEHub(),
        )
    job = await get_job(fresh_pool, job_id)
    assert job is not None
    assert job.state == "failed"
    assert job.error is not None
    assert "zip" in job.error.lower()


def test_read_and_parse_sets_container_flag(tmp_path: Path) -> None:
    z = tmp_path / "container.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        zf.writestr("system/container/dockerenv.out", "")
    parsed, _, _, _, _ = read_and_parse(z)
    assert parsed["sys.is_container"] is True


def test_read_and_parse_container_flag_false_on_bare_host(
    tmp_path: Path,
) -> None:
    z = tmp_path / "bare.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
    parsed, _, _, _, _ = read_and_parse(z)
    assert parsed["sys.is_container"] is False


# ---------------------------------------------------------------------------
# Per-db conditional LLM analysis tests
# ---------------------------------------------------------------------------

_DATABASES_TSV = (
    "oid\tdatname\tdatdba\tencoding\tdatcollate\tdatctype\n"
    "5\tpostgres\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
    "4\ttemplate0\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
    "1\ttemplate1\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
    "17028\tactivedb\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
    "17029\tidledb\t10\t6\ten_US.UTF-8\ten_US.UTF-8\n"
)

# activedb: 500 commits + 10 rollbacks = 510 > 100 → qualifies for LLM
# idledb: 0 activity → static "no issues" card
_DATABASES_XACT_TSV = (
    "datname\txact_commit\txact_rollback\n"
    "postgres\t0\t0\n"
    "activedb\t500\t10\n"
    "idledb\t0\t0\n"
)


def _make_radar_zip_with_dbs(tmp_path: Path) -> Path:
    z = tmp_path / "radar-dbs.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        zf.writestr("postgresql/configuration.tsv", _PG_CONFIG)
        zf.writestr("system/sysctl.out", _SYSCTL)
        zf.writestr("system/proc/meminfo.out", _MEMINFO)
        zf.writestr(
            "postgresql/databases.tsv", _DATABASES_TSV
        )
        zf.writestr(
            "postgresql/databases_xact.tsv",
            _DATABASES_XACT_TSV,
        )
    return z


@pytest.mark.asyncio
async def test_orchestrate_active_db_gets_brief_markdown(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """Activedb (commits+rollbacks > 100) triggers an LLM call."""
    await apply_migrations(fresh_pool)
    z = _make_radar_zip_with_dbs(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    dbs_by_name = {d["datname"]: d for d in snap["databases"]}
    assert "activedb" in dbs_by_name
    active = dbs_by_name["activedb"]
    # The mock LLM returns HEALTHY; no rule fires, so tag stays HEALTHY.
    assert active.get("brief_markdown") is not None
    assert "HEALTHY" in (active.get("brief_markdown") or "")
    assert active.get("brief_verdict") == "HEALTHY"


@pytest.mark.asyncio
async def test_orchestrate_idle_db_gets_static_no_issues(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """Idledb (0 commits, 0 rollbacks, 0 backends, no findings)
    gets the static 'no issues observed' card without an LLM call.
    """
    await apply_migrations(fresh_pool)
    z = _make_radar_zip_with_dbs(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    dbs_by_name = {d["datname"]: d for d in snap["databases"]}
    assert "idledb" in dbs_by_name
    idle = dbs_by_name["idledb"]
    # Static card: no LLM call fired, deterministic text.
    assert "no issues" in (idle.get("brief_markdown") or "").lower()
    assert idle.get("brief_verdict") == "HEALTHY"


@pytest.mark.asyncio
async def test_orchestrate_per_db_severity_floor_applied(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """A db with a critical rule finding gets at least CRITICAL tag,
    even though the mock returns HEALTHY.
    """
    await apply_migrations(fresh_pool)
    # Build a zip where activedb has a checksum failure (critical
    # rule). We use the checksums file; the rule fires when
    # checksum_failures > 0.
    _checksums_tsv = (
        "datname\tchecksum_failures\tchecksum_last_failure\n"
        "activedb\t3\t2024-01-01 00:00:00+00\n"
    )
    z = tmp_path / "radar-cf.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        zf.writestr("postgresql/configuration.tsv", _PG_CONFIG)
        zf.writestr("system/sysctl.out", _SYSCTL)
        zf.writestr("system/proc/meminfo.out", _MEMINFO)
        zf.writestr(
            "postgresql/databases.tsv", _DATABASES_TSV
        )
        zf.writestr(
            "postgresql/databases_checksums.tsv",
            _checksums_tsv,
        )
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=MockAdapter(),
        hub=SSEHub(),
    )
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    dbs_by_name = {d["datname"]: d for d in snap["databases"]}
    active = dbs_by_name["activedb"]
    # checksum_failures finding is critical; severity floor must
    # upgrade the mock's HEALTHY to CRITICAL.
    assert active.get("brief_verdict") == "CRITICAL"
