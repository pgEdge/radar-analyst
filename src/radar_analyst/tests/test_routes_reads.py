"""Tests for the read-side endpoints that power the UI.

Covers GET /api/uploads (list), GET /api/uploads/{id}, GET
/api/uploads/{id}/snapshot, GET /api/uploads/{id}/assessment, and
GET /api/config.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from radar_analyst.rules.base import Finding
from radar_analyst.store.briefs import insert_brief
from radar_analyst.store.findings import insert_findings
from radar_analyst.store.jobs import insert_job, update_job_state
from radar_analyst.store.snapshots import upsert_snapshot
from radar_analyst.store.uploads import insert_upload, set_archive_files
from radar_analyst.tests.helpers import build_app


async def _seed_upload_with_briefs(
    pool: AsyncConnectionPool,
) -> UUID:
    upload_id = uuid4()
    job_id = uuid4()
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename="radar-db01-20260401-120000.zip",
        storage_url=f"file:///tmp/{upload_id}.zip",
        size_bytes=4096,
        sha256="a" * 64,
        hostname="db01",
        archive_timestamp=None,
    )
    await insert_job(
        pool,
        job_id=job_id,
        upload_id=upload_id,
        ai_provider="mock",
    )
    await update_job_state(
        pool, job_id, state="done", phase="complete"
    )
    await upsert_snapshot(
        pool,
        upload_id=upload_id,
        data={
            "hostname": "db01",
            "pg_version": "PostgreSQL 17.2",
            "parsed_kinds": ["pg.version"],
            "unknown_entries": [],
        },
    )
    await insert_brief(
        pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Host & OS",
        provider="mock",
        model="mock-v0",
        verdict="HEALTHY",
        markdown="**[HEALTHY]** all good",
        prompt_tokens=100,
        completion_tokens=20,
    )
    return upload_id


@pytest.mark.asyncio
async def test_list_uploads_returns_recent_first(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    a = await _seed_upload_with_briefs(fresh_pool)
    b = await _seed_upload_with_briefs(fresh_pool)
    with TestClient(app) as client:
        resp = client.get("/api/uploads")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    ids = [u["id"] for u in body["items"]]
    # Both uploads present, newest first (b created after a).
    assert ids[0] == str(b)
    assert ids[1] == str(a)


@pytest.mark.asyncio
async def test_list_uploads_paginates(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    for _ in range(5):
        await _seed_upload_with_briefs(fresh_pool)
    with TestClient(app) as client:
        resp = client.get("/api/uploads?limit=2")
    body = resp.json()
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_upload_returns_row(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    with TestClient(app) as client:
        resp = client.get(f"/api/uploads/{upload_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(upload_id)
    assert body["hostname"] == "db01"
    assert body["size_bytes"] == 4096


@pytest.mark.asyncio
async def test_get_upload_404(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get(f"/api/uploads/{uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_snapshot(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/snapshot"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hostname"] == "db01"
    assert body["unknown_entries"] == []


@pytest.mark.asyncio
async def test_get_snapshot_404(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{uuid4()}/snapshot"
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_assessment(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/assessment"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "HEALTHY"
    assert len(body["briefs"]) == 1
    a = body["briefs"][0]
    assert a["category"] == "Host & OS"
    assert a["verdict"] == "HEALTHY"
    assert a["markdown"] == "**[HEALTHY]** all good"
    assert a["sources"] == []  # no inventory persisted yet


@pytest.mark.asyncio
async def test_assessment_verdict_is_the_worst_category_verdict(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    await insert_brief(
        fresh_pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Replication",
        provider="mock",
        model="mock-v0",
        verdict="CRITICAL",
        markdown="**[CRITICAL]** slot is stuck",
        prompt_tokens=None,
        completion_tokens=None,
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/assessment"
        )
    body = resp.json()
    assert body["verdict"] == "CRITICAL"
    assert len(body["briefs"]) == 2


@pytest.mark.asyncio
async def test_a_database_verdict_counts_toward_the_overall_verdict(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    await upsert_snapshot(
        fresh_pool,
        upload_id=upload_id,
        data={
            "hostname": "db01",
            "databases": [
                {"datname": "app", "brief_verdict": "CRITICAL"},
            ],
        },
    )
    with TestClient(app) as client:
        assessment = client.get(
            f"/api/uploads/{upload_id}/assessment"
        ).json()
        listed = client.get("/api/uploads").json()["items"][0]
        upload = client.get(f"/api/uploads/{upload_id}").json()
    assert assessment["verdict"] == "CRITICAL"
    assert listed["verdict"] == "CRITICAL"
    assert upload["verdict"] == "CRITICAL"


@pytest.mark.asyncio
async def test_a_database_not_yet_assessed_does_not_count(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    await upsert_snapshot(
        fresh_pool,
        upload_id=upload_id,
        data={
            "hostname": "db01",
            "databases": [{"datname": "app", "severity": "CRITICAL"}],
        },
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/uploads/{upload_id}/assessment")
    assert resp.json()["verdict"] == "HEALTHY"


@pytest.mark.asyncio
async def test_assessment_of_unanalysed_upload_has_no_verdict(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="radar-db02-20260401-120000.zip",
        storage_url=f"file:///tmp/{upload_id}.zip",
        size_bytes=1024,
        sha256="c" * 64,
        hostname="db02",
        archive_timestamp=None,
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/assessment"
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] is None
    assert body["briefs"] == []


@pytest.mark.asyncio
async def test_assessment_includes_sources_per_category(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    await set_archive_files(
        fresh_pool,
        upload_id,
        [
            {
                "path": "system/proc/meminfo.out",
                "kind": "sys.proc.meminfo",
                "dbname": None,
                "size": 100,
            },
            {
                "path": "system/sysctl.out",
                "kind": "sys.sysctl",
                "dbname": None,
                "size": 100,
            },
            {
                "path": "postgresql/configuration.tsv",
                "kind": "pg.settings",
                "dbname": None,
                "size": 100,
            },
        ],
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/assessment"
        )
    a = resp.json()["briefs"][0]
    assert a["category"] == "Host & OS"
    assert "system/proc/meminfo.out" in a["sources"]
    assert "system/sysctl.out" in a["sources"]
    # PG-only file must NOT leak into Host & OS sources.
    assert "postgresql/configuration.tsv" not in a["sources"]


@pytest.mark.asyncio
async def test_get_config_lists_providers(
    fresh_pool: AsyncConnectionPool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    names = {p["name"] for p in body["providers"]}
    assert {"claude", "gemini", "local", "openai"} <= names
    openai_entry = next(
        p for p in body["providers"] if p["name"] == "openai"
    )
    # Unavailable providers say why, so the UI renders the missing
    # env var rather than a bare disabled chip.
    assert openai_entry["available"] is False
    assert "OPENAI_API_KEY" in openai_entry["reason"]
    assert openai_entry["model"]
    assert "default" in body


@pytest.mark.asyncio
async def test_get_config_marks_openai_available_with_key(
    fresh_pool: AsyncConnectionPool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get("/api/config")
    openai_entry = next(
        p
        for p in resp.json()["providers"]
        if p["name"] == "openai"
    )
    assert openai_entry["available"] is True
    assert "reason" not in openai_entry


@pytest.mark.asyncio
async def test_assessment_lists_the_findings_behind_each_brief(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_upload_with_briefs(fresh_pool)
    await insert_brief(
        fresh_pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Replication",
        provider="mock",
        model="mock-v0",
        verdict="WARNING",
        markdown="**[WARNING]** a slot is inactive",
        prompt_tokens=None,
        completion_tokens=None,
    )
    await insert_findings(
        fresh_pool,
        upload_id=upload_id,
        category="Replication",
        findings=[
            Finding(
                rule_id="pg.replication.slot_inactive",
                severity="warning",
                title="A replication slot is inactive",
                detail="Drop it or reconnect its consumer.",
            )
        ],
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/assessment"
        )
    briefs = {b["category"]: b for b in resp.json()["briefs"]}
    assert briefs["Host & OS"]["findings"] == []
    assert briefs["Replication"]["findings"] == [
        {
            "rule_id": "pg.replication.slot_inactive",
            "severity": "warning",
            "title": "A replication slot is inactive",
            "detail": "Drop it or reconnect its consumer.",
        }
    ]
