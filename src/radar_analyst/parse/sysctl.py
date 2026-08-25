"""Parse ``system/sysctl.out`` and filter to PG-relevant keys.

``sysctl -a`` emits ~1000 keys on a typical Linux host. For LLM token
budget reasons we only forward values for a whitelist of keys that
plausibly affect a PostgreSQL workload. Everything else is dropped
silently.
"""

from __future__ import annotations

# Kernel tunables that meaningfully affect a PostgreSQL database
# server's performance, durability, or connection capacity.
PG_RELEVANT_KEYS: frozenset[str] = frozenset(
    {
        # VM / page cache / dirty-page writeback
        "vm.dirty_background_bytes",
        "vm.dirty_background_ratio",
        "vm.dirty_bytes",
        "vm.dirty_ratio",
        "vm.dirty_expire_centisecs",
        "vm.dirty_writeback_centisecs",
        "vm.overcommit_memory",
        "vm.overcommit_ratio",
        "vm.swappiness",
        "vm.nr_hugepages",
        "vm.nr_overcommit_hugepages",
        "vm.max_map_count",
        "vm.min_free_kbytes",
        "vm.zone_reclaim_mode",
        # Shared memory / semaphores (still matter for PG even with
        # dynamic shared memory because some IPC uses SysV)
        "kernel.shmmax",
        "kernel.shmall",
        "kernel.shmmni",
        "kernel.sem",
        "kernel.randomize_va_space",
        "kernel.numa_balancing",
        # Networking: client connection capacity and keepalive
        "net.core.somaxconn",
        "net.core.rmem_max",
        "net.core.wmem_max",
        "net.core.rmem_default",
        "net.core.wmem_default",
        "net.ipv4.tcp_keepalive_time",
        "net.ipv4.tcp_keepalive_intvl",
        "net.ipv4.tcp_keepalive_probes",
        "net.ipv4.tcp_fin_timeout",
        "net.ipv4.ip_local_port_range",
        # File descriptors and async I/O
        "fs.file-max",
        "fs.nr_open",
        "fs.aio-max-nr",
    }
)


def parse_sysctl(data: bytes) -> dict[str, str]:
    """Return a ``{key: value}`` dict of whitelisted sysctl values."""
    out: dict[str, str] = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        if key not in PG_RELEVANT_KEYS:
            continue
        out[key] = raw.strip()
    return out
