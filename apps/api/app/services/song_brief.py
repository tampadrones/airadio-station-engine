from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any


_GENERIC_FORBIDDEN = [
    "city lights",
    "we own the night",
    "never give up",
    "rise above",
    "feel alive",
    "in the moment",
    "through the noise",
    "signal stays strong",
    "right here right now",
    "no pause no fade",
]


def _ascii(value: object) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    text = normalized.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126)


def _clean_topic(value: str) -> str:
    raw = _ascii(value).lower()
    words = re.findall(r"[a-z0-9']+", raw)
    stop = {"a", "an", "and", "or", "the", "for", "with", "song", "track", "music", "radio", "station"}
    kept = [w for w in words if w not in stop]
    return " ".join(kept[:7]) or "turning point"


def _recent_briefs(recent_generations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in recent_generations or []:
        if not isinstance(item, dict):
            continue
        brief = item.get("song_brief")
        if not isinstance(brief, dict):
            diagnostics = item.get("diagnostics", {})
            if isinstance(diagnostics, dict):
                brief = diagnostics.get("song_brief")
            if not isinstance(brief, dict):
                pre = item.get("preprocessor", {})
                diagnostics = pre.get("diagnostics", {}) if isinstance(pre, dict) else {}
                brief = diagnostics.get("song_brief") if isinstance(diagnostics, dict) else None
        if isinstance(brief, dict):
            out.append(brief)
    return out


def _used_values(recent_generations: list[dict[str, Any]] | None, field: str) -> set[str]:
    return {_ascii(brief.get(field, "")).lower() for brief in _recent_briefs(recent_generations) if _ascii(brief.get(field, ""))}


def _genre_key(genre: str) -> str:
    g = (genre or "").lower()
    if "trap" in g or "rap" in g or "hip-hop" in g:
        return "trap"
    if "synthwave" in g or "synthpop" in g:
        return "synthwave"
    if "lofi" in g or "lo-fi" in g or "chillhop" in g:
        return "lofi"
    if any(token in g for token in ["nu-metal", "numetal", "industrial", "deftones", "nine inch nails"]):
        return "nu_metal"
    if "rock" in g or "metal" in g or "punk" in g:
        return "rock"
    return "general"


def _pools(genre: str) -> dict[str, list[str]]:
    key = _genre_key(genre)
    common = {
        "narrator": [
            "first-person narrator making one risky choice",
            "witness watching a friend cross a line",
            "late-night caller confessing the real motive",
            "driver narrating the moment before the turn",
        ],
        "emotional_turn": [
            "doubt turns into a precise decision",
            "anger cools into control",
            "nostalgia becomes forward motion",
            "fear becomes a named cost",
        ],
        "chorus_strategy": [
            "repeat one concrete image with a changed final line",
            "make the chorus answer the verse conflict directly",
            "use a short title phrase as the last line only",
            "escalate the same action across each chorus",
        ],
    }
    genre_pools = {
        "trap": {
            "angle": ["turn the topic into a pressure-tested come-up", "frame the topic as a calculated late-night move", "make the topic a win earned under surveillance"],
            "setting": ["locked-in studio after midnight", "rainy block outside a closed store", "dashboard glow near the last exit"],
            "conflict": ["focus is threatened by debt, doubt, and fake loyalty", "one bad choice could waste the whole run", "the room wants celebration before the work is finished"],
            "hook_concept": ["the hook lands like a decision made under pressure", "the hook turns restraint into the flex", "the hook repeats the move that changes the odds"],
            "imagery_bank": ["phone light", "wet pavement", "dashboard glow", "coded route", "quiet win", "locked door"],
        },
        "synthwave": {
            "angle": ["turn the topic into a neon chase with emotional stakes", "frame the topic as a message found too late", "make the topic a midnight escape through memory"],
            "setting": ["rain-slick overpass under violet signs", "empty arcade glowing after close", "chrome dashboard on an expressway loop"],
            "conflict": ["the past keeps calling while the road demands a choice", "the message arrives after the exit is already missed", "speed hides the truth until the chorus names it"],
            "hook_concept": ["the hook is the turn signal before the emotional crash", "the hook repeats the message the narrator cannot ignore", "the hook makes the escape feel romantic and dangerous"],
            "imagery_bank": ["neon", "chrome", "arcade glass", "tail lights", "cassette hiss", "blue rain"],
        },
        "lofi": {
            "angle": ["turn the topic into a quiet room-sized realization", "frame the topic as a note written but never sent", "make the topic a small habit that reveals the whole story"],
            "setting": ["desk lamp beside a rain-streaked window", "kitchen table before sunrise", "empty apartment with a humming laptop"],
            "conflict": ["old thoughts keep circling until one detail breaks the loop", "the narrator wants peace but keeps rereading the evidence", "silence makes the unfinished conversation louder"],
            "hook_concept": ["the hook stays intimate and repeats a private object", "the hook resolves the thought without making it grand", "the hook lets one small image carry the feeling"],
            "imagery_bank": ["cup steam", "notebook margin", "window rain", "lamp hum", "soft dust", "morning edge"],
        },
        "nu_metal": {
            "angle": ["turn the topic into a failed escape cycle", "frame the topic as a body trapped inside a hostile room", "make the topic a fracture between identity and control"],
            "setting": ["sealed hallway under a red exit sign", "fluorescent room with shaking glass", "concrete stairwell full of wire hum"],
            "conflict": ["the exit keeps resetting every time the narrator reaches it", "the body remembers damage the mind tries to deny", "control tightens whenever the narrator names the truth"],
            "hook_concept": ["the hook is a shouted command to break the loop", "the hook repeats the lock image until it cracks", "the hook turns panic into a physical release"],
            "imagery_bank": ["glass", "wire", "rust", "red light", "static", "breath", "fracture"],
        },
        "rock": {
            "angle": ["turn the topic into a last-stand road confession", "frame the topic as a stage-light confrontation", "make the topic a storm the narrator drives straight into"],
            "setting": ["wide road under a hard storm front", "backstage hallway before the final set", "cracked asphalt outside a motel sign"],
            "conflict": ["pride wants to run but the truth demands volume", "the narrator must choose between escape and repair", "the past catches up at full speed"],
            "hook_concept": ["the hook opens like a physical release", "the hook turns the title into a shouted vow", "the hook makes the consequence feel worth the burn"],
            "imagery_bank": ["thunder", "headlights", "smoke", "scar", "steel", "open road"],
        },
        "general": {
            "angle": ["turn the topic into a specific choice before dawn", "frame the topic as a message that changes the route", "make the topic a promise tested in public"],
            "setting": ["late bus stop under weak streetlight", "small apartment during a weather shift", "empty diner booth after closing"],
            "conflict": ["one honest sentence could change the relationship", "the narrator has to act before the chance disappears", "comfort and truth pull in opposite directions"],
            "hook_concept": ["the hook repeats the choice in plain language", "the hook turns a concrete object into the title image", "the hook resolves the conflict without explaining it"],
            "imagery_bank": ["doorway", "weather", "hands", "receipt", "window", "last call"],
        },
    }
    selected = genre_pools.get(key, genre_pools["general"])
    return {**common, **selected}


def _pick(
    options: list[str],
    *,
    label: str,
    seed: str,
    avoid: set[str] | None = None,
) -> str:
    if not options:
        return ""
    avoid = avoid or set()
    digest = hashlib.sha1(f"{seed}|{label}|{len(options)}".encode("utf-8")).digest()
    start = digest[0] % len(options)
    ordered = options[start:] + options[:start]
    if digest[1] % 2:
        ordered = list(reversed(ordered))
    for item in ordered:
        if _ascii(item).lower() not in avoid:
            return item
    return ordered[0]


def _title_seed(topic: str, hook_concept: str, imagery_bank: list[str], seed: str) -> str:
    topic_words = [w.title() for w in re.findall(r"[a-z0-9']+", topic) if w not in {"and", "the", "with"}]
    image = imagery_bank[hashlib.sha1(f"{seed}|title".encode("utf-8")).digest()[0] % max(1, len(imagery_bank))]
    if topic_words:
        return _ascii(f"{' '.join(topic_words[:2])} {image.title()}")
    hook_words = re.findall(r"[A-Za-z0-9']+", hook_concept)
    return _ascii(" ".join(hook_words[:3]).title() or image.title())


def build_song_brief(
    *,
    topic: str,
    genre: str,
    mood: str,
    daypart: str,
    station_profile: dict,
    recent_generations: list,
    voice_profile: dict | None = None,
    salt: str = "",
) -> dict:
    clean_topic = _clean_topic(topic)
    runtime_salt = salt or datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    voice_id = str((voice_profile or {}).get("id", ""))
    hints = "|".join(str(x) for x in (station_profile or {}).get("taste_hints", [])[:4])
    seed = f"{clean_topic}|{genre}|{mood}|{daypart}|{voice_id}|{hints}|{runtime_salt}"
    pools = _pools(genre)

    narrator = _pick(pools["narrator"], label="narrator", seed=seed, avoid=_used_values(recent_generations, "narrator"))
    setting = _pick(pools["setting"], label="setting", seed=seed, avoid=_used_values(recent_generations, "setting"))
    conflict = _pick(pools["conflict"], label="conflict", seed=seed, avoid=_used_values(recent_generations, "conflict"))
    hook_concept = _pick(
        pools["hook_concept"],
        label="hook",
        seed=seed,
        avoid=_used_values(recent_generations, "hook_concept"),
    )
    angle = _pick(pools["angle"], label="angle", seed=seed)
    emotional_turn = _pick(pools["emotional_turn"], label="turn", seed=seed)
    chorus_strategy = _pick(pools["chorus_strategy"], label="chorus", seed=seed)

    imagery = list(dict.fromkeys(_ascii(x) for x in pools["imagery_bank"] if _ascii(x)))
    digest = hashlib.sha1(f"{seed}|imagery".encode("utf-8")).digest()
    if imagery:
        start = digest[0] % len(imagery)
        imagery = (imagery[start:] + imagery[:start])[:6]

    forbidden = list(_GENERIC_FORBIDDEN)
    for brief in _recent_briefs(recent_generations):
        hook = _ascii(brief.get("hook_concept", "")).lower()
        if hook:
            forbidden.append(hook[:80])

    out = {
        "topic": clean_topic,
        "angle": f"{angle}: {clean_topic}",
        "narrator": narrator,
        "setting": setting,
        "conflict": conflict,
        "emotional_turn": emotional_turn,
        "hook_concept": hook_concept,
        "chorus_strategy": chorus_strategy,
        "imagery_bank": imagery,
        "forbidden_phrases": list(dict.fromkeys(_ascii(x).lower() for x in forbidden if _ascii(x))),
        "title_seed": _title_seed(clean_topic, hook_concept, imagery or ["signal"], seed),
    }
    return {key: ([ _ascii(x) for x in value ] if isinstance(value, list) else _ascii(value)) for key, value in out.items()}
