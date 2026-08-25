"""Tests for the rule-engine base helpers."""

from typing import Any

from radar_analyst.rules.base import (
    REGISTRY,
    Finding,
    register,
    tier,
    top_n,
)


def test_register_stamps_category_on_returned_findings() -> None:
    @register("Test Category")
    def _rule(parsed: dict[str, Any]) -> list[Finding]:
        return [
            Finding(
                rule_id="t.x",
                severity="warning",
                title="t",
                detail="d",
            )
        ]

    try:
        out = _rule({})
        assert out[0].category == "Test Category"
    finally:
        REGISTRY.pop("Test Category", None)


def test_register_keeps_an_explicit_category() -> None:
    @register("Test Category")
    def _rule(parsed: dict[str, Any]) -> list[Finding]:
        return [
            Finding(
                rule_id="t.y",
                severity="info",
                title="t",
                detail="d",
                category="Elsewhere",
            )
        ]

    try:
        out = _rule({})
        assert out[0].category == "Elsewhere"
    finally:
        REGISTRY.pop("Test Category", None)


def test_tier_maps_thresholds() -> None:
    assert tier(5, warn=2, crit=4) == "critical"
    assert tier(4, warn=2, crit=4) == "critical"
    assert tier(3, warn=2, crit=4) == "warning"
    assert tier(2, warn=2, crit=4) == "warning"
    assert tier(1, warn=2, crit=4) is None


def test_top_n_renders_examples_and_suffix() -> None:
    examples, suffix = top_n(["a", "b", "c"], str, n=2)
    assert examples == "a; b"
    assert suffix == " (+1 more)"


def test_top_n_no_suffix_when_all_shown() -> None:
    examples, suffix = top_n(["a"], str)
    assert examples == "a"
    assert suffix == ""
