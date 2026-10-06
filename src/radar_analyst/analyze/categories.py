"""Canonical list of analysis categories.

Each category is one LLM call and answers one diagnostic question a DBA
asks during a health check. The orchestrator iterates this tuple in
order; the UI groups findings + briefs by the same ``name``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    """One analysis category: display name plus URL slug."""
    name: str  # human-readable, used in prompts and persisted rows
    key: str  # stable slug for URL params and JSON API responses


CATEGORIES: tuple[Category, ...] = (
    Category(name="Host & OS", key="host_os"),
    Category(
        name="PostgreSQL Configuration", key="pg_config"
    ),
    Category(name="Workload", key="pg_workload"),
    Category(
        name="Internals & I/O Health", key="pg_health"
    ),
    Category(name="Replication", key="pg_replication"),
)
