from __future__ import annotations

import hashlib
from typing import Any


VOICE_PROFILES: list[dict[str, Any]] = [
    {
        "id": "female_bright_pop",
        "gender": "female",
        "vocal_tone": "bright, clear, youthful pop tone",
        "delivery": "confident melodic phrasing with crisp chorus lift",
        "range_hint": "mid to upper register",
        "genre_affinity": ["pop", "synthwave", "dance", "trance"],
        "negative_prompt_terms": ["no smoky lounge vocal", "no gravelly male lead", "no monotone chant"],
    },
    {
        "id": "female_smoky_alt",
        "gender": "female",
        "vocal_tone": "smoky, intimate, alternative tone",
        "delivery": "restrained verses opening into a vulnerable hook",
        "range_hint": "low to mid register",
        "genre_affinity": ["alternative", "alt", "indie", "synthwave", "lofi"],
        "negative_prompt_terms": ["no bright bubblegum pop lead", "no shouted rock belt", "no male rap lead"],
    },
    {
        "id": "female_gritty_rock",
        "gender": "female",
        "vocal_tone": "raspy, gritty rock tone",
        "delivery": "driven belt with rough edges and an anthemic chorus",
        "range_hint": "mid register with pushed upper notes",
        "genre_affinity": ["rock", "metal", "punk", "arena", "glam"],
        "negative_prompt_terms": ["no airy whisper vocal", "no clean boy-band tone", "no trap mumble cadence"],
    },
    {
        "id": "female_airy_synth",
        "gender": "female",
        "vocal_tone": "airy, glassy synth-pop tone",
        "delivery": "floating lead with long vowels and layered harmonies",
        "range_hint": "upper register",
        "genre_affinity": ["synthwave", "synthpop", "electronic", "trance", "ambient"],
        "negative_prompt_terms": ["no gritty rock rasp", "no aggressive rap cadence", "no dry spoken vocal"],
    },
    {
        "id": "male_gritty_rock",
        "gender": "male",
        "vocal_tone": "gritty, weathered rock tone",
        "delivery": "strained verses with a full-throated chorus",
        "range_hint": "mid register with rough upper push",
        "genre_affinity": ["rock", "metal", "industrial", "arena", "glam"],
        "negative_prompt_terms": ["no airy female lead", "no clean pop croon", "no detached monotone"],
    },
    {
        "id": "male_clean_pop",
        "gender": "male",
        "vocal_tone": "clean, polished pop tone",
        "delivery": "smooth melodic phrasing with tight radio hooks",
        "range_hint": "mid to upper register",
        "genre_affinity": ["pop", "synthwave", "dance", "electronic"],
        "negative_prompt_terms": ["no gravelly rock growl", "no smoky alto lead", "no shouted chant"],
    },
    {
        "id": "male_dark_alt",
        "gender": "male",
        "vocal_tone": "dark, tense alternative tone",
        "delivery": "close, brooding verses with controlled chorus pressure",
        "range_hint": "low to mid register",
        "genre_affinity": ["alternative", "alt", "industrial", "metal", "darkwave"],
        "negative_prompt_terms": ["no bright pop smile", "no airy synth-pop lead", "no hype ad-lib delivery"],
    },
    {
        "id": "male_rap_tight",
        "gender": "male",
        "vocal_tone": "focused, percussive rap tone",
        "delivery": "tight rhythmic cadence with sharp consonants and compact hooks",
        "range_hint": "spoken low to mid register",
        "genre_affinity": ["rap", "trap", "hip-hop", "drill"],
        "negative_prompt_terms": ["no arena-rock belt", "no airy sung lead", "no loose mumble flow"],
    },
    {
        "id": "duet_call_response",
        "gender": "duet",
        "vocal_tone": "contrasting male and female lead tones",
        "delivery": "call-and-response verses with a shared chorus payoff",
        "range_hint": "low male register answered by mid/high female register",
        "genre_affinity": ["pop", "rock", "synthwave", "dance", "alternative"],
        "negative_prompt_terms": ["no single unison-only lead", "no faceless choir wash", "no monotone chant"],
    },
    {
        "id": "group_chant",
        "gender": "group",
        "vocal_tone": "stacked group chant with gang-vocal energy",
        "delivery": "short punchy phrases, crowd shouts, and unified hook accents",
        "range_hint": "mixed voices in a compact mid register",
        "genre_affinity": ["rock", "punk", "trap", "rap", "arena", "dance"],
        "negative_prompt_terms": ["no delicate solo ballad vocal", "no airy whisper lead", "no loose choir pad"],
    },
]


