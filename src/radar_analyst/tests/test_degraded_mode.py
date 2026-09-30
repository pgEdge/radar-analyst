"""Verdicts must survive an LLM outage.

With the provider down every brief loses its prose, but the
deterministic findings are still there, so each category verdict is
derived mechanically from the worst finding severity.
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg_pool import AsyncConnectionPool

from radar_analyst.ai.base import AIError, Request, Result
from radar_analyst.analyze.orchestrator import orchestrate
from radar_analyst.server.sse import SSEHub
from radar_analyst.store.briefs import list_briefs
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.findings import list_findings
from radar_analyst.store.jobs import insert_job
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

_DATABASES_TSV = (
    "datname\tnumbackends\txact_commit\txact_rollback\n"
    "activedb\t4\t9000\t120\n"
)

_CHECKSUMS_TSV = (
    "datname\tchecksum_failures\tchecksum_last_failure\n"
    "activedb\t3\t2024-01-01 00:00:00+00\n"
)


@dataclass
class DeadAdapter:
    """An analyzer whose provider is unreachable."""

    name: str = "dead"
    model: str = "dead-v0"

    def available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    async def analyze(self, req: Request) -> Result:
        raise AIError("provider unreachable")


def _make_zip(tmp_path: Path) -> Path:
    z = tmp_path / "radar-degraded.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("postgresql/version.tsv", _PG_VERSION)
        zf.writestr("postgresql/configuration.tsv", _PG_CONFIG)
        zf.writestr("system/sysctl.out", _SYSCTL)
        zf.writestr("system/proc/meminfo.out", _MEMINFO)
        zf.writestr("postgresql/databases.tsv", _DATABASES_TSV)
        zf.writestr(
            "postgresql/databases_checksums.tsv", _CHECKSUMS_TSV
        )
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
        sha256="b" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    await insert_job(
        pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="dead",
    )
    return upload_id, job_id


@pytest.mark.asyncio
async def test_every_brief_keeps_a_verdict_when_the_llm_is_down(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    await apply_migrations(fresh_pool)
    z = _make_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=DeadAdapter(),
        hub=SSEHub(),
    )
    rows = await list_briefs(fresh_pool, upload_id)
    assert rows, "the orchestrator must still persist briefs"
    missing = [r.category for r in rows if r.verdict is None]
    assert not missing, f"no verdict for: {missing}"
    by_cat = {r.category: r.verdict for r in rows}
    # A category with data yet zero findings reads HEALTHY even
    # with the provider down; one with no data stays UNKNOWN.
    assert by_cat["Host & OS"] == "HEALTHY"
    assert by_cat["Replication"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_per_db_verdict_survives_the_llm_being_down(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """A critical checksum finding survives a silent provider.

    The database stays CRITICAL even though no brief came back.
    """
    await apply_migrations(fresh_pool)
    z = _make_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=DeadAdapter(),
        hub=SSEHub(),
    )
    snap = await get_snapshot(fresh_pool, upload_id)
    assert snap is not None
    dbs = {d["datname"]: d for d in snap["databases"]}
    assert dbs["activedb"]["brief_verdict"] == "CRITICAL"


@pytest.mark.asyncio
async def test_findings_are_stored_when_the_llm_is_down(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    """The deterministic half of the assessment needs no provider."""
    await apply_migrations(fresh_pool)
    z = _make_zip(tmp_path)
    upload_id, job_id = await _seed(fresh_pool, z)
    await orchestrate(
        upload_id=upload_id,
        job_id=job_id,
        zip_path=z,
        pool=fresh_pool,
        analyzer=DeadAdapter(),
        hub=SSEHub(),
    )
    rows = await list_findings(fresh_pool, upload_id)
    assert "pg.config.shared_buffers_low" in {r.rule_id for r in rows}
