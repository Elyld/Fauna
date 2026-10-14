"""Offline trait pack: 'did you know' facts from bundled scientific datasets.

EOL's TraitBank API needs an API key, and EOL's account system is currently
broken — so the fact cards read from public trait datasets shipped with the
app instead. All four are CC-licensed, static reference data (body mass,
diet, lifespan, ... don't change), imported once into the ``local_traits``
table at startup:

- EltonTraits 1.0 (Wilman et al. 2014) — diet/foraging, all birds + mammals
- AnAge — longevity, body mass, litter size; birds/mammals/reptiles
- AVONET (Tobias et al. 2022) — bird measurements, habitat, trophic niche
- PanTHERIA (Jones et al. 2009) — mammal life history

Raw CSVs live in app/trait_data/. ``ensure_loaded()`` is idempotent: it
only imports when the table is empty. Lookups are by lowercase scientific
name and return rows shaped like EOL Cypher results so app.eol._curate_cards
feeds both sources through one pipeline.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import LocalTrait

logger = logging.getLogger(__name__)

TRAIT_DATA_DIR = Path(__file__).resolve().parent / "trait_data"


def _norm_name(name: str | None) -> str:
    return (name or "").strip().lower()


def _fmt_mass_g(grams: float | None) -> str | None:
    """85 g stays '85 g'; 120000 g becomes '120 kg'."""
    if grams is None:
        return None
    try:
        g = float(grams)
    except (TypeError, ValueError):
        return None
    if g <= 0:
        return None
    if g >= 1000:
        kg = g / 1000
        s = str(int(kg)) if kg.is_integer() else f"{kg:.1f}".rstrip("0").rstrip(".")
        return f"{s} kg"
    s = str(int(g)) if g.is_integer() else f"{g:.1f}".rstrip("0").rstrip(".")
    return f"{s} g"


def _fmt_years(years: float | None) -> str | None:
    if years is None:
        return None
    try:
        y = float(years)
    except (TypeError, ValueError):
        return None
    if y <= 0:
        return None
    s = str(int(y)) if y.is_integer() else f"{y:.1f}".rstrip("0").rstrip(".")
    return f"{s} years"


# ---------------------------------------------------------------------------
# Dataset parsers. Each takes the data dir and yields
# (scientific_name, predicate, value) tuples. Predicates reuse
# app.eol.CARD_RULES vocabulary ("body mass", "diet", "maximum longevity",
# "habitat", "litter size", "gestation", "diel activity"). Values are
# pre-formatted display strings ("85 kg", "fruit 60%, seeds 30%").
# ---------------------------------------------------------------------------

DIET_LABELS = {
    "Diet-Inv": "invertebrates",
    "Diet-Vend": "mammals & birds",
    "Diet-Vect": "reptiles & amphibians",
    "Diet-Vfish": "fish",
    "Diet-Vunk": "vertebrates",
    "Diet-Scav": "carrion",
    "Diet-Fruit": "fruit",
    "Diet-Nect": "nectar",
    "Diet-Seed": "seeds",
    "Diet-PlantO": "plants",
}
DIET_COLS = list(DIET_LABELS)

BIRD_DIET_5CAT = {
    "Invertebrate": "invertebrates",
    "Omnivore": "omnivore",
    "FruiNect": "fruit & nectar",
    "PlantSeed": "seeds & plants",
    "VertFishScav": "vertebrates, fish & carrion",
}

AVONET_DIET = {
    "Invertivore": "invertebrates",
    "Frugivore": "fruit",
    "Granivore": "seeds",
    "Nectarivore": "nectar",
    "Omnivore": "omnivore",
    "Vertivore": "vertebrates",
    "Aquatic predator": "aquatic prey",
    "Scavenger": "carrion",
    "Herbivore terrestrial": "plants",
    "Herbivore aquatic": "aquatic plants",
}


def _diet_from_percentages(row: dict) -> str | None:
    """'fruit 60%, seeds 30%' from EltonTraits Diet-* percentage columns."""
    parts = []
    for col in DIET_COLS:
        try:
            pct = float(row.get(col) or 0)
        except (TypeError, ValueError):
            continue
        if pct > 0:
            parts.append((pct, DIET_LABELS[col]))
    if not parts:
        return None
    parts.sort(reverse=True)
    top = parts[:3]
    if len(top) == 1 and top[0][0] >= 100:
        return top[0][1]
    return ", ".join(
        f"{label} {int(p)}%" if float(p).is_integer() else f"{label} {p:.0f}%"
        for p, label in top
    )


def _parse_elton(data_dir: Path):
    """EltonTraits 1.0: diet (+ body mass and activity for mammals)."""
    for fname in ("elton_birds.txt", "elton_mammals.txt"):
        path = data_dir / fname
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                name = (row.get("Scientific") or "").strip()
                if not name:
                    continue
                diet = _diet_from_percentages(row)
                if not diet and fname == "elton_birds.txt":
                    diet = BIRD_DIET_5CAT.get((row.get("Diet-5Cat") or "").strip())
                if diet:
                    yield name, "diet", diet
                mass = _fmt_mass_g(row.get("BodyMass-Value"))
                if mass:
                    yield name, "body mass", mass
                acts = [
                    label
                    for col, label in (
                        ("Activity-Nocturnal", "nocturnal"),
                        ("Activity-Crepuscular", "crepuscular"),
                        ("Activity-Diurnal", "diurnal"),
                    )
                    if (row.get(col) or "").strip() == "1"
                ]
                if acts:
                    yield name, "diel activity", ", ".join(acts)


def _parse_anage(data_dir: Path):
    """AnAge: maximum longevity and adult body mass."""
    path = data_dir / "anage.csv"
    if not path.exists():
        return
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            name = f"{(row.get('Genus') or '').strip()} {(row.get('Species') or '').strip()}".strip()
            if len(name.split()) < 2:
                continue
            longevity = _fmt_years(row.get("Maximum.longevity.yrs"))
            if longevity:
                yield name, "maximum longevity", longevity
            mass = _fmt_mass_g(row.get("Body.mass.g"))
            if mass:
                yield name, "body mass", mass


def _parse_pantheria(data_dir: Path):
    """PanTHERIA: body mass, gestation, litter size, longevity (-999 = missing)."""
    path = data_dir / "pantheria_msw05.txt"
    if not path.exists():
        return

    def num(v):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return None if x == -999 else x

    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            name = (row.get("MSW05_Binomial") or "").strip()
            if not name:
                continue
            mass = _fmt_mass_g(num(row.get("5-1_AdultBodyMass_g")))
            if mass:
                yield name, "body mass", mass
            gest = num(row.get("9-1_GestationLen_d"))
            if gest and gest > 0:
                g = str(int(gest)) if gest.is_integer() else f"{gest:.0f}"
                yield name, "gestation", f"{g} days"
            litter = num(row.get("15-1_LitterSize"))
            if litter and litter > 0:
                yield name, "litter size", f"{litter:.0f}"
            longev_m = num(row.get("17-1_MaxLongevity_m"))
            if longev_m and longev_m > 0:
                longevity = _fmt_years(longev_m / 12)
                if longevity:
                    yield name, "maximum longevity", longevity


def _parse_avonet(data_dir: Path):
    """AVONET: body mass, habitat, and trophic niche for birds."""
    path = data_dir / "avonet_birdlife.csv"
    if not path.exists():
        return
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            name = (row.get("Species1") or "").strip()
            if not name:
                continue
            mass = _fmt_mass_g(row.get("Mass"))
            if mass:
                yield name, "body mass", mass
            habitat = (row.get("Habitat") or "").strip()
            if habitat:
                yield name, "habitat", habitat
            diet = AVONET_DIET.get((row.get("Trophic.Niche") or "").strip())
            if diet:
                yield name, "diet", diet


_PARSERS = {
    # Priority order: first writer wins per (species, predicate).
    "anage": _parse_anage,
    "pantheria": _parse_pantheria,
    "elton": _parse_elton,
    "avonet": _parse_avonet,
}


def ensure_loaded(session: Session) -> int:
    """Import bundled CSVs into local_traits. Idempotent; returns row count.

    Skips entirely when the table already has rows. First writer wins per
    (species, predicate) — parsers run in _PARSERS priority order. Never
    raises: a missing or malformed CSV only means fewer offline facts,
    never a failed startup.
    """
    try:
        existing = session.query(LocalTrait.id).limit(1).first()
        if existing is not None:
            return session.query(LocalTrait.id).count()
        seen: set[tuple[str, str]] = set()
        total = 0
        batch: list[LocalTrait] = []
        for key, parse in _PARSERS.items():
            try:
                for name, pred, value in parse(TRAIT_DATA_DIR):
                    norm = _norm_name(name)
                    if not norm or not pred or not value:
                        continue
                    dup = (norm, pred)
                    if dup in seen:
                        continue
                    seen.add(dup)
                    batch.append(
                        LocalTrait(
                            scientific_name=norm,
                            dataset=key,
                            predicate=pred,
                            value=value,
                        )
                    )
            except Exception:
                logger.exception("trait pack: failed parsing dataset %s", key)
                continue
        if batch:
            session.bulk_save_objects(batch)
            total = len(batch)
        session.commit()
        logger.info("trait pack: loaded %d local trait rows", total)
        return total
    except Exception:
        logger.exception("trait pack: load failed")
        session.rollback()
        return 0


def fetch_local_trait_rows(session: Session, scientific_name: str) -> list[dict]:
    """Trait rows for a species, shaped like EOL Cypher results.

    Returns [{"predicate", "literal"}, ...] — [] when the species isn't in
    the pack. Never raises.
    """
    try:
        name = _norm_name(scientific_name)
        if not name:
            return []
        traits = (
            session.query(LocalTrait)
            .filter(LocalTrait.scientific_name == name)
            .all()
        )
        return [
            {"predicate": t.predicate, "literal": t.value}
            for t in traits
        ]
    except Exception:
        logger.exception("trait pack: lookup failed for %r", scientific_name)
        return []