def _extract_recent_profile_ids(recent_generations: list[dict[str, Any]] | None) -> list[str]:
    ids: list[str] = []
    for item in recent_generations or []:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("voice_profile_id") or "").strip()
        if not profile_id:
            diagnostics = item.get("diagnostics", {})
            if isinstance(diagnostics, dict):
                voice = diagnostics.get("voice_profile", {})
                if isinstance(voice, dict):
                    profile_id = str(voice.get("id") or "").strip()
        if profile_id:
            ids.append(profile_id)
    return ids


def _profile_by_id(profile_id: str) -> dict[str, Any] | None:
    for profile in VOICE_PROFILES:
        if profile["id"] == profile_id:
            return profile
    return None


def _genre_score(profile: dict[str, Any], genre: str) -> int:
    lowered = (genre or "").lower()
    score = 0
    for token in profile.get("genre_affinity", []):
        t = str(token).lower().strip()
        if t and t in lowered:
            score += 8
    if not lowered:
        score += 1
    return score


def _station_hint_score(profile: dict[str, Any], station_profile: dict[str, Any]) -> int:
    hints = " ".join(str(x).lower() for x in station_profile.get("taste_hints", []) if str(x).strip())
    topics = " ".join(str(x).lower() for x in station_profile.get("topic_ideas", []) if str(x).strip())
    text = f"{hints} {topics}"
    profile_id = str(profile.get("id", ""))
    gender = str(profile.get("gender", ""))
    score = 0
    if gender and gender in text:
        score += 7
    for token in profile_id.split("_"):
        if token and token in text:
            score += 3
    return score


def choose_voice_profile(
    genre: str,
    station_profile: dict[str, Any] | None,
    recent_generations: list[dict[str, Any]] | None,
    salt: str,
) -> dict[str, Any]:
    profile = station_profile or {}
    requested = str(profile.get("voice_profile_id") or "").strip()
    if requested:
        found = _profile_by_id(requested)
        if found:
            return dict(found)

    recent_ids = _extract_recent_profile_ids(recent_generations)
    recent_set = set(recent_ids[:4])
    recent_genders = {
        str((found or {}).get("gender", ""))
        for found in (_profile_by_id(profile_id) for profile_id in recent_ids[:2])
        if found
    }

    scored: list[tuple[int, int, dict[str, Any]]] = []
    seed = f"{genre}|{salt}|{'|'.join(recent_ids)}"
    for idx, candidate in enumerate(VOICE_PROFILES):
        score = _genre_score(candidate, genre) + _station_hint_score(candidate, profile)
        if candidate["id"] in recent_set:
            score -= 20
        if candidate.get("gender") in recent_genders:
            score -= 6
        digest = hashlib.sha1(f"{seed}|{candidate['id']}".encode("utf-8")).digest()
        jitter = digest[0] % 5
        scored.append((score, jitter, candidate))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return dict(scored[0][2])


def format_voice_directive(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    tone = str(profile.get("vocal_tone", "")).strip()
    delivery = str(profile.get("delivery", "")).strip()
    range_hint = str(profile.get("range_hint", "")).strip()
    gender = str(profile.get("gender", "")).strip()
    parts = [part for part in [gender, tone, delivery, range_hint] if part]
    return "Vocal profile: " + "; ".join(parts) + "."
