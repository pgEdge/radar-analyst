"""What the entrypoint does with a setting that it cannot use."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import radar_analyst.main as main_mod


def test_an_unusable_upload_limit_gives_the_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A limit of zero would refuse every upload.
    monkeypatch.setenv("RADAR_ANALYST_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RADAR_ANALYST_BLOB_DIR", raising=False)
    monkeypatch.setenv(
        "RADAR_ANALYST_STATE_DB_URL", "postgresql://elsewhere/radar_analyst"
    )
    monkeypatch.setenv("RADAR_ANALYST_MAX_UPLOAD_BYTES", "0")
    with caplog.at_level(logging.WARNING):
        app = main_mod.build_production_app()
    assert app.state.max_upload_bytes == 500 * 1024 * 1024
    assert "RADAR_ANALYST_MAX_UPLOAD_BYTES" in caplog.text


def test_an_unknown_log_level_stops_with_a_one_line_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(app: str, **kw: object) -> None:
        raise AssertionError("must not start the server")

    # A fresh process has no handlers on the root logger, and only
    # then does logging.basicConfig apply the level at all.
    monkeypatch.setattr(logging.root, "handlers", [])
    monkeypatch.setenv("RADAR_ANALYST_LOG_LEVEL", "loud")
    monkeypatch.setattr("uvicorn.run", fake_run)
    with pytest.raises(SystemExit) as stopped:
        main_mod.main()
    assert "RADAR_ANALYST_LOG_LEVEL" in str(stopped.value)


def test_an_empty_log_level_gives_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    def fake_run(app: str, **kw: object) -> None:
        started.append(app)

    monkeypatch.setattr(logging.root, "handlers", [])
    monkeypatch.setattr(logging.root, "level", logging.root.level)
    monkeypatch.setenv("RADAR_ANALYST_LOG_LEVEL", "")
    monkeypatch.delenv("RADAR_ANALYST_LISTEN", raising=False)
    monkeypatch.setattr("uvicorn.run", fake_run)
    main_mod.main()
    assert started
    assert logging.root.level == logging.INFO
