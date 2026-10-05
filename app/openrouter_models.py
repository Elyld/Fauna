"""OpenRouter's public model catalog, filtered to vision-capable models.

Fauna's photo ID needs a model that can *see* — OpenRouter's model entries
carry `architecture.input_modalities`, so we keep only models whose input
modalities include "image". The public catalog needs no auth.

The list is cached in-process for 24 hours (the catalog changes slowly).
Every public function is defensive: failures return an empty list, never
raise — the Settings UI falls back to a plain text field when the catalog
is unreachable.
"""
from __future__ import annotations

import time

import httpx

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_TTL = 24 * 3600

_cache = {"at": 0.0, "models": []}


def clear_cache() -> None:
    """Empty the model-list cache (used by tests)."""
    _cache.update(at=0.0, models=[])


def is_free(entry: dict) -> bool:
    """A model is free when OpenRouter prices both directions at zero
    (the `:free` suffix is the usual marker, but the pricing fields are
    the ground truth)."""
    mid = entry.get("id") or ""
    if mid.endswith(":free"):
        return True
    pricing = entry.get("pricing") or {}
    try:
        return float(pricing.get("prompt") or 1) == 0 and float(
            pricing.get("completion") or 1
        ) == 0
    except (TypeError, ValueError):
        return False


def is_vision(entry: dict) -> bool:
    """True when the model's architecture accepts image input."""
    arch = entry.get("architecture") or {}
    modalities = arch.get("input_modalities") or []
    return "image" in modalities


def get_vision_models() -> list[dict]:
    """Vision-capable OpenRouter models: id, name, free flag. Cached 24h.

    Free models sort first, then alphabetically. Never raises — returns
    an empty list when the catalog can't be fetched.
    """
    now = time.time()
    if _cache["models"] and now - _cache["at"] < CACHE_TTL:
        return _cache["models"]
    models: list[dict] = []
    try:
        resp = httpx.get(
            MODELS_URL,
            headers={"User-Agent": "Fauna/1.0"},
            timeout=15.0,
        )
        resp.raise_for_status()
        for entry in resp.json().get("data", []):
            mid = entry.get("id") or ""
            if not mid or not is_vision(entry):
                continue
            models.append(
                {
                    "id": mid,
                    "name": entry.get("name") or mid,
                    "free": is_free(entry),
                }
            )
        models.sort(key=lambda m: (not m["free"], m["name"].lower()))
        _cache.update(at=now, models=models)
    except Exception:
        pass  # noqa: BLE001 — the UI falls back to a text field
    return models
