"""Tests for listen-address parsing.

The analyst is a local tool. Anything that is not an explicit,
deliberate request to bind wider must land on the loopback
interface, and a typo must stop the process rather than open a
port nobody expected.
"""

from __future__ import annotations

import pytest

from radar_analyst.main import is_loopback, parse_listen


def test_empty_value_binds_loopback() -> None:
    assert parse_listen("") == ("127.0.0.1", 8080)


def test_bare_colon_port_binds_loopback() -> None:
    """`:8080` means "port 8080", not "every interface"."""
    assert parse_listen(":8080") == ("127.0.0.1", 8080)


def test_bare_port_binds_loopback() -> None:
    assert parse_listen("9000") == ("127.0.0.1", 9000)


def test_explicit_host_is_honoured() -> None:
    assert parse_listen("127.0.0.1:9000") == (
        "127.0.0.1",
        9000,
    )
    assert parse_listen("localhost:8081") == (
        "localhost",
        8081,
    )


def test_explicit_wildcard_is_honoured() -> None:
    """Binding wide stays possible, but only when asked for."""
    assert parse_listen("0.0.0.0:8080") == ("0.0.0.0", 8080)


def test_bracketed_ipv6_host() -> None:
    assert parse_listen("[::1]:8080") == ("::1", 8080)
    assert parse_listen("[::]:8080") == ("::", 8080)


@pytest.mark.parametrize(
    "value",
    [
        "127.0.0.1:",
        "127.0.0.1:notaport",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:-1",
        ":",
        "[::1]",
    ],
)
def test_malformed_value_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        parse_listen(value)


def test_is_loopback() -> None:
    assert is_loopback("127.0.0.1")
    assert is_loopback("127.1.2.3")
    assert is_loopback("::1")
    assert is_loopback("localhost")
    assert is_loopback("LocalHost")
    assert not is_loopback("0.0.0.0")
    assert not is_loopback("::")
    assert not is_loopback("192.168.1.10")
    assert not is_loopback("example.com")


def test_main_binds_loopback_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entrypoint must not open a port to the network."""
    import radar_analyst.main as main_mod

    captured: dict[str, object] = {}

    def fake_run(app: str, **kw: object) -> None:
        captured.update(kw)

    monkeypatch.delenv("RADAR_ANALYST_LISTEN", raising=False)
    monkeypatch.setattr("uvicorn.run", fake_run)
    main_mod.main()
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8080


def test_main_rejects_a_malformed_listen_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo stops the process instead of opening a stray port."""
    import radar_analyst.main as main_mod

    def fake_run(app: str, **kw: object) -> None:
        raise AssertionError("must not start the server")

    monkeypatch.setenv("RADAR_ANALYST_LISTEN", "127.0.0.1:nope")
    monkeypatch.setattr("uvicorn.run", fake_run)
    with pytest.raises(SystemExit):
        main_mod.main()
