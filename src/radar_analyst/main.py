"""Production entrypoint.

Builds the FastAPI app wired to real Postgres + blob store + LLM
provider based on environment variables. Used by ``python -m
radar_analyst`` (via ``__main__.py``) and by ``uvicorn
radar_analyst.main:build_production_app --factory``.

``RADAR_ANALYST_STATE_DB_URL`` names the PostgreSQL the analyst
keeps its own state in; every deployment supplies one. Everything
the analyst writes goes under the data directory described in
:mod:`radar_analyst.layout`.
"""

from __future__ import annotations

import ipaddress
import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from radar_analyst.ai import configured_provider, make
from radar_analyst.analyze.runner import JobRunner
from radar_analyst.blob.localfs import LocalFsStore
from radar_analyst.env import positive_int_env
from radar_analyst.layout import (
    admin_token_path,
    data_dir_from_env,
    ensure_admin_token,
    resolve_archive_dir,
)
from radar_analyst.server.app import create_app
from radar_analyst.store.db import (
    apply_migrations,
    check_encoding,
    create_pool,
)
from radar_analyst.store.jobs import fail_interrupted_jobs


# What a job left unfinished by the previous run reports as its
# error. The console shows it on the progress page and offers to
# assess the upload again.
INTERRUPTED_ERROR = (
    "the analyst stopped before this assessment finished"
)


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


def _resolve_admin_token() -> str | None:
    """Return the token that authorises deletes, or None to refuse.

    With nothing configured the analyst generates a token into its
    own data directory, so deletes work out of the box and still
    require authentication. If that directory cannot be written the
    route keeps failing closed rather than opening up.
    """
    configured = os.environ.get("RADAR_ANALYST_ADMIN_TOKEN") or None
    if configured:
        return configured
    path = admin_token_path(data_dir_from_env(os.environ))
    try:
        token = ensure_admin_token(path)
    except OSError as error:
        _logger.warning(
            "cannot write an admin token to %s (%s); DELETE "
            "/api/uploads will refuse with 503 until "
            "RADAR_ANALYST_ADMIN_TOKEN is set",
            path,
            error,
        )
        return None
    _logger.info("deletes are authorised by the token in %s", path)
    return token


def build_production_app() -> FastAPI:
    """Build the app wired from RADAR_ANALYST_* environment."""
    dsn = os.environ.get("RADAR_ANALYST_STATE_DB_URL")
    if not dsn:
        raise RuntimeError(
            "RADAR_ANALYST_STATE_DB_URL is required"
        )
    blob_dir = resolve_archive_dir(os.environ)
    blob_dir.mkdir(parents=True, exist_ok=True)
    # 500 MiB default: a radar zip heavy with per-database
    # time-series lands around 100–150 MiB compressed. Bump via
    # env for very large instances; shrink where uploads are
    # tightly bounded.
    max_upload = positive_int_env(
        "RADAR_ANALYST_MAX_UPLOAD_BYTES", 500 * 1024 * 1024
    )
    provider_name = configured_provider()
    admin_token = _resolve_admin_token()

    app = create_app(
        blob_store=LocalFsStore(data_dir=blob_dir),
        max_upload_bytes=max_upload,
        admin_token=admin_token,
    )

    @asynccontextmanager
    async def lifespan(
        _: FastAPI,
    ) -> AsyncGenerator[None, None]:
        """Open the pool, run migrations, and wire the job runner."""
        _logger.info("connecting to %s", dsn)
        pool = await create_pool(dsn)
        await check_encoding(pool)
        await apply_migrations(pool)
        # The task that ran such a job went with the previous
        # process, so nothing will ever finish it.
        interrupted = await fail_interrupted_jobs(
            pool, error=INTERRUPTED_ERROR
        )
        if interrupted:
            _logger.warning(
                "%d assessment(s) were interrupted by the previous "
                "stop and are marked failed; each can be assessed "
                "again from the console",
                interrupted,
            )
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

    try:
        logging.basicConfig(
            level=os.environ.get(
                "RADAR_ANALYST_LOG_LEVEL", "INFO"
            ).upper(),
            format=(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            ),
        )
    except ValueError as e:
        raise SystemExit(f"RADAR_ANALYST_LOG_LEVEL: {e}") from None
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
