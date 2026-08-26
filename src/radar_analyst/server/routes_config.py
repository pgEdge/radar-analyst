"""GET /api/config: the configured AI providers and availability."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from radar_analyst.ai import DEFAULT_PROVIDER, providers


router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config() -> dict[str, Any]:
    """List the AI providers, with availability and model name.

    Each entry carries ``name``, ``label``, ``available`` and
    ``model``; an unavailable provider that can explain itself also
    carries ``reason``.
    """
    items: list[dict[str, Any]] = []
    for p in providers():
        adapter = p.factory()
        entry: dict[str, Any] = {
            "name": p.name,
            "label": p.label,
            "available": adapter.available(),
            "model": adapter.model,
        }
        # Unavailable adapters say why, so the UI renders the
        # missing env var instead of a bare disabled chip.
        if not entry["available"]:
            entry["reason"] = adapter.unavailable_reason()
        items.append(entry)
    return {
        "providers": items,
        "default": DEFAULT_PROVIDER,
    }
