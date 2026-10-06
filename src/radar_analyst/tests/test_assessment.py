"""Tests for the assessment roll-up verdict."""

from radar_analyst.analyze.assessment import rollup_verdict
from radar_analyst.rules.base import (
    apply_finding_floor,
    rank_to_verdict,
    severity_rank,
)


def test_rollup_of_no_briefs_is_none() -> None:
    assert rollup_verdict([]) is None


def test_rollup_of_all_healthy_is_healthy() -> None:
    assert (
        rollup_verdict(["HEALTHY", "HEALTHY"]) == "HEALTHY"
    )


def test_rollup_takes_the_worst_verdict() -> None:
    assert (
        rollup_verdict(["HEALTHY", "WARNING", "HEALTHY"])
        == "WARNING"
    )
    assert (
        rollup_verdict(["WARNING", "CRITICAL", "HEALTHY"])
        == "CRITICAL"
    )


def test_rollup_ignores_unknown_and_missing() -> None:
    """UNKNOWN means no data collected, not a problem found.

    A category the archive carries nothing for cannot make the
    assessment worse than the categories it does cover.
    """
    assert (
        rollup_verdict(["UNKNOWN", None, "HEALTHY"])
        == "HEALTHY"
    )
    assert (
        rollup_verdict(["UNKNOWN", "WARNING"]) == "WARNING"
    )


def test_rollup_of_only_unknown_is_unknown() -> None:
    """Nothing was collected, so nothing can be concluded."""
    assert rollup_verdict(["UNKNOWN"]) == "UNKNOWN"
    assert rollup_verdict([None, "UNKNOWN"]) == "UNKNOWN"


def test_info_severity_maps_to_healthy_verdict() -> None:
    assert rank_to_verdict(severity_rank("info")) == "HEALTHY"


def test_floor_lifts_missing_verdict_from_findings() -> None:
    assert apply_finding_floor(None, ["warning"]) == "WARNING"


def test_floor_never_downgrades_llm_verdict() -> None:
    assert apply_finding_floor("CRITICAL", ["info"]) == "CRITICAL"


def test_floor_overrides_verdict_below_worst_finding() -> None:
    assert (
        apply_finding_floor("HEALTHY", ["critical"]) == "CRITICAL"
    )


def test_floor_no_findings_no_verdict_reads_healthy() -> None:
    assert apply_finding_floor(None, []) == "HEALTHY"


def test_floor_info_findings_read_healthy() -> None:
    assert apply_finding_floor(None, ["info"]) == "HEALTHY"
