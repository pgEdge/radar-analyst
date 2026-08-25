"""Production entrypoint.

Builds the FastAPI app wired to real Postgres + blob store + LLM
provider based on environment variables. Used by ``python -m
radar_analyst`` (via ``__main__.py``) and by ``uvicorn
radar_analyst.main:build_production_app --factory``.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI

from radar_analyst.ai import DEFAULT_PROVIDER, make
from radar_analyst.analyze.runner import JobRunner
from radar_analyst.blob.localfs import LocalFsStore
from radar_analyst.server.app import create_app
from radar_analyst.store.db import apply_migrations, create_pool

_logger = logging.getLogger(__name__)


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_LISTEN = f"{LOOPBACK_HOST}:8080"


def is_loopback(host: str) -> bool:
    """Report whether *host* can only be reached from this machine."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_listen(value: str) -> tuple[str, int]:
    """Split a ``[host:]port`` listen spec into ``(host, port)``.

    An omitted host means the loopback interface, so the analyst
    stays a local tool unless an address is named on purpose. A
    malformed spec raises ``ValueError`` rather than falling back to
    a default, because silently listening somewhere other than what
    was configured is worse than refusing to start.
    """
    spec = value.strip() or DEFAULT_LISTEN
    if spec.startswith("["):
        host, sep, port_s = spec.partition("]")
        host = host[1:]
        if not sep or not port_s.startswith(":"):
            raise ValueError(
                f"invalid listen address {value!r}: "
                "bracketed IPv6 host needs a :port suffix"
            )
        port_s = port_s[1:]
    elif ":" in spec:
        host, _, port_s = spec.rpartition(":")
    else:
        host, port_s = "", spec

    try:
        port = int(port_s)
    except ValueError:
        raise ValueError(
            f"invalid listen address {value!r}: "
            f"{port_s!r} is not a port number"
        ) from None
    if not 1 <= port <= 65535:
        raise ValueError(
            f"invalid listen address {value!r}: "
            f"port {port} is outside 1-65535"
        )
    return host or LOOPBACK_HOST, port


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        _logger.warning(
            "invalid %s=%r, using default %d", name, raw, default
        )
        return default


def build_production_app() -> FastAPI:
    """Build the app wired from RADAR_ANALYST_* environment."""
    dsn = os.environ.get("RADAR_ANALYST_STATE_DB_URL")
    if not dsn:
        raise RuntimeError(
            "RADAR_ANALYST_STATE_DB_URL is required"
        )
    blob_dir = Path(
        os.environ.get("RADAR_ANALYST_BLOB_DIR", "./data/blobs")
    )
    blob_dir.mkdir(parents=True, exist_ok=True)
    # 500 MiB default: a radar zip heavy with per-database
    # time-series lands around 100–150 MiB compressed. Bump via
    # env for very large instances; shrink where uploads are
    # tightly bounded.
    max_upload = _int_env(
        "RADAR_ANALYST_MAX_UPLOAD_BYTES", 500 * 1024 * 1024
    )
    provider_name = os.environ.get(
        "RADAR_ANALYST_AI_PROVIDER", DEFAULT_PROVIDER
    )
    admin_token = os.environ.get("RADAR_ANALYST_ADMIN_TOKEN") or None
    if not admin_token:
        _logger.warning(
            "RADAR_ANALYST_ADMIN_TOKEN is unset; DELETE /api/uploads "
            "will refuse with 503 until it is configured"
        )

    app = create_app(
        blob_store=LocalFsStore(data_dir=blob_dir),
        max_upload_bytes=max_upload,
        admin_token=admin_token,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Open the pool, run migrations, and wire the job runner."""
        _logger.info("connecting to %s", dsn)
        pool = await create_pool(dsn)
        await apply_migrations(pool)
        app.state.pool = pool
        analyzer = make(provider_name)
        _logger.info(
            "AI provider: %s (%s)",
            analyzer.name,
            analyzer.model,
        )
        app.state.job_runner = JobRunner(
            pool=pool,
            blob_store=app.state.blob_store,
            analyzer=analyzer,
            hub=app.state.sse_hub,
        )
        try:
            yield
        finally:
            await pool.close()

    # Attach lifespan to the router so uvicorn picks it up on startup.
    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    """CLI entry: configure logging and serve the listen address."""
    import uvicorn

    logging.basicConfig(
        level=os.environ.get(
            "RADAR_ANALYST_LOG_LEVEL", "INFO"
        ).upper(),
        format=(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ),
    )
    try:
        host, port = parse_listen(
            os.environ.get("RADAR_ANALYST_LISTEN", "")
        )
    except ValueError as e:
        raise SystemExit(f"RADAR_ANALYST_LISTEN: {e}") from None

    if not is_loopback(host):
        _logger.warning(
            "listening on %s, which is reachable from other "
            "hosts. The analyst is meant to run locally: bind "
            "%s instead, or restrict access at the network "
            "layer (docker-compose publishes the port on host "
            "loopback only).",
            host,
            DEFAULT_LISTEN,
        )

    _logger.info("console + API on http://%s:%d/", host, port)
    uvicorn.run(
        "radar_analyst.main:build_production_app",
        factory=True,
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
