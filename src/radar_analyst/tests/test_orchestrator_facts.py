"""Tight unit tests for the per-category facts builders in
:mod:`radar_analyst.analyze.orchestrator`. The integration tests
exercise the full pipeline; these lock in specific
prompt-shaping choices that the LLM downstream depends on.
"""

from __future__ import annotations

from radar_analyst.analyze.facts import (
    _build_pg_config_facts,
    _build_replication_facts,
)
from radar_analyst.parse.pg_conf import HbaRule
from radar_analyst.parse.pg_wal import ReplicationOrigin


def _hba(
    n: int,
    type_: str,
    method: str,
    *,
    database: str = "{all}",
    user: str = "{all}",
) -> HbaRule:
    return HbaRule(
        rule_number=n,
        type=type_,
        database=database,
        user_name=user,
        address="" if type_ == "local" else "0.0.0.0/0",
        auth_method=method,
        options="",
        error="",
    )


def test_hba_facts_pivot_by_type_so_local_trust_is_unambiguous() -> None:
    # The facts builder pivots HBA rules by connection type so
    # "trust on local" vs "trust on network" is unambiguous in
    # the prompt line itself.
    rules = [
        _hba(1, "local", "trust"),
        _hba(2, "local", "peer"),
        _hba(3, "host", "scram-sha-256"),
        _hba(4, "host", "scram-sha-256"),
        _hba(5, "hostssl", "scram-sha-256"),
    ]
    facts = _build_pg_config_facts({"pg.hba_file_rules": rules})
    assert facts is not None
    # Find the HBA line.
    line = next(ln for ln in facts.splitlines() if "HBA" in ln)
    # Header carries total rule count.
    assert "5 rules" in line
    # Per-type breakdown: local trust is clearly local; no
    # ambiguity with network rules.
    assert "local: " in line
    assert "host: " in line
    assert "hostssl: " in line
    # The trust=1 belongs to local, not host.
    local_chunk = line.split("local: ")[1].split(";")[0]
    assert "trust=1" in local_chunk
    host_chunk = line.split("host: ")[1].split(";")[0]
    assert "trust" not in host_chunk


def test_hba_facts_network_trust_is_visible_to_the_llm() -> None:
    # Sanity check the inverse: when network trust IS present,
    # the per-type breakdown surfaces it clearly so the LLM
    # has unambiguous facts to escalate on.
    rules = [
        _hba(1, "local", "peer"),
        _hba(2, "host", "trust"),
    ]
    facts = _build_pg_config_facts({"pg.hba_file_rules": rules})
    assert facts is not None
    line = next(ln for ln in facts.splitlines() if "HBA" in ln)
    host_chunk = line.split("host: ")[1].split(";")[0]
    assert "trust=1" in host_chunk


def test_hba_facts_silent_when_no_hba_rules() -> None:
    # Nothing crashes on missing HBA data.
    facts = _build_pg_config_facts({})
    # Either None or some non-HBA content; the only invariant
    # is no HBA line.
    if facts:
        assert "HBA" not in facts


def test_replication_facts_present_with_only_origins() -> None:
    # An archive can carry only pg_replication_origin_status
    # rows; the category still has evidence and must not be
    # short-circuited to UNKNOWN.
    parsed = {
        "pg.replication_origin": [
            ReplicationOrigin(
                local_id="1",
                external_id="pgl_node1",
                remote_lsn="0/1",
                local_lsn="0/2",
            )
        ]
    }
    facts = _build_replication_facts(parsed)
    assert facts is not None
    assert "origin" in facts.lower()
