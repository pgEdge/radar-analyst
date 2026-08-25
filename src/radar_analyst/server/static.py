"""Static-file mount for the Astro-built GUI.

The Astro build lands in ``web/dist/``. For development we read it
straight from there; for packaged installs we look under
``src/radar_analyst/webdist/`` (populated by the hatchling build hook).

The mount is attached as a catch-all AFTER the API routes are
registered, so ``/api/*`` continues to hit FastAPI handlers.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Candidate locations, in priority order:
# 1. Packaged assets copied into the wheel by the hatchling hook.
# 2. The sibling web/dist produced by `npm run build` during dev.
_CANDIDATES: tuple[Path, ...] = (
    Path(__file__).resolve().parent.parent / "webdist",
    Path(__file__).resolve().parent.parent.parent.parent
    / "web"
    / "dist",
)


def find_static_dir() -> Path | None:
    """Return the first existing static-assets directory, or None."""
    for c in _CANDIDATES:
        if c.is_dir() and (c / "index.html").is_file():
            return c
    return None


def mount_static(app: FastAPI) -> bool:
    """Attach the static GUI if a build is present.

    Returns True if mounted, False if no build was found (the service
    still runs: the API endpoints are the contract; the GUI is
    optional).
    """
    path = find_static_dir()
    if path is None:
        return False
    # html=True makes StaticFiles serve index.html for directory URLs
    # like /upload/ and /live/, matching Astro's directory output.
    app.mount(
        "/",
        StaticFiles(directory=str(path), html=True),
        name="static",
    )
    return True
