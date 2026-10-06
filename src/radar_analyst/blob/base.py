"""Blob-store abstraction.

Storage is addressed by an opaque ``storage_url``, so the database
schema is independent of which :class:`BlobStore` implementation
holds the bytes.
"""

import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class PutResult:
    """Where a stored blob lives: URL, size, and sha256."""
    url: str
    size: int
    sha256: str


@runtime_checkable
class BlobStore(Protocol):
    """Protocol every blob backend implements."""
    async def put(
        self, key: str, chunks: AsyncIterator[bytes]
    ) -> PutResult:
        """Store *chunks* under *key* and describe the result."""
        ...

    def get(self, url: str) -> AsyncIterator[bytes]:
        """Stream the blob at *url* in chunks."""
        ...

    async def delete(self, url: str) -> None:
        """Remove the blob at *url*."""
        ...


async def download_to_temp(
    store: BlobStore, url: str, *, suffix: str = ".zip"
) -> Path:
    """Stream a blob into a named tempfile and return its path.

    The caller owns the file and must unlink it. On a failed
    download the tempfile is removed before the error propagates,
    so an aborted stream cannot leak files.
    """
    # Not a context manager: the caller owns the file after this
    # returns, so it must outlive the handle that made it.
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115
        suffix=suffix, delete=False
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    try:
        with tmp_path.open("wb") as fh:
            async for chunk in store.get(url):
                fh.write(chunk)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path
