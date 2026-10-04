"""Bird sound ID via BirdNET-Analyzer (server-side, Merlin Sound-ID style).

How it works: she records or uploads a short clip, the server runs BirdNET's
model on it and returns ranked species suggestions. Live real-time listening
like Merlin's Sound ID isn't feasible in a web v1 — this analyzes a recorded
clip and gives the same answer a few seconds later.

Heavy optional dependency: birdnet-analyzer pulls in TensorFlow (~700MB
installed) and downloads a ~230MB model on first use (cached in the package's
checkpoints/ dir). The import is lazy; if the package isn't installed,
is_available() is False and the API degrades gracefully instead of 500ing.
"""
from __future__ import annotations

import csv
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()
_MIN_CONFIDENCE = 0.25
_TOP_N = 5
MAX_CLIP_BYTES = 20 * 1024 * 1024

# BirdNET's label set includes a few non-bird sounds — never suggest those
# in a wildlife journal.
_NON_BIRD_LABELS = frozenset(
    {"dog", "engine", "environmental", "fireworks", "gun", "noise", "siren"}
)


def is_available() -> bool:
    """True when birdnet-analyzer is installed and importable."""
    try:
        import birdnet_analyzer  # noqa: F401

        return True
    except ImportError:
        return False


def _parse_results_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            try:
                conf = float(row.get("Confidence") or 0)
            except (TypeError, ValueError):
                continue
            sci = (row.get("Scientific name") or "").strip()
            common = (row.get("Common name") or "").strip()
            if not sci:
                continue
            rows.append(
                {
                    "scientific_name": sci,
                    "common_name": common or sci,
                    "confidence": conf,
                    "start_s": row.get("Start (s)"),
                }
            )
    return rows


def _enrich_with_photos(suggestions: list[dict]) -> None:
    """Best-effort: attach an iNaturalist thumbnail to each suggestion."""
    from app import inat

    for s in suggestions:
        try:
            matches = inat.search_taxa(s["scientific_name"], per_page=1)
            if matches and matches[0].get("photo_url"):
                s["photo_url"] = matches[0]["photo_url"]
        except Exception:  # noqa: BLE001 — photo is decorative; never fail the ID
            continue


def analyze_clip(
    audio_bytes: bytes,
    filename: str = "clip.wav",
    min_confidence: float = _MIN_CONFIDENCE,
    top_n: int = _TOP_N,
    enrich: bool = True,
) -> list[dict]:
    """Analyze an audio clip; return ranked species suggestions, best first.

    Each suggestion matches the photo-ID card shape: taxon_id (None —
    BirdNET yields names, not iNaturalist ids), common_name, scientific_name,
    rank ("species"), vision_score (None), combined_score (confidence 0..1),
    photo_url (best-effort iNaturalist thumbnail, may be None).
    """
    if not is_available():
        raise RuntimeError("birdnet-analyzer is not installed")
    if not audio_bytes:
        raise ValueError("empty audio")

    from birdnet_analyzer.analyze import analyze

    ext = Path(filename or "clip.wav").suffix.lower() or ".wav"
    with tempfile.TemporaryDirectory(prefix="fauna-birdnet-") as tmp:
        tmpdir = Path(tmp)
        clip_path = tmpdir / f"clip{ext}"
        clip_path.write_bytes(audio_bytes)
        outdir = tmpdir / "out"
        outdir.mkdir()
        # threads=1: no multiprocessing fork inside a web worker; the
        # analyzer keeps its config in globals, so serialize analyses.
        with _LOCK:
            analyze(
                str(clip_path),
                output=str(outdir),
                rtype="csv",
                min_conf=min_confidence,
                threads=1,
            )
        csv_files = list(outdir.glob("*.BirdNET.results.csv"))
        rows: list[dict] = []
        for cf in csv_files:
            rows.extend(_parse_results_csv(cf))

    # One row per species: keep each species' best (max-confidence) detection.
    # Non-bird sounds (engine noise etc.) are never suggested.
    best: dict[str, dict] = {}
    for row in rows:
        if row["scientific_name"].lower() in _NON_BIRD_LABELS:
            continue
        key = row["scientific_name"]
        if key not in best or row["confidence"] > best[key]["confidence"]:
            best[key] = row
    ranked = sorted(best.values(), key=lambda r: r["confidence"], reverse=True)[:top_n]

    suggestions = [
        {
            "taxon_id": None,
            "common_name": r["common_name"],
            "scientific_name": r["scientific_name"],
            "rank": "species",
            "vision_score": None,
            "combined_score": round(r["confidence"], 4),
            "photo_url": None,
        }
        for r in ranked
    ]
    if enrich:
        _enrich_with_photos(suggestions)
    return suggestions
