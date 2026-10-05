"""Tests for POST /api/uploads."""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from radar_analyst.blob.base import BlobStore, PutResult
from radar_analyst.blob.localfs import LocalFsStore
from radar_analyst.rules.base import Finding
from radar_analyst.server.app import create_app
from radar_analyst.store.briefs import insert_brief, list_briefs
from radar_analyst.store.db import apply_migrations
from radar_analyst.store.findings import insert_findings, list_findings
from radar_analyst.store.jobs import get_job, insert_job
from radar_analyst.store.uploads import get_upload, insert_upload
from radar_analyst.tests.helpers import build_app


def _zip_bytes(payload: bytes = b"x") -> bytes:
    """Minimal in-memory zip; uploads must pass the magic check."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("radar.out", payload)
    return buf.getvalue()


async def test_post_upload_returns_upload_and_job_ids(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={
                "file": ("radar.zip", io.BytesIO(_zip_bytes()))
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert UUID(body["upload_id"])
    assert UUID(body["job_id"])


async def test_post_upload_writes_to_blob_store(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, store = await build_app(fresh_pool, tmp_path)
    payload = _zip_bytes(b"radar zipfile content")
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={"file": ("radar.zip", io.BytesIO(payload))},
        )
    assert resp.status_code == 201
    upload_id = UUID(resp.json()["upload_id"])
    row = await get_upload(fresh_pool, upload_id)
    assert row is not None
    assert row.size_bytes == len(payload)
    chunks = [c async for c in store.get(row.storage_url)]
    assert b"".join(chunks) == payload


async def test_post_upload_inserts_queued_job(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={
                "file": ("radar.zip", io.BytesIO(_zip_bytes()))
            },
        )
    job_id = UUID(resp.json()["job_id"])
    job = await get_job(fresh_pool, job_id)
    assert job is not None
    assert job.state == "queued"


async def test_post_upload_rejects_over_size_limit(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(
        fresh_pool, tmp_path, max_upload_bytes=10
    )
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={
                "file": (
                    "radar.zip",
                    io.BytesIO(_zip_bytes(b"x" * 100)),
                )
            },
        )
    assert resp.status_code == 413


async def test_post_upload_rejects_non_zip_with_415(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={"file": ("radar.zip", io.BytesIO(b"payload"))},
        )
    assert resp.status_code == 415
    assert "zip" in resp.json()["detail"].lower()
    leftovers = [
        p for p in tmp_path.rglob("*") if p.is_file()
    ]
    assert leftovers == []


async def test_post_upload_rejects_empty_file_with_415(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={"file": ("radar.zip", io.BytesIO(b""))},
        )
    assert resp.status_code == 415


async def test_post_upload_rejects_missing_file(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post("/api/uploads")
    assert resp.status_code == 422


async def test_post_upload_deletes_blob_when_insert_upload_fails(
    fresh_pool: AsyncConnectionPool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If the DB insert fails after the blob has been written,
    # the blob must be cleaned up: otherwise every transient
    # DB error leaks a file with no tracking row.
    app, _store = await build_app(fresh_pool, tmp_path)

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(
        "radar_analyst.server.routes_uploads.insert_upload", _boom
    )
    before = sorted(Path(tmp_path).rglob("*.zip"))
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/api/uploads",
            files={
                "file": ("radar.zip", io.BytesIO(_zip_bytes()))
            },
        )
    assert resp.status_code == 500
    after = sorted(Path(tmp_path).rglob("*.zip"))
    leaked = [p for p in after if p not in before]
    assert leaked == [], leaked


# ---------------------------------------------------------------
# DELETE /api/uploads/{id}: auth gate
# ---------------------------------------------------------------

async def _seed_upload(
    pool: AsyncConnectionPool, store: LocalFsStore
) -> UUID:
    """Insert one upload row + a tiny blob so DELETE has a target."""
    uid = uuid4()
    key = f"{uid}.zip"

    async def _chunks() -> AsyncIterator[bytes]:
        yield b"payload"

    result = await store.put(key, _chunks())
    await insert_upload(
        pool,
        upload_id=uid,
        filename="radar.zip",
        storage_url=result.url,
        size_bytes=result.size,
        sha256=result.sha256,
        hostname=None,
        archive_timestamp=None,
    )
    return uid


async def test_delete_without_auth_header_returns_401(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, store = await build_app(
        fresh_pool, tmp_path, admin_token="s3cret"
    )
    uid = await _seed_upload(fresh_pool, store)
    with TestClient(app) as client:
        resp = client.delete(f"/api/uploads/{uid}")
    assert resp.status_code == 401


async def test_delete_with_wrong_token_returns_401(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, store = await build_app(
        fresh_pool, tmp_path, admin_token="s3cret"
    )
    uid = await _seed_upload(fresh_pool, store)
    with TestClient(app) as client:
        resp = client.delete(
            f"/api/uploads/{uid}",
            headers={"Authorization": "Bearer wrong"},
        )
    assert resp.status_code == 401


async def test_delete_with_non_ascii_token_returns_401_not_500(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    # hmac.compare_digest on str rejects non-ASCII with TypeError;
    # the dependency must encode to bytes so a hostile or sloppy
    # client can't flip a 401 into a 500. httpx itself refuses to
    # encode non-ASCII into a header, so we send the raw bytes
    # via the latin-1-tolerant bytes header path.
    app, store = await build_app(
        fresh_pool, tmp_path, admin_token="s3cret"
    )
    uid = await _seed_upload(fresh_pool, store)
    with TestClient(app) as client:
        # latin-1 keeps the header valid bytes-wise while still
        # carrying a non-ASCII codepoint into the server.
        raw_value: bytes = "Bearer invalid_ñ".encode("latin-1")
        resp = client.delete(
            f"/api/uploads/{uid}",
            headers=[(b"Authorization", raw_value)],
        )
    assert resp.status_code == 401


async def test_delete_with_correct_token_returns_204(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, store = await build_app(
        fresh_pool, tmp_path, admin_token="s3cret"
    )
    uid = await _seed_upload(fresh_pool, store)
    with TestClient(app) as client:
        resp = client.delete(
            f"/api/uploads/{uid}",
            headers={"Authorization": "Bearer s3cret"},
        )
    assert resp.status_code == 204
    assert await get_upload(fresh_pool, uid) is None


async def test_delete_when_token_unconfigured_returns_503(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    # Fail-closed: if the operator did not set RADAR_ANALYST_ADMIN_TOKEN,
    # DELETE refuses entirely instead of being silently open.
    app, store = await build_app(
        fresh_pool, tmp_path, admin_token=None
    )
    uid = await _seed_upload(fresh_pool, store)
    with TestClient(app) as client:
        resp = client.delete(
            f"/api/uploads/{uid}",
            headers={"Authorization": "Bearer anything"},
        )
    assert resp.status_code == 503


# ---------------------------------------------------------------
# DELETE: blob delete swallow logging
# ---------------------------------------------------------------

class _FailingDeleteStore:
    """LocalFsStore-equivalent put/get; delete raises a chosen error."""

    def __init__(
        self, base: LocalFsStore, exc: BaseException
    ) -> None:
        self._base = base
        self._exc = exc

    async def put(
        self, key: str, chunks: AsyncIterator[bytes]
    ) -> PutResult:
        return await self._base.put(key, chunks)

    def get(self, url: str) -> AsyncIterator[bytes]:
        return self._base.get(url)

    async def delete(self, url: str) -> None:
        raise self._exc


async def test_delete_logs_warning_on_unexpected_blob_error(
    fresh_pool: AsyncConnectionPool,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await apply_migrations(fresh_pool)
    base_store = LocalFsStore(data_dir=tmp_path)
    failing = _FailingDeleteStore(
        base_store, PermissionError("denied")
    )
    assert isinstance(failing, BlobStore)
    app = create_app(
        pool=fresh_pool,
        blob_store=failing,
        admin_token="s3cret",
    )
    uid = await _seed_upload(fresh_pool, base_store)
    with caplog.at_level(
        logging.WARNING, logger="radar_analyst.server.routes_uploads"
    ), TestClient(app) as client:
        resp = client.delete(
            f"/api/uploads/{uid}",
            headers={"Authorization": "Bearer s3cret"},
        )
    assert resp.status_code == 204
    # DB row gone even though blob delete failed.
    assert await get_upload(fresh_pool, uid) is None
    # Operator gets a log line that names the upload + cause.
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        str(uid) in m and "denied" in m for m in msgs
    ), msgs


async def test_delete_silent_on_blob_already_missing(
    fresh_pool: AsyncConnectionPool,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await apply_migrations(fresh_pool)
    base_store = LocalFsStore(data_dir=tmp_path)
    failing = _FailingDeleteStore(
        base_store, FileNotFoundError("gone")
    )
    app = create_app(
        pool=fresh_pool,
        blob_store=failing,
        admin_token="s3cret",
    )
    uid = await _seed_upload(fresh_pool, base_store)
    with caplog.at_level(
        logging.WARNING, logger="radar_analyst.server.routes_uploads"
    ), TestClient(app) as client:
        resp = client.delete(
            f"/api/uploads/{uid}",
            headers={"Authorization": "Bearer s3cret"},
        )
    assert resp.status_code == 204
    # No warning for the already-gone case: that's expected state.
    assert caplog.records == []


async def test_post_upload_reads_host_and_time_from_the_filename(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={
                "file": (
                    "radar-db1-20260903-164450.zip",
                    io.BytesIO(_zip_bytes()),
                )
            },
        )
        assert resp.status_code == 201, resp.text
        shown = client.get(f"/api/uploads/{resp.json()['upload_id']}")
    body = shown.json()
    assert body["hostname"] == "db1"
    # The host's own clock, which the name gives without a zone.
    assert body["archive_timestamp"] == "2026-09-03T16:44:50"


async def test_post_upload_with_another_name_leaves_host_unknown(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/uploads",
            files={"file": ("archive.zip", io.BytesIO(_zip_bytes()))},
        )
        shown = client.get(f"/api/uploads/{resp.json()['upload_id']}")
    assert shown.json()["hostname"] is None
    assert shown.json()["archive_timestamp"] is None


async def test_list_carries_the_verdict_and_the_job_state(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, store = await build_app(fresh_pool, tmp_path)
    assessed = await _seed_upload(fresh_pool, store)
    await insert_job(
        fresh_pool, job_id=uuid4(), upload_id=assessed, ai_provider="mock"
    )
    for category, verdict in (
        ("Host & OS", "HEALTHY"),
        ("PostgreSQL Configuration", "WARNING"),
    ):
        await insert_brief(
            fresh_pool,
            brief_id=uuid4(),
            upload_id=assessed,
            category=category,
            provider="mock",
            model="mock-v0",
            verdict=verdict,
            markdown="x",
            prompt_tokens=None,
            completion_tokens=None,
        )
    bare = await _seed_upload(fresh_pool, store)

    with TestClient(app) as client:
        items = client.get("/api/uploads").json()["items"]

    by_id = {item["id"]: item for item in items}
    assert by_id[str(assessed)]["verdict"] == "WARNING"
    assert by_id[str(assessed)]["state"] == "queued"
    assert by_id[str(bare)]["verdict"] is None
    assert by_id[str(bare)]["state"] is None


async def _seed_assessed_upload(
    pool: AsyncConnectionPool, *, job_state: str = "done"
) -> UUID:
    """An upload with a job, one brief, and one finding."""
    upload_id = uuid4()
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename="radar-db01-20260401-120000.zip",
        storage_url=f"file:///tmp/{upload_id}.zip",
        size_bytes=1024,
        sha256="d" * 64,
        hostname="db01",
        archive_timestamp=None,
    )
    await insert_job(
        pool,
        job_id=uuid4(),
        upload_id=upload_id,
        ai_provider="mock",
        state=job_state,
    )
    await insert_brief(
        pool,
        brief_id=uuid4(),
        upload_id=upload_id,
        category="Host & OS",
        provider="mock",
        model="mock-v0",
        verdict="WARNING",
        markdown="**[WARNING]** swap",
        prompt_tokens=None,
        completion_tokens=None,
    )
    await insert_findings(
        pool,
        upload_id=upload_id,
        category="Host & OS",
        findings=[
            Finding(
                rule_id="host.swap_configured",
                severity="warning",
                title="Swap is configured",
                detail="Disable swap on a database host.",
            )
        ],
    )
    return upload_id


async def test_assess_again_starts_a_new_job_and_clears_the_result(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_assessed_upload(fresh_pool)
    with TestClient(app) as client:
        resp = client.post(f"/api/uploads/{upload_id}/assess")
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["upload_id"] == str(upload_id)
    job = await get_job(fresh_pool, UUID(body["job_id"]))
    assert job is not None
    assert job.state == "queued"
    assert await list_briefs(fresh_pool, upload_id) == []
    assert await list_findings(fresh_pool, upload_id) == []


async def test_assess_again_refuses_while_an_assessment_runs(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = await _seed_assessed_upload(
        fresh_pool, job_state="parsing"
    )
    with TestClient(app) as client:
        resp = client.post(f"/api/uploads/{upload_id}/assess")
    assert resp.status_code == 409
    assert len(await list_briefs(fresh_pool, upload_id)) == 1


async def test_assess_again_of_an_unknown_upload_is_404(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.post(f"/api/uploads/{uuid4()}/assess")
    assert resp.status_code == 404
