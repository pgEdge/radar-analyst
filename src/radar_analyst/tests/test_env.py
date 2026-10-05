"""Tests for reading a positive integer setting from the environment."""

from __future__ import annotations

import logging

import pytest

from radar_analyst.env import positive_int_env


_NAME = "RADAR_ANALYST_TEST_SETTING"


@pytest.mark.parametrize("raw", [None, ""])
def test_an_unset_or_empty_variable_gives_the_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raw: str | None,
) -> None:
    if raw is None:
        monkeypatch.delenv(_NAME, raising=False)
    else:
        monkeypatch.setenv(_NAME, raw)
    assert positive_int_env(_NAME, 3) == 3
    assert caplog.text == ""


def test_a_positive_integer_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_NAME, "5")
    assert positive_int_env(_NAME, 3) == 5


@pytest.mark.parametrize("raw", ["0", "-2", "1.5", "three"])
def test_any_other_value_warns_and_gives_the_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raw: str,
) -> None:
    monkeypatch.setenv(_NAME, raw)
    with caplog.at_level(logging.WARNING):
        assert positive_int_env(_NAME, 3) == 3
    assert _NAME in caplog.text
