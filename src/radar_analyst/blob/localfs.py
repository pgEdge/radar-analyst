"""Local-filesystem blob store.

Files land under ``{data_dir}/{YYYY}/{MM}/{DD}/{key}`` and are addressed
by ``file://`` URLs. Computes sha256 + size in a single streaming pass
during ``put``.
"""

import hashlib
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

from radar_analyst.blob.base import PutResult


class LocalFsStore:
    """BlobStore over a local directory tree.

    Files land under ``{data_dir}/{YYYY}/{MM}/{DD}/{key}``,
    addressed by ``file://`` URLs; reads refuse any path that
    resolves outside the data directory.
    """

    # Chunk size used when streaming bytes back out of the store.
    _GET_CHUNK = 64 * 1024

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        now = datetime.now(tz=timezone.utc)
        sub = self._data_dir / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        sub.mkdir(parents=True, exist_ok=True)
        return sub / key

    def _path_from_url(self, url: str) -> Path:
        if not url.startswith("file://"):
            raise ValueError(f"not a file:// URL: {url!r}")
        # Defence-in-depth: URLs are server-generated today, but
        # if a future bug or compromised DB row points the URL
        # outside the configured data root, refuse rather than
        # leaking a read or unlinking an unrelated file. resolve()
        # collapses ``..`` and follows symlinks before the check.
        path = Path(url.removeprefix("file://")).resolve()
        root = self._data_dir.resolve()
        if not path.is_relative_to(root):
            raise PermissionError(
                f"path escapes data directory: {url!r}"
            )
        return path

    async def put(
        self, key: str, chunks: AsyncIterator[bytes]
    ) -> PutResult:
        """Write *chunks* under the data dir, hashing while streaming."""
        path = self._path_for(key)
        hasher = hashlib.sha256()
        size = 0
        try:
            with path.open("wb") as fh:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    fh.write(chunk)
                    hasher.update(chunk)
                    size += len(chunk)
        except BaseException:
            # Client disconnect, 413 mid-stream, network error,
            # cancellation: any of these would otherwise leave a
            # partial file on disk with no DB row to track it,
            # which a malicious client can exploit to fill the
            # volume by repeatedly aborting uploads.
            path.unlink(missing_ok=True)
            raise
        return PutResult(
            url=f"file://{path.resolve()}",
            size=size,
            sha256=hasher.hexdigest(),
        )

    async def get(self, url: str) -> AsyncIterator[bytes]:
        """Stream a stored file in chunks."""
        path = self._path_from_url(url)
        if not path.exists():
            raise FileNotFoundError(path)
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(self._GET_CHUNK)
                if not chunk:
                    break
                yield chunk

    async def delete(self, url: str) -> None:
        """Unlink the stored file, refusing paths outside the root."""
        path = self._path_from_url(url)
        path.unlink(missing_ok=True)
