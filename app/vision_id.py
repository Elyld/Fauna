"""Photo ID via an OpenRouter vision model.

iNaturalist's own computer-vision endpoint needs a per-user JWT that expires
every 24 hours (a daily copy-paste chore), so Fauna's primary photo-ID path
asks a vision-capable chat model through OpenRouter instead. The household's
OpenRouter key lives server-side in Settings and never expires.

The model only has to *name* the animal in the photo; iNaturalist's free,
no-auth taxonomy endpoints then attach the canonical names, thumbnails, and
links, and the human confirms the pick before anything is saved.
"""
from __future__ import annotations

import base64
import json
import os
import re

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Default vision model: a free OpenRouter model with image input. Verified
# against the live model list; pick can be overridden in Settings.
DEFAULT_VISION_MODEL = "google/gemma-4-31b-it:free"

SYSTEM_PROMPT = (
    "You are a wildlife identification assistant. Look at the photo and name "
    "the animal(s) visible in it. Reply with ONLY a JSON array (no markdown, "
    "no prose) of up to 3 candidates, best guess first. Each candidate is an "
    "object: {\"common_name\": \"...\", \"scientific_name\": \"...\", "
    "\"confidence\": 0.0-1.0, \"notes\": \"one short sentence on the visible "
    "features that led you here\"}. "
    "If no animal is visible, reply with an empty array []."
)


class VisionIDError(Exception):
    """Raised when vision photo ID can't produce candidates.

    `reason` is one of:
      "no_key"       — no OpenRouter key configured
      "parse_failed" — the model didn't return usable JSON
      "api_error"    — transport failure or the API refused the request
      "no_animal"    — the model saw no animal in the photo
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _guess_mime(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")


def _sanitize_no_proxy() -> None:
    """Drop malformed NO_PROXY entries (bracketed IPv6 literals like "[::1]")
    that crash httpx's proxy-env parsing. No-op on well-formed systems."""
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val and "[" in val:
            os.environ[var] = ",".join(p for p in val.split(",") if "[" not in p)


_sanitize_no_proxy()


def _extract_json_array(text: str) -> list:
    """Pull a JSON array out of model output, tolerating fences and prose."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError("expected a JSON array")
    return parsed


def identify_with_vision(
    image_bytes: bytes,
    filename: str = "photo.jpg",
    api_key: str | None = None,
    model: str = DEFAULT_VISION_MODEL,
) -> list[dict]:
    """Name the animal(s) in a photo with an OpenRouter vision model.

    Returns up to 3 candidates, best guess first: each has common_name,
    scientific_name, confidence (0.0-1.0), and notes. Raises VisionIDError
    on any failure (see class docstring for reasons).
    """
    if not api_key:
        raise VisionIDError("no_key")
    if not image_bytes:
        raise VisionIDError("api_error")
    b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = _guess_mime(filename)
    payload = {
        "model": model or DEFAULT_VISION_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What animal is in this photo?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            },
        ],
        "max_tokens": 600,
        "temperature": 0.2,
    }
    try:
        resp = httpx.post(
            OPENROUTER_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # Identifies the app to OpenRouter (optional, recommended).
                "X-Title": "Fauna wildlife journal",
            },
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise VisionIDError("api_error") from exc
    if resp.status_code >= 400:
        raise VisionIDError("api_error")
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise VisionIDError("parse_failed") from exc
    try:
        candidates = _extract_json_array(content)
    except (ValueError, json.JSONDecodeError) as exc:
        raise VisionIDError("parse_failed") from exc
    results: list[dict] = []
    for cand in candidates[:3]:
        if not isinstance(cand, dict):
            continue
        common = (cand.get("common_name") or "").strip()
        sci = (cand.get("scientific_name") or "").strip()
        if not common and not sci:
            continue
        try:
            conf = float(cand.get("confidence", 0.5))
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        results.append(
            {
                "common_name": common or None,
                "scientific_name": sci or None,
                "confidence": conf,
                "notes": (cand.get("notes") or "").strip() or None,
            }
        )
    if not results:
        raise VisionIDError("no_animal")
    return results
