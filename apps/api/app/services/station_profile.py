from __future__ import annotations

import re
from typing import Any


DEFAULT_PROFILE: dict[str, Any] = {
    "preset": "cohesive_radio",
    "genre_mode": "single_genre",
    "cohesion_spectrum": 80,
    "discovery_depth": 20,
    "lyrics_mode": "mixed",
    "clean_lyrics_only": True,
    "mood_seed": "baseline",
    "mood_volatility": 30,
    "energy_variability": 30,
    "vocal_ratio": 40,
    "target_duration_sec": 320,
    "duration_jitter_sec": 12,
    "duration_min_sec": 320,
    "duration_max_sec": 320,
    "ace_overrides": {},
    "taste_hints": [],
    "topic_ideas": [],
}


def clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def normalize_station_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_PROFILE)
    if profile:
        merged.update(profile)

    merged["cohesion_spectrum"] = clamp_int(int(merged.get("cohesion_spectrum", 80)), 0, 100)
    merged["discovery_depth"] = clamp_int(int(merged.get("discovery_depth", 20)), 0, 100)
    merged["mood_volatility"] = clamp_int(int(merged.get("mood_volatility", 30)), 0, 100)
    merged["energy_variability"] = clamp_int(int(merged.get("energy_variability", 30)), 0, 100)
    merged["vocal_ratio"] = clamp_int(int(merged.get("vocal_ratio", 40)), 0, 100)
    merged["target_duration_sec"] = clamp_int(int(merged.get("target_duration_sec", 320)), 150, 320)
    merged["duration_jitter_sec"] = clamp_int(int(merged.get("duration_jitter_sec", 12)), 0, 45)
    merged["duration_min_sec"] = clamp_int(int(merged.get("duration_min_sec", 320)), 120, 320)
    merged["duration_max_sec"] = clamp_int(int(merged.get("duration_max_sec", 320)), 120, 320)
    if merged["duration_min_sec"] > merged["duration_max_sec"]:
        merged["duration_min_sec"], merged["duration_max_sec"] = merged["duration_max_sec"], merged["duration_min_sec"]
    if merged["target_duration_sec"] < merged["duration_min_sec"]:
        merged["target_duration_sec"] = merged["duration_min_sec"]
    if merged["target_duration_sec"] > merged["duration_max_sec"]:
        merged["target_duration_sec"] = merged["duration_max_sec"]

    raw_lyrics_mode = str(merged.get("lyrics_mode", "mixed")).strip().lower()
    lyrics_aliases = {
        "instrumental": "instrumental_only",
        "instrumental_only": "instrumental_only",
        "no_lyrics": "instrumental_only",
        "mixed": "mixed",
        "balanced": "mixed",
        "vocal": "vocal_forward",
        "vocal_forward": "vocal_forward",
        "lyrics": "vocal_forward",
    }
    lyrics_mode = lyrics_aliases.get(raw_lyrics_mode, "mixed")
    merged["lyrics_mode"] = lyrics_mode

    mood_seed = str(merged.get("mood_seed", "baseline")).strip().lower()
    if mood_seed not in {"baseline", "rise", "peak", "release"}:
        mood_seed = "baseline"
    merged["mood_seed"] = mood_seed

    genre_mode = str(merged.get("genre_mode", "single_genre"))
    if genre_mode not in {"single_genre", "genre_blend", "open_format"}:
        genre_mode = "single_genre"
    merged["genre_mode"] = genre_mode

    merged["clean_lyrics_only"] = bool(merged.get("clean_lyrics_only", True))
    tastes = merged.get("taste_hints", [])
    if isinstance(tastes, list):
        merged["taste_hints"] = [str(x).strip() for x in tastes if str(x).strip()][:8]
    else:
        merged["taste_hints"] = []
    topics = merged.get("topic_ideas", [])
    if isinstance(topics, list):
        merged["topic_ideas"] = [str(x).strip() for x in topics if str(x).strip()][:8]
    else:
        merged["topic_ideas"] = []
    ace_overrides = merged.get("ace_overrides", {})
    merged["ace_overrides"] = ace_overrides if isinstance(ace_overrides, dict) else {}

    # Keep an inverse relationship so station behavior is coherent.
    if merged["discovery_depth"] > (100 - merged["cohesion_spectrum"] + 20):
        merged["discovery_depth"] = max(0, 100 - merged["cohesion_spectrum"] + 20)

    return merged


def slugify_station_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:68] or "custom-station"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def infer_station_taste_hints(*, genre: str, personality: str, description: str) -> list[str]:
    hints: list[str] = []
    if genre.strip():
        hints.append(genre.strip())
    if personality.strip():
        hints.append(personality.strip())

    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", description or "")
    stop = {"the", "and", "with", "from", "that", "this", "your", "into", "for", "are", "was", "you"}
    for word in words:
        low = word.lower()
        if low in stop:
            continue
        hints.append(low)
        if len(hints) >= 8:
            break
    return _dedupe_keep_order(hints)[:8]


def reprofile_station_profile(
    *,
    current_profile: dict[str, Any] | None,
    genre: str,
    personality: str,
    description: str,
    overrides: dict[str, Any] | None = None,
    include_inferred_taste_hints: bool = True,
) -> dict[str, Any]:
    merged = dict(current_profile or {})
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})

    existing_hints = merged.get("taste_hints", [])
    if not isinstance(existing_hints, list):
        existing_hints = []
    raw_hints = [str(x).strip() for x in existing_hints if str(x).strip()]
    if include_inferred_taste_hints:
        raw_hints.extend(infer_station_taste_hints(genre=genre, personality=personality, description=description))
    merged["taste_hints"] = _dedupe_keep_order(raw_hints)[:8]
    return normalize_station_profile(merged)
