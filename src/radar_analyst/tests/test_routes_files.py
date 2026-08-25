"""Tests for /api/uploads/{id}/files inventory and downloads."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg_pool import AsyncConnectionPool

from radar_analyst.store.uploads import (
    insert_upload,
    set_archive_files,
)
from radar_analyst.tests.helpers import build_app


def _make_zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in entries.items():
            zf.writestr(path, data)
    return buf.getvalue()


async def _seed_upload_with_zip(
    pool: AsyncConnectionPool,
    blob_dir: Path,
    *,
    entries: dict[str, bytes],
) -> tuple[str, list[dict[str, Any]]]:
    """Create an upload row + write a real zip blob + persist
    the inventory snapshot. Returns (upload_id_str, inventory).
    """
    upload_id = uuid4()
    raw = _make_zip_bytes(entries)
    blob_dir.mkdir(parents=True, exist_ok=True)
    blob_path = blob_dir / f"{upload_id}.zip"
    blob_path.write_bytes(raw)
    storage_url = f"file://{blob_path.resolve()}"
    await insert_upload(
        pool,
        upload_id=upload_id,
        filename=f"{upload_id}.zip",
        storage_url=storage_url,
        size_bytes=len(raw),
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    inventory: list[dict[str, Any]] = [
        {
            "path": p,
            "kind": (
                "pg.settings"
                if p == "postgresql/configuration.tsv"
                else (
                    "sys.proc.meminfo"
                    if p == "system/proc/meminfo.out"
                    else None
                )
            ),
            "dbname": None,
            "size": len(data),
        }
        for p, data in entries.items()
    ]
    await set_archive_files(pool, upload_id, inventory)
    return str(upload_id), inventory


@pytest.mark.asyncio
async def test_list_files_returns_inventory(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    blob_dir = tmp_path / "blobs"
    upload_id, _ = await _seed_upload_with_zip(
        fresh_pool,
        blob_dir,
        entries={
            "postgresql/configuration.tsv": b"name\tsetting\n",
            "system/proc/meminfo.out": b"MemTotal: 1 kB\n",
            "weird/unknown.txt": b"x",
        },
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/uploads/{upload_id}/files")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    paths = {item["path"] for item in body["items"]}
    assert "postgresql/configuration.tsv" in paths
    assert "weird/unknown.txt" in paths
    cfg = next(
        i for i in body["items"]
        if i["path"] == "postgresql/configuration.tsv"
    )
    assert cfg["kind"] == "pg.settings"


@pytest.mark.asyncio
async def test_list_files_404_for_missing_upload(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get(f"/api/uploads/{uuid4()}/files")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_files_empty_when_inventory_unset(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    upload_id = uuid4()
    await insert_upload(
        fresh_pool,
        upload_id=upload_id,
        filename="r.zip",
        storage_url="file:///tmp/r.zip",
        size_bytes=1,
        sha256="0" * 64,
        hostname=None,
        archive_timestamp=None,
    )
    with TestClient(app) as client:
        resp = client.get(f"/api/uploads/{upload_id}/files")
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


@pytest.mark.asyncio
async def test_download_file_streams_content(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    blob_dir = tmp_path / "blobs"
    payload = b"name\tsetting\nfsync\ton\n"
    upload_id, _ = await _seed_upload_with_zip(
        fresh_pool,
        blob_dir,
        entries={"postgresql/configuration.tsv": payload},
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/files/"
            "postgresql/configuration.tsv"
        )
    assert resp.status_code == 200
    assert resp.content == payload
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd
    assert "configuration.tsv" in cd


@pytest.mark.asyncio
async def test_download_404_for_missing_upload(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{uuid4()}/files/anything.tsv"
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_404_for_path_not_in_inventory(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    blob_dir = tmp_path / "blobs"
    upload_id, _ = await _seed_upload_with_zip(
        fresh_pool,
        blob_dir,
        entries={"postgresql/configuration.tsv": b"x"},
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/files/"
            "postgresql/secret.tsv"
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_rejects_path_traversal_attempt(
    fresh_pool: AsyncConnectionPool, tmp_path: Path
) -> None:
    app, _ = await build_app(fresh_pool, tmp_path)
    blob_dir = tmp_path / "blobs"
    upload_id, _ = await _seed_upload_with_zip(
        fresh_pool,
        blob_dir,
        entries={"postgresql/configuration.tsv": b"x"},
    )
    with TestClient(app) as client:
        resp = client.get(
            f"/api/uploads/{upload_id}/files/"
            "../../etc/passwd"
        )
    # The whitelist check makes this a plain 404: the path
    # isn't in the upload's inventory.
    assert resp.status_code == 404
