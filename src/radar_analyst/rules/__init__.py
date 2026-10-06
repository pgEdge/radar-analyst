"""Rule engine.

Importing this package registers every rule in the REGISTRY via the
``@register`` decorator at module import time.
"""

from radar_analyst.rules import (
    host_os,
    pg_activity,
    pg_conf,
    pg_config,
    pg_diagnostics,
    pg_health,
    pg_internals,
    pg_replication,
    pg_workload,
)
from radar_analyst.rules.base import (
    REGISTRY,
    Finding,
    apply_finding_floor,
    rank_to_verdict,
    register,
    run_for_category,
    severity_rank,
)


# The rule modules appear here because importing them is what
# registers their rules; nothing else reads these names.
__all__ = [
    "REGISTRY",
    "Finding",
    "apply_finding_floor",
    "host_os",
    "pg_activity",
    "pg_conf",
    "pg_config",
    "pg_diagnostics",
    "pg_health",
    "pg_internals",
    "pg_replication",
    "pg_workload",
    "rank_to_verdict",
    "register",
    "run_for_category",
    "severity_rank",
]
