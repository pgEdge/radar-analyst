"""Small text-file readers for system identity + hardware facts.

Each reader takes the raw bytes of one radar entry and returns a
narrow typed value. None means "file absent or unparseable"; callers
coalesce.
"""

from __future__ import annotations


def _text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace").strip()


def parse_hostname(data: bytes) -> str | None:
    """``hostname`` is one line; sometimes FQDN, sometimes short."""
    s = _text(data)
    return s or None


def parse_os_release(data: bytes) -> dict[str, str]:
    """``/etc/os-release`` parses to a plain KEY=VALUE dict.

    Quotes around values are stripped; comment lines skipped.
    PRETTY_NAME is the one field humans actually want.
    """
    out: dict[str, str] = {}
    for line in data.decode(
        "utf-8", errors="replace"
    ).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip("\"'")
    return out


def parse_uname(data: bytes) -> str | None:
    """Output of ``uname -a``: keep the whole line."""
    s = _text(data)
    return s or None


def parse_lscpu(data: bytes) -> dict[str, str]:
    """``lscpu`` output is a list of ``Key:  value`` lines."""
    out: dict[str, str] = {}
    for line in data.decode(
        "utf-8", errors="replace"
    ).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out


def parse_hypervisor(data: bytes) -> str:
    """``system/hypervisor.out``: single token; ``none`` means
    bare metal, anything else (``kvm``, ``vmware``, ``xen``,
    ``microsoft``, ``oracle``, etc.) names the virtualisation
    layer detected by ``systemd-detect-virt``. Returns the raw
    token (lowercased, whitespace stripped); empty string when
    the file is absent or unreadable.
    """
    return _text(data).lower()


def parse_uptime(data: bytes) -> float | None:
    """``/proc/uptime`` first field: seconds since boot."""
    try:
        return float(
            data.decode("ascii", errors="replace").split()[0]
        )
    except (ValueError, IndexError):
        return None


def cpu_count_from_lscpu(lscpu: dict[str, str]) -> int:
    """The host's CPU count from a parsed lscpu map, or 0."""
    try:
        return int(lscpu.get("CPU(s)", "0") or 0)
    except ValueError:
        return 0
