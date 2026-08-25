"""Tests for the local-filesystem blob store."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from radar_analyst.blob.localfs import LocalFsStore


async def _gen(chunks: list[bytes]):  # type: ignore[no-untyped-def]
    for c in chunks:
        yield c


async def test_put_writes_file_and_returns_url_size_sha256(
    tmp_path: Path,
) -> None:
    store = LocalFsStore(data_dir=tmp_path)
    result = await store.put(
        "upload-1.zip", _gen([b"hello ", b"world"])
    )
    assert result.size == 11
    assert result.sha256 == (
        "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
    assert result.url.startswith("file://")
    assert Path(result.url.removeprefix("file://")).exists()


async def test_get_streams_back_same_bytes(tmp_path: Path) -> None:
    store = LocalFsStore(data_dir=tmp_path)
    result = await store.put(
        "upload-1.zip", _gen([b"a" * 10_000, b"b" * 10_000])
    )
    chunks: list[bytes] = []
    async for c in store.get(result.url):
        chunks.append(c)
    assert b"".join(chunks) == b"a" * 10_000 + b"b" * 10_000


async def test_delete_removes_the_file(tmp_path: Path) -> None:
    store = LocalFsStore(data_dir=tmp_path)
    result = await store.put("upload-1.zip", _gen([b"x"]))
    path = Path(result.url.removeprefix("file://"))
    assert path.exists()
    await store.delete(result.url)
    assert not path.exists()


async def test_get_missing_url_raises_filenotfounderror(
    tmp_path: Path,
) -> None:
    store = LocalFsStore(data_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        async for _ in store.get(
            f"file://{tmp_path}/does-not-exist.zip"
        ):
            pass


# ---------------------------------------------------------------
# _path_from_url: defense-in-depth boundary check
# ---------------------------------------------------------------


async def test_get_rejects_path_outside_data_dir(
    tmp_path: Path,
) -> None:
    # Defence-in-depth: even if a future bug or compromised DB
    # row plants a file:// URL pointing outside the configured
    # data dir, the store must refuse to read it.
    store = LocalFsStore(data_dir=tmp_path / "blobs")
    with pytest.raises(PermissionError):
        async for _ in store.get("file:///etc/passwd"):
            pass


async def test_delete_rejects_path_outside_data_dir(
    tmp_path: Path,
) -> None:
    # Same containment for delete: without this guard, a planted
    # URL like file:///etc/hosts would be unlinked when the
    # corresponding upload row is deleted.
    target = tmp_path / "outside.txt"
    target.write_text("must not be removed")
    store = LocalFsStore(data_dir=tmp_path / "blobs")
    with pytest.raises(PermissionError):
        await store.delete(f"file://{target}")
    assert target.exists()


async def test_get_rejects_dotdot_traversal(
    tmp_path: Path,
) -> None:
    data = tmp_path / "blobs"
    data.mkdir()
    sibling = tmp_path / "sibling.txt"
    sibling.write_text("nope")
    store = LocalFsStore(data_dir=data)
    with pytest.raises(PermissionError):
        async for _ in store.get(
            f"file://{data}/../sibling.txt"
        ):
            pass


# ---------------------------------------------------------------
# put: partial-file cleanup on stream failure
# ---------------------------------------------------------------


async def _failing_stream() -> AsyncIterator[bytes]:
    yield b"some bytes"
    raise RuntimeError("client went away")


async def test_put_removes_partial_file_when_stream_raises(
    tmp_path: Path,
) -> None:
    # If the chunk iterator raises (client disconnect, 413
    # mid-upload, network error), the partial file must not be
    # left on disk: otherwise repeated failed uploads slowly
    # leak storage with no DB row to track them.
    store = LocalFsStore(data_dir=tmp_path)
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(RuntimeError):
        await store.put("partial.zip", _failing_stream())
    after = sorted(tmp_path.rglob("*"))
    leaked = [p for p in after if p not in before and p.is_file()]
    assert leaked == [], leaked


async def test_download_to_temp_streams_blob_to_file(
    tmp_path: Path,
) -> None:
    from radar_analyst.blob.base import download_to_temp

    store = LocalFsStore(data_dir=tmp_path)

    async def _chunks() -> AsyncIterator[bytes]:
        yield b"abc"
        yield b"def"

    result = await store.put("k.zip", _chunks())
    out = await download_to_temp(store, result.url)
    try:
        assert out.read_bytes() == b"abcdef"
    finally:
        out.unlink(missing_ok=True)


async def test_download_to_temp_cleans_up_on_error(
    tmp_path: Path,
) -> None:
    from radar_analyst.blob.base import download_to_temp

    store = LocalFsStore(data_dir=tmp_path)
    with pytest.raises(FileNotFoundError):
        await download_to_temp(
            store, f"file://{tmp_path}/missing.zip"
        )
