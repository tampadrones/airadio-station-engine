from __future__ import annotations

import json
import hashlib
import re
import unicodedata
import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.prompt_builder import build_music_caption_formula, build_song_concept_prompt, build_technical_parameters, format_song_brief
from app.services.lyric_quality_gate import evaluate_lyrics_quality
from app.services.song_brief import build_song_brief
from app.services.voice_profiles import format_voice_directive

_AUTH_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TEMPLATE_PHRASES = {
    "we move through the noise with our heads held high",
    "the night keeps turning and the signal stays strong",
    "we lean into baseline, where we know we belong",
    "stay in the signal, stay in the sound",
    "we rise then settle when the beat comes around",
    "hold this moment, frame by frame, in time",
}
_LYRIC_PRODUCTION_TERMS = {
    "kick",
    "snare",
    "hi-hat",
    "hihat",
    "bpm",
    "metronome",
    "eq",
    "compressor",
    "sidechain",
}
_TOPIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "or",
    "the",
    "for",
    "with",
    "into",
    "from",
    "this",
    "that",
    "your",
    "radio",
    "station",
    "track",
    "song",
    "music",
    "custom",
    "baseline",
    "momentum",
}
_NON_LYRIC_TOPIC_HINTS = {
    "inspired",
    "vocals",
    "vocal",
    "guitar",
    "guitars",
    "drums",
    "bass",
    "tempo",
    "pulse",
    "rhythm",
    "mix",
    "texture",
    "male",
    "female",
    "rock",
    "metal",
    "industrial",
}
_REMOTE_LYRIC_PROMPT_VERSION = "cinematic-brief-v2"
_REMOTE_BANNED_FILLER_PHRASES = [
    "we rise",
    "feel alive",
    "through the night",
    "city lights",
    "signal strong",
    "hands up",
    "never let go",
    "we own the night",
    "right here right now",
]


@dataclass
class PreprocessedGeneration:
    prompt: str
    negative_prompt: str
    lyrics: str | None
    source: str
    diagnostics: dict[str, Any]
    music_caption: str = ""
    technical_parameters: dict[str, str] | None = None


def _sanitize_ascii_text(text: str, *, collapse_whitespace: bool = False) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.replace("\r\n", "\n").replace("\r", "\n")
    ascii_text = "".join(ch for ch in ascii_text if ch == "\n" or 32 <= ord(ch) <= 126)
    if collapse_whitespace:
        ascii_text = re.sub(r"\s+", " ", ascii_text)
    return ascii_text.strip()


def _finalize_lyrics_for_generator(lyrics: str | None) -> str | None:
    raw = (lyrics or "").strip()
    if not raw:
        return None

    section_pattern = re.compile(r"^\[(Intro|Verse 1|Verse 2|Pre-Chorus|Chorus|Bridge|Final Chorus|Outro)\]\s*$", re.IGNORECASE)
    colon_section_pattern = re.compile(r"^(Intro|Verse 1|Verse 2|Pre-Chorus|Chorus|Bridge|Final Chorus|Outro):\s*$", re.IGNORECASE)
    drop_patterns = (
        re.compile(r"^\s*Tone:\s*", re.IGNORECASE),
        re.compile(r"^\s*Theme anchors:\s*", re.IGNORECASE),
        re.compile(r"^\s*Style anchor:\s*", re.IGNORECASE),
        re.compile(r"^\s*Song concept:\s*", re.IGNORECASE),
        re.compile(r"^\s*Vocal profile:\s*", re.IGNORECASE),
        re.compile(r"^\s*Avoid verbatim repeats", re.IGNORECASE),
        re.compile(r"^\s*Station style:\s*", re.IGNORECASE),
        re.compile(r"^\s*Station personality:\s*", re.IGNORECASE),
        re.compile(r"^\s*Station name:\s*", re.IGNORECASE),
        re.compile(r"^\s*(Mood|Genre|Topic):\s*", re.IGNORECASE),
        re.compile(r"^\s*Keep language clean", re.IGNORECASE),
        re.compile(r"^\s*Natural language is allowed", re.IGNORECASE),
        re.compile(r"^\s*User-generated custom station\.?\s*$", re.IGNORECASE),
    )

    out_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            out_lines.append("")
            continue
        if any(p.match(stripped) for p in drop_patterns):
            continue
        m = section_pattern.match(stripped)
        if m:
            out_lines.append(f"[{m.group(1).upper()}]")
            continue
        m = colon_section_pattern.match(stripped)
        if m:
            out_lines.append(f"[{m.group(1).upper()}]")
            continue
        lowered = stripped.lower()
        if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _LYRIC_PRODUCTION_TERMS):
            continue
        out_lines.append(stripped)

    text = "\n".join(out_lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def compact_lyric_excerpt(lyrics: str | None, max_lines: int = 8) -> str:
    limit = max(0, int(max_lines))
    if limit == 0:
        return ""
    lines = []
    for raw in (lyrics or "").splitlines():
        line = " ".join(raw.strip().split())
        if not line:
            continue
        lines.append(line[:220])
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _lyrics_is_too_templatey(lyrics: str | None) -> bool:
    text = (lyrics or "").strip()
    if not text:
        return True
    lowered = text.lower()
    phrase_hits = sum(1 for phrase in _TEMPLATE_PHRASES if phrase in lowered)
    lines = [line.strip().lower() for line in text.splitlines() if line.strip() and not line.strip().endswith(":")]
    if not lines:
        return True
    unique_ratio = len(set(lines)) / max(1, len(lines))
    return phrase_hits >= 2 or unique_ratio < 0.75


def _tempo_target(genre: str, daypart: str) -> str:
    g = (genre or "").lower()
    if "trap" in g:
        return "130-155 BPM with halftime feel"
    if "synthwave" in g:
        return "95-120 BPM with steady pulse"
    if "lo-fi" in g or "lofi" in g or "chillhop" in g:
        return "72-92 BPM with relaxed swing"
    if "rock" in g or "metal" in g:
        return "110-150 BPM with live-band drive"
    if daypart in {"late_night", "night"}:
        return "80-110 BPM with lower intensity"
    return "90-130 BPM aligned with the target genre"


def _build_song_concept(
    *,
    genre: str,
    topic: str,
    daypart: str,
    mood: str,
    station_description: str,
) -> dict[str, str]:
    cleaned_topic = _clean_topic_phrase(topic) or "turning point"
    g = (genre or "").lower()
    mood_word = str(mood or "baseline").lower()
    if _is_nu_metal_like(genre=genre):
        return {
            "premise": f"a trapped narrator reliving {cleaned_topic} inside a hostile room",
            "setting": "sealed hallway, stained glass, red exit light, humming wires",
            "conflict": "the escape attempt keeps resetting and the body carries the damage",
            "images": "glass, wire, pressure, rust, flicker, breath, fracture",
            "chorus_action": "turn the failed escape into a shouted survival hook",
        }
    if "trap" in g or "rap" in g:
        return {
            "premise": f"a focused narrator turning {cleaned_topic} into leverage",
            "setting": "afterhours block, dashboard glow, locked-in studio, rain on concrete",
            "conflict": "pressure, doubt, and distractions try to break the run",
            "images": "phone light, wet pavement, clean aim, coded route, hard-earned win",
            "chorus_action": "make the hook sound like a decisive move, not a slogan",
        }
    if "synthwave" in g:
        return {
            "premise": f"a midnight driver chasing {cleaned_topic} through a neon city",
            "setting": "chrome overpass, arcade glow, rain-slick skyline, blue dashboard",
            "conflict": "nostalgia and urgency pull in opposite directions",
            "images": "neon, chrome, glass rain, cassette hiss, tail lights, horizon",
            "chorus_action": "make the chorus a cinematic turn in the road",
        }
    if "lofi" in g or "lo-fi" in g or "chillhop" in g:
        return {
            "premise": f"a quiet observer processing {cleaned_topic} in small private details",
            "setting": "desk lamp, window rain, notebook margins, sleeping apartment",
            "conflict": "old thoughts keep circling until one practical truth lands",
            "images": "paper, rain, cup steam, dim keys, soft dust, morning edge",
            "chorus_action": "keep the hook intimate and reflective",
        }
    if "rock" in g or "metal" in g:
        return {
            "premise": f"a defiant narrator confronting {cleaned_topic} at the breaking point",
            "setting": "wide road, hot stage lights, cracked asphalt, storm front",
            "conflict": "fear and fatigue push back against a last stand",
            "images": "thunder, steel, headlights, scar, smoke, open road",
            "chorus_action": "make the chorus a physical release with a clear emotional stake",
        }
    return {
        "premise": f"a character moving through {cleaned_topic} during the {daypart}",
        "setting": station_description.strip()[:120] or f"{daypart} streets with a {mood_word} emotional charge",
        "conflict": "a specific choice has to be made before the moment passes",
        "images": "light, weather, hands, room tone, distance, doorway",
        "chorus_action": "make the hook resolve the story premise in concrete language",
    }


def _concept_from_song_brief(song_brief: dict[str, Any] | None, fallback: dict[str, str]) -> dict[str, str]:
    if not isinstance(song_brief, dict) or not song_brief:
        return fallback
    imagery = song_brief.get("imagery_bank", [])
    if isinstance(imagery, list):
        image_text = ", ".join(str(x).strip() for x in imagery if str(x).strip())
    else:
        image_text = str(imagery or "").strip()
    return {
        "premise": str(song_brief.get("angle") or fallback.get("premise") or "").strip(),
        "setting": str(song_brief.get("setting") or fallback.get("setting") or "").strip(),
        "conflict": str(song_brief.get("conflict") or fallback.get("conflict") or "").strip(),
        "images": image_text or fallback.get("images") or "",
        "chorus_action": str(song_brief.get("hook_concept") or fallback.get("chorus_action") or "").strip(),
    }


def _strict_local_lyrics_from_brief(
    *,
    song_brief: dict[str, Any],
    genre: str,
    voice_profile: dict[str, Any] | None,
) -> str:
    _ = (genre, voice_profile)
    topic = str(song_brief.get("topic") or "turning point").strip()
    narrator = str(song_brief.get("narrator") or "first-person narrator").strip()
    setting = str(song_brief.get("setting") or "a specific room before dawn").strip()
    conflict = str(song_brief.get("conflict") or "one honest choice has a cost").strip()
    emotional_turn = str(song_brief.get("emotional_turn") or "fear becomes a named cost").strip()
    hook = str(song_brief.get("hook_concept") or "the hook answers the conflict directly").strip()
    strategy = str(song_brief.get("chorus_strategy") or "repeat one concrete image with a changed final line").strip()
    imagery = song_brief.get("imagery_bank", [])
    if not isinstance(imagery, list):
        imagery = []
    images = [str(x).strip() for x in imagery if str(x).strip()]
    while len(images) < 6:
        images.append(["doorway", "weather", "hands", "window", "receipt", "last call"][len(images)])
    title_seed = str(song_brief.get("title_seed") or topic.title()).strip()
    return (
        "[INTRO]\n"
        f"{images[0].title()} marks the place where {topic} begins\n\n"
        "[VERSE 1]\n"
        f"I speak as {narrator}\n"
        f"The scene is {setting}\n"
        f"{images[1].title()} catches on my sleeve while I count the cost\n"
        f"{conflict.capitalize()}\n\n"
        "[PRE-CHORUS]\n"
        f"{images[2].title()} gives the warning I ignored\n"
        f"{emotional_turn.capitalize()}\n\n"
        "[CHORUS]\n"
        f"{title_seed} is the name I give the turn\n"
        f"{hook.capitalize()}\n"
        f"{images[3].title()} stays with me when the room goes quiet\n"
        f"I choose the cost before it chooses me\n\n"
        "[VERSE 2]\n"
        f"The proof sits there in {images[4]} and breath\n"
        f"I stop pretending {topic} is only a mood\n"
        f"{setting.capitalize()} will remember what I did\n"
        f"{conflict.capitalize()} but I keep moving\n\n"
        "[BRIDGE]\n"
        f"{strategy.capitalize()}\n"
        f"{images[5].title()} turns the silence into evidence\n"
        f"{emotional_turn.capitalize()}\n\n"
        "[FINAL CHORUS]\n"
        f"{title_seed} is the mark I carry out\n"
        f"{hook.capitalize()} before the fade\n"
        f"{images[0].title()} answers back in a different light\n"
        f"I choose the cost and leave with proof\n\n"
        "[OUTRO]\n"
        f"{images[1].title()} fades behind the last door\n"
        f"{topic.title()} finally has a shape\n"
    )


def _build_lyrics_draft(
    *,
    genre: str,
    personality: str,
    station_name: str,
    station_description: str,
    daypart: str,
    mood: str,
    station_profile: dict[str, Any],
    song_topic: str,
    variation_salt: str,
    recent_tracks: list[dict[str, Any]],
    voice_profile: dict[str, Any] | None = None,
    song_brief: dict[str, Any] | None = None,
) -> str | None:
    lyrics_mode = str(station_profile.get("lyrics_mode", "mixed"))
    if lyrics_mode == "instrumental_only":
        return None

    clean_only = bool(station_profile.get("clean_lyrics_only", True))
    topics = station_profile.get("topic_ideas", [])
    topic_list = [str(x).strip() for x in (topics or []) if str(x).strip()][:4]
    safety = "Keep language clean and radio-safe." if clean_only else "Natural language is allowed; avoid gratuitous explicit content."
    topic_suffix = f"Theme anchors: {', '.join(topic_list)}." if topic_list else f"Theme anchors: {song_topic}."
    primary_topic = song_topic.strip() or "momentum"
    fallback_concept = _build_song_concept(
        genre=genre,
        topic=primary_topic,
        daypart=daypart,
        mood=mood,
        station_description=station_description,
    )
    concept = _concept_from_song_brief(song_brief, fallback_concept)
    concept_images = [x.strip() for x in concept["images"].split(",") if x.strip()]
    image_a = concept_images[0] if concept_images else "light"
    image_b = concept_images[1] if len(concept_images) > 1 else "weather"
    voice_directive = format_voice_directive(voice_profile)

    intro_lines = [
        f"Street lamps bloom while the {daypart} air turns electric",
        f"Concrete glows as the {daypart} rush comes alive",
        f"Window lights paint the avenue in restless color",
        f"Headlights trace the skyline as the pulse locks in",
        f"The city exhales and the speakers catch the spark",
        f"Midnight static fades and the rhythm takes control",
    ]
    verse_openers = [
        f"{primary_topic.title()} starts as {concept['premise']}",
        f"I step into {primary_topic} with {concept['conflict']}",
        f"The first sign of {primary_topic} cuts through {concept['setting']}",
        f"{primary_topic.title()} presses close until the choice gets clear",
        f"I follow {primary_topic} past the point where old excuses hold",
        f"{primary_topic.title()} leaves its mark in {image_a} and breath",
    ]
    pre_lifts = [
        "One hard inhale and the room starts to levitate",
        "When the floor shakes, every heartbeat aligns",
        "No looking back once the pressure flips to gold",
        "We lock the timing and the whole block wakes up",
        "The voltage climbs and every signal turns green",
        "One more second and we break into flight",
    ]
    bridge_lines = [
        f"No safe route now, {concept['conflict']}",
        f"I name {primary_topic} in the place where {concept['setting']} closes in",
        f"Every image comes back sharp: {concept['images']}",
        f"We cross the limit line and make {primary_topic} answer back",
        f"The room leans in as {primary_topic} turns specific and loud",
        f"{concept['chorus_action'].capitalize()}",
    ]
    genre_motifs = {
        "synthwave": ["neon glass", "analog glow", "midnight skyline", "chrome horizon"],
        "rock": ["open highway", "burning amplifiers", "thunder drums", "wide-screen chorus"],
        "trap": ["808 pressure", "dark room pulse", "late-night focus", "streetlight cadence"],
    }

    g = genre.lower()
    motifs = ["city static", "night drive", "signal flare", "afterhours air", "neon dust", "fast-lane focus"]
    for key, words in genre_motifs.items():
        if key in g:
            motifs = words
            break
    recent_titles = [str(item.get("title", "")).strip() for item in (recent_tracks or []) if str(item.get("title", "")).strip()]
    recent_hint = ", ".join(recent_titles[:3])
    mood_terms = {
        "baseline": ["steady", "locked", "grounded", "focused"],
        "rise": ["climbing", "expanding", "opening", "ascending"],
        "peak": ["blazing", "maximum", "unstoppable", "electric"],
        "release": ["weightless", "cooldown", "echoing", "floating"],
    }
    mood_words = mood_terms.get(str(mood).lower(), ["steady", "focused", "alive", "bright"])
    action_lines = [
        f"I trace the proof through {image_a} and keep it close",
        f"Every line points back to {concept['premise']}",
        f"The pressure names itself: {concept['conflict']}",
        f"I hold the scene in focus until the hook cuts deeper",
        f"The chorus has a job now: {concept['chorus_action']}",
        f"No filler, only the detail that makes {primary_topic} feel lived in",
    ]
    outro_lines = [
        "Tail lights fade but the fire in us stays lit",
        "We leave the echo rolling through the avenue",
        "The room goes dark while the heartbeat keeps time",
        "Night closes in and the signal still feels alive",
        "We drift to silence with the skyline still glowing",
        "The station breathes and the last chord hangs bright",
    ]

    def pick(options: list[str], label: str) -> str:
        if not options:
            return ""
        key = f"{genre}|{personality}|{daypart}|{mood}|{primary_topic}|{variation_salt}|{label}"
        digest = hashlib.sha1(key.encode("utf-8")).digest()
        idx = digest[0] % len(options)
        return options[idx]

    def pick_unique(options: list[str], label: str, count: int) -> list[str]:
        if not options or count <= 0:
            return []
        key = f"{genre}|{personality}|{daypart}|{mood}|{primary_topic}|{variation_salt}|{label}"
        digest = hashlib.sha1(key.encode("utf-8")).digest()
        start = digest[0] % len(options)
        ordered = options[start:] + options[:start]
        if digest[1] % 2 == 1:
            ordered = list(reversed(ordered))
        return ordered[: min(count, len(options))]

    if _is_nu_metal_like(genre=genre, taste_hints=station_profile.get("taste_hints", [])):
        intro_lines = [
            "Glass walls breathe while the hallway hums in red light",
            "Cold neon leaks through the cracks in the sealed room",
            "Steel air presses down and the ceiling starts to bend",
            "Static crawls the wires while the exit sign flickers blind",
        ]
        verse_1_lines = [
            f"{primary_topic.title()} lives under the skin like a live wire",
            "My shadow drags chains through the fluorescent haze",
            "Every locked door throws my name back in my face",
            "The mirror shakes but never breaks clean enough to crawl through",
        ]
        pre_lines = [
            "I feel the pressure counting down inside my teeth",
            "One more pulse and the whole frame starts to split",
            "The room folds in and I still push against it",
            "Every breath tastes like sparks and rust",
        ]
        chorus_lines = [
            "Pull me out of the glass",
            "Cut the loop before it closes",
            "I keep waking in the same black bloom",
            "Every exit seals itself around me",
        ]
        verse_2_lines = [
            "The walls learn my shape and tighten when I move",
            "I leave fingerprints in the dust where the light goes dead",
            "My pulse kicks back through the wires in the floor",
            "I drag this damaged engine through another failed escape",
        ]
        bridge_lines = [
            "If I break the frame, I break with it",
            "No clean horizon, just shattered signal and breath",
            f"{primary_topic.title()} turns the fracture into a mouth",
            "I bite down hard enough to hear the circuit scream",
        ]
        outro_lines = [
            "The red light fades but the pressure stays awake",
            "I hear the lock turn slow inside the dark",
            "No clean release, only static and heat",
            "The room goes black and the echo keeps my shape",
        ]
        verse_1 = pick_unique(verse_1_lines, "nm-v1", 4)
        verse_2 = pick_unique(verse_2_lines, "nm-v2", 4)
        pre_1 = pick_unique(pre_lines, "nm-pre-a", 2)
        pre_2 = pick_unique(pre_lines, "nm-pre-b", 2)
        chorus_1 = pick_unique(chorus_lines, "nm-chorus-a", 4)
        chorus_2 = pick_unique(chorus_lines, "nm-chorus-b", 4)
        bridge = pick_unique(bridge_lines, "nm-bridge", 3)
        outro = pick_unique(outro_lines, "nm-outro", 2)
        final_chorus = pick_unique(chorus_lines, "nm-final-chorus", 4)
        return (
            f"[INTRO]\n"
            f"{pick(intro_lines, 'nm-intro')}\n\n"
            f"[VERSE 1]\n"
            f"{chr(10).join(verse_1)}\n\n"
            f"[PRE-CHORUS]\n"
            f"{chr(10).join(pre_1)}\n\n"
            f"[CHORUS]\n"
            f"{chr(10).join(chorus_1)}\n\n"
            f"[VERSE 2]\n"
            f"{chr(10).join(verse_2)}\n\n"
            f"[PRE-CHORUS]\n"
            f"{chr(10).join(pre_2)}\n\n"
            f"[CHORUS]\n"
            f"{chr(10).join(chorus_2)}\n\n"
            f"[BRIDGE]\n"
            f"{chr(10).join(bridge)}\n\n"
            f"[FINAL CHORUS]\n"
            f"{chr(10).join(final_chorus)}\n\n"
            f"[OUTRO]\n"
            f"{chr(10).join(outro)}\n"
        )

    return (
        f"[Intro]\n"
        f"{pick(intro_lines, 'intro')}\n\n"
        f"[Verse 1]\n"
        f"{pick(verse_openers, 'verse1-open')}\n"
        f"{pick(action_lines, 'verse1-action')}\n"
        f"{pick(mood_words, 'verse1-mood').capitalize()} energy holds the lane while the streetlights roll\n"
        f"{pick(motifs, 'motif-v1a').capitalize()} colors the frame and keeps us moving\n"
        f"{pick(motifs, 'motif-v1b').capitalize()} frames the scene while {personality} holds the line\n"
        f"\n[Pre-Chorus]\n"
        f"{pick(pre_lifts, 'pre1')}\n"
        f"Every mile pulls the focus in tighter tonight\n\n"
        f"[Chorus]\n"
        f"{primary_topic.title()} has a face in the window light\n"
        f"{concept['conflict'].capitalize()} but I do not fold\n"
        f"{concept['chorus_action'].capitalize()}\n"
        f"I can name the cost and still keep hold\n\n"
        f"[Verse 2]\n"
        f"Street signs blur and the whole block tilts forward\n"
        f"We push {primary_topic} until hesitation breaks\n"
        f"{pick(action_lines, 'verse2-action')}\n"
        f"{pick(mood_words, 'verse2-mood').capitalize()} pressure keeps the chorus in our grip\n"
        f"{pick(motifs, 'motif-v2').capitalize()} keeps the station moving bold and bright\n\n"
        f"[Pre-Chorus]\n"
        f"{pick(pre_lifts, 'pre2')}\n"
        f"Every echo says we are alive tonight\n\n"
        f"[Chorus]\n"
        f"{primary_topic.title()} leaves a mark I recognize\n"
        f"{image_b.capitalize()} keeps shining through the cold\n"
        f"{concept['chorus_action'].capitalize()}\n"
        f"I can name the cost and still keep hold\n\n"
        f"[Bridge]\n"
        f"{pick(bridge_lines, 'bridge')}\n"
        f"{topic_suffix}\n"
        f"Song concept: {concept['premise']}; {concept['setting']}; {concept['conflict']}.\n"
        f"{voice_directive}\n"
        f"Style anchor: {station_name} with {personality} tone.\n"
        f"Avoid verbatim repeats from recent titles: {recent_hint or 'none'}.\n"
        f"{safety}\n"
        f"\n[Final Chorus]\n"
        f"{primary_topic.title()} answers back in {image_a} and {image_b}\n"
        f"The cost is clear, the last doubt loses hold\n"
        f"{concept['chorus_action'].capitalize()} before the fade\n"
        f"I carry the proof into the last note\n\n"
        f"[Outro]\n"
        f"{pick(outro_lines, 'outro1')}\n"
        f"{pick(outro_lines, 'outro2')}\n"
    )


def _build_local_prompt(
    *,
    base_prompt: str,
    music_caption: str,
    technical_parameters: dict[str, str],
    genre: str,
    daypart: str,
    mood: str,
    station_profile: dict[str, Any],
    lyrics: str | None,
    chosen_topic: str,
    song_brief: dict[str, Any] | None = None,
    voice_profile: dict[str, Any] | None = None,
) -> str:
    _ = (base_prompt, genre, daypart, mood, station_profile, chosen_topic)
    return build_song_concept_prompt(
        music_caption=music_caption,
        technical_parameters=technical_parameters,
        lyrics=lyrics,
        song_brief=song_brief,
        voice_profile=voice_profile,
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


async def _try_remote_refine(
    *,
    base_urls: list[str],
    model: str,
    api_key: str | None,
    auth_email: str | None,
    auth_password: str | None,
    timeout_seconds: int,
    base_prompt: str,
    local_prompt: str,
    negative_prompt: str,
    lyrics: str | None,
    lyrics_mode: str,
    context_payload: dict[str, Any],
) -> PreprocessedGeneration | None:
    system = (
        "You are a music-prompt refiner for AI song generation. "
        "Return strict JSON only with keys: music_caption, technical_parameters, negative_prompt, lyrics. "
        "If lyrics should be instrumental-only, return empty string for lyrics. "
        "music_caption must remain a single-line, comma-separated creative prompt using this order: "
        "genre/style, influence/artist comparison, mood/energy, sonic texture, theme/story, "
        "setting/visual imagery, vocal style, rhythm/pace. "
        "technical_parameters must be an object with Key, BPM, Time Signature, Duration, Energy Level, "
        "Structure Density, and optional Subgenre Tags, Instrumentation, Dynamic Arc, Mix Texture. "
        "Duration must use M:SS. BPM must be numeric. Energy Level must be Low, Medium, High, or Extreme. "
        "Structure Density must be Sparse, Balanced, or Dense. "
        "lyrics must use [INTRO], [VERSE 1], optional [PRE-CHORUS], [CHORUS], [VERSE 2], "
        "optional [PRE-CHORUS], [CHORUS], [BRIDGE], [FINAL CHORUS], [OUTRO]. "
        "Use English words with ASCII characters only."
    )
    user_payload = {
        "base_prompt": base_prompt,
        "local_prompt": local_prompt,
        "negative_prompt": negative_prompt,
        "lyrics": lyrics or "",
        "station_context": context_payload,
    }

    for raw_url in base_urls:
        base_url = raw_url.strip().rstrip("/")
        if not base_url:
            continue
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                payload = {
                    "model": model,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(user_payload)},
                    ],
                }
                headers = {"Content-Type": "application/json"}
                token = _get_cached_auth_token(base_url)
                auth_value = token or api_key
                if auth_value:
                    headers["Authorization"] = f"Bearer {auth_value}"

                resp = await client.post(f"{base_url}/api/chat/completions", headers=headers, json=payload)
                if resp.status_code == 401 and auth_email and auth_password:
                    token = await _signin_openwebui_token(
                        client=client,
                        base_url=base_url,
                        auth_email=auth_email,
                        auth_password=auth_password,
                    )
                    if token:
                        headers["Authorization"] = f"Bearer {token}"
                        resp = await client.post(f"{base_url}/api/chat/completions", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            choices = data.get("choices", []) if isinstance(data, dict) else []
            if not choices:
                continue
            message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
            content = message.get("content", "") if isinstance(message, dict) else ""
            parsed = _extract_json(content if isinstance(content, str) else "")
            if not parsed:
                continue
            music_caption = str(parsed.get("music_caption", "")).strip()
            technical_raw = parsed.get("technical_parameters", {})
            technical_parameters = {
                str(k): str(v).strip()
                for k, v in (technical_raw.items() if isinstance(technical_raw, dict) else [])
                if str(k).strip() and str(v).strip()
            }
            refined_neg = str(parsed.get("negative_prompt", "")).strip() or negative_prompt
            refined_lyrics = str(parsed.get("lyrics", "")).strip() or None
            if lyrics_mode == "instrumental_only":
                refined_lyrics = None
            if not music_caption:
                continue
            return PreprocessedGeneration(
                prompt=music_caption,
                negative_prompt=refined_neg,
                lyrics=refined_lyrics,
                source=f"openwebui:{base_url}",
                diagnostics={"provider": "openwebui", "model": model},
                music_caption=music_caption,
                technical_parameters=technical_parameters,
            )
        except Exception:
            continue
    return None


def _clean_topic_phrase(value: str) -> str:
    raw = " ".join(str(value or "").split()).strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _LYRIC_PRODUCTION_TERMS):
        return ""
    parts = [p for p in re.findall(r"[A-Za-z0-9']+", raw) if p]
    kept = [p for p in parts if p.lower() not in _TOPIC_STOPWORDS]
    if not kept:
        return ""
    text = " ".join(kept[:6]).strip()
    return text if len(text) >= 3 else ""


def _is_usable_topic_hint(value: str) -> bool:
    lowered = str(value or "").lower()
    return not any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _NON_LYRIC_TOPIC_HINTS)


def _dedupe_lower(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _genre_topic_fallbacks(genre: str) -> list[str]:
    g = (genre or "").lower()
    if "trap" in g or "rap" in g:
        return [
            "late night hustle",
            "city ambition",
            "pressure into power",
            "afterhours focus",
            "victory lap",
            "from doubt to dominance",
        ]
    if _is_nu_metal_like(genre=genre):
        return [
            "failed escape cycle",
            "psychological entrapment",
            "glass city breakdown",
            "pressure in the wires",
            "fractured identity",
            "static in the blood",
        ]
    if "rock" in g or "metal" in g:
        return [
            "against the storm",
            "breaking point",
            "scar tissue resolve",
            "last stand confession",
            "pressure on the chest",
            "teeth against the dark",
        ]
    if "synthwave" in g:
        return [
            "neon skyline chase",
            "midnight arcade romance",
            "chrome horizon",
            "retro future escape",
            "city lights confession",
            "night drive signal",
        ]
    if "lofi" in g or "lo-fi" in g or "chillhop" in g:
        return [
            "quiet desk reflections",
            "rain on window glass",
            "soft focus memories",
            "slow morning reset",
            "letters never sent",
            "late night journaling",
        ]
    return [
        "city lights",
        "new beginnings",
        "long road home",
        "midnight stories",
        "quiet confidence",
        "afterhours stories",
    ]


def _daypart_topic_fallbacks(daypart: str) -> list[str]:
    d = (daypart or "").lower()
    if d in {"morning", "early_morning"}:
        return ["sunrise reset", "fresh start", "first light ambition"]
    if d in {"afternoon"}:
        return ["midday focus", "forward motion", "second wind"]
    if d in {"evening"}:
        return ["city afterglow", "golden hour release", "streetlight stories"]
    if d in {"night", "late_night"}:
        return ["midnight drive", "afterhours confession", "moonlit resolve"]
    return []


def _mood_topic_fallbacks(mood: str) -> list[str]:
    m = (mood or "").lower()
    if m == "rise":
        return ["breaking through", "turning point", "climbing higher"]
    if m == "peak":
        return ["no limits", "all in tonight", "center of the storm"]
    if m == "release":
        return ["letting go", "quiet aftermath", "dawn after the rush"]
    return ["steady confidence", "holding the line", "keep moving forward"]


def _recent_topic_keys(recent_tracks: list[dict[str, Any]] | None) -> set[str]:
    keys: set[str] = set()
    for item in recent_tracks or []:
        if not isinstance(item, dict):
            continue
        for field in ("topic", "song_topic"):
            cleaned = _clean_topic_phrase(str(item.get(field, "")))
            if cleaned:
                keys.add(cleaned.lower())
    return keys


def _choose_song_topic(
    station_profile: dict[str, Any],
    mood: str,
    *,
    genre: str = "",
    daypart: str = "",
    recent_tracks: list[dict[str, Any]] | None = None,
    salt: str = "",
) -> str:
    topics = station_profile.get("topic_ideas", [])
    taste_hints = station_profile.get("taste_hints", [])
    explicit_topics: list[str] = []
    if isinstance(topics, list):
        explicit_topics = [_clean_topic_phrase(str(item)) for item in topics if str(item).strip()]
        explicit_topics = [x for x in explicit_topics if x]
    candidates: list[str] = []
    if isinstance(taste_hints, list):
        candidates.extend(
            [
                _clean_topic_phrase(str(item))
                for item in taste_hints
                if str(item).strip() and _is_usable_topic_hint(str(item))
            ]
        )

    recent_keys = _recent_topic_keys(recent_tracks)
    if explicit_topics:
        base_pool = _dedupe_lower(explicit_topics)
    else:
        is_nu_metal = _is_nu_metal_like(genre=genre, taste_hints=taste_hints if isinstance(taste_hints, list) else None)
        candidates.extend([_clean_topic_phrase(x) for x in _genre_topic_fallbacks(genre)])
        if not is_nu_metal:
            candidates.extend([_clean_topic_phrase(x) for x in _daypart_topic_fallbacks(daypart)])
            candidates.extend([_clean_topic_phrase(x) for x in _mood_topic_fallbacks(mood)])
        base_pool = _dedupe_lower([x for x in candidates if x])

    fresh = [x for x in base_pool if x.lower() not in recent_keys]
    pool = fresh or base_pool
    if not pool:
        pool = [f"{(genre or mood or 'night').strip()} energy".strip()]

    seed_src = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}|{mood}|{genre}|{daypart}|{salt}|{'|'.join(pool)}"
    digest = hashlib.sha1(seed_src.encode("utf-8")).digest()
    idx = digest[0] % len(pool)
    base_topic = pool[idx]

    if explicit_topics and base_topic.lower() in {x.lower() for x in explicit_topics} and isinstance(taste_hints, list):
        refined_hints = [h for h in (_clean_topic_phrase(str(x)) for x in taste_hints) if h]
        for hint in refined_hints:
            if hint.lower() == base_topic.lower():
                continue
            if hint.lower() in base_topic.lower() or base_topic.lower() in hint.lower():
                continue
            merged = f"{base_topic} {hint}".strip()
            if len(merged) <= 64:
                return merged
            break
    return base_topic


def _suggest_song_title(*, station_name: str, topic: str, daypart: str) -> str:
    seed = topic.strip() or f"{station_name} {daypart}"
    tokens = re.findall(r"[A-Za-z0-9']+", seed)
    if not tokens:
        return f"{station_name} Signal"
    clipped = tokens[:6]
    return " ".join(word.capitalize() for word in clipped)


def suggest_track_title(
    *,
    genre: str,
    mood: str,
    topic: str,
    daypart: str,
    personality: str,
    salt: str,
) -> str:
    topic_tokens = re.findall(r"[A-Za-z0-9']+", topic or "")
    mood_tokens = re.findall(r"[A-Za-z0-9']+", mood or "")
    daypart_tokens = re.findall(r"[A-Za-z0-9']+", daypart or "")
    persona_tokens = re.findall(r"[A-Za-z0-9']+", personality or "")

    banned = {"custom", "baseline", "track", "station", "host", "radio", "music", "song"}
    filtered_topic = [t for t in topic_tokens if t.lower() not in banned]

    g = (genre or "").lower()
    fallback_by_genre = {
        "trap": ["Respawn", "Raid", "Overclock", "Speedrun"],
        "rock": ["Afterburn", "Thunderline", "Steelheart", "Voltage"],
        "synthwave": ["Afterglow", "Neonline", "Night Drive", "Static Sky"],
        "lofi": ["Low Tide", "Soft Focus", "Night Window", "Quiet Circuit"],
    }
    if filtered_topic:
        base_topic = " ".join(filtered_topic[:3]).title()
    else:
        if "trap" in g or "rap" in g:
            base_topic = "Respawn"
        elif _is_nu_metal_like(genre=genre):
            base_topic = "Afterburn"
        elif "rock" in g or "metal" in g:
            base_topic = "Afterburn"
        elif "synthwave" in g:
            base_topic = "Afterglow"
        elif "lofi" in g or "lo-fi" in g:
            base_topic = "Soft Focus"
        else:
            base_topic = "Signal"

    mood_alias = {
        "baseline": "Steady",
        "rise": "Lift",
        "peak": "Surge",
        "release": "Afterglow",
    }
    raw_mood = mood_tokens[0].lower() if mood_tokens else ""
    mood_word = mood_alias.get(raw_mood, mood_tokens[0].title() if mood_tokens else "Pulse")
    daypart_word = (daypart_tokens[0].title() if daypart_tokens else "Night")
    persona_word = (persona_tokens[0].title() if persona_tokens else "Radio")

    if "trap" in g or "rap" in g:
        suffixes = ["Raid", "Overclock", "Respawn", "Bossfight"]
    elif _is_nu_metal_like(genre=genre):
        suffixes = ["Voltage", "Collapse", "Blackglass", "Afterburn"]
    elif "rock" in g or "metal" in g:
        suffixes = ["Anthem", "Ignition", "Voltage", "Afterburn"]
    elif "synthwave" in g:
        suffixes = ["Neon", "Drive", "Afterglow", "Midnight"]
    else:
        suffixes = ["Signal", "Motion", "Drift", "Echo"]

    digest = hashlib.sha1(f"{genre}|{mood}|{topic}|{daypart}|{personality}|{salt}".encode("utf-8")).digest()
    extra = []
    for key, words in fallback_by_genre.items():
        if key in g:
            extra = words
            break
    suffix_pool = suffixes + extra
    suffix = suffix_pool[digest[0] % len(suffix_pool)]
    variant = digest[1] % 4
    candidates = [
        f"{base_topic} {suffix}",
        f"{daypart_word} {base_topic}",
        f"{base_topic} {mood_word}",
        f"{base_topic} {persona_word}",
    ]
    title = candidates[variant]
    title = re.sub(r"\s+", " ", title).strip()
    if title.lower() in banned:
        title = f"{base_topic} {suffix}"
    return title[:80] or "Untitled Signal"


def _extract_chat_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices", []) if isinstance(data, dict) else []
    if not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message", {})
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip() or None
    return None


def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return cleaned


_REMOTE_LYRIC_LIST_TYPES = {
    "lyric",
    "lyrics",
    "line",
    "verse",
    "chorus",
    "bridge",
    "pre-chorus",
    "prechorus",
    "intro",
    "outro",
    "final chorus",
    "final_chorus",
}


def _looks_like_chord_token(value: str) -> bool:
    text = value.strip()
    return bool(re.match(r"^[A-G](?:#|b)?m?(?:maj|min|dim|aug|sus|add)?\d*(?:/[A-G](?:#|b)?)?$", text))


def _lyrics_payload_to_text(raw_lyrics: Any) -> tuple[str, str]:
    if isinstance(raw_lyrics, str):
        return raw_lyrics.strip(), "string"
    if isinstance(raw_lyrics, dict):
        ordered_sections = [
            "[INTRO]",
            "[VERSE 1]",
            "[PRE-CHORUS]",
            "[CHORUS]",
            "[VERSE 2]",
            "[PRE-CHORUS 2]",
            "[CHORUS 2]",
            "[BRIDGE]",
            "[FINAL CHORUS]",
            "[OUTRO]",
        ]
        blocks: list[str] = []
        consumed: set[str] = set()
        for section in ordered_sections:
            for key, value in raw_lyrics.items():
                normalized_key = str(key).strip().upper()
                target_key = section.upper()
                if normalized_key in {"[PRE-CHORUS 2]", "[PRE-CHORUS TWO]"}:
                    normalized_key = "[PRE-CHORUS]"
                if normalized_key in {"[CHORUS 2]", "[CHORUS TWO]"}:
                    normalized_key = "[CHORUS]"
                if normalized_key != target_key or normalized_key in consumed:
                    continue
                line_text = str(value).strip()
                if line_text:
                    blocks.append(f"{target_key}\n{line_text}")
                    consumed.add(normalized_key)
                    break
        if not blocks:
            for key, value in raw_lyrics.items():
                normalized_key = str(key).strip().upper()
                line_text = str(value).strip()
                if normalized_key and line_text:
                    blocks.append(f"{normalized_key}\n{line_text}")
        return "\n\n".join(blocks).strip(), "dict"
    if isinstance(raw_lyrics, list):
        if all(isinstance(item, str) for item in raw_lyrics):
            lines = [str(item).strip() for item in raw_lyrics if str(item).strip() and not _looks_like_chord_token(str(item))]
            return "\n".join(lines).strip(), "list_strings"
        if all(isinstance(item, dict) for item in raw_lyrics):
            lines = []
            for item in raw_lyrics:
                kind = str(item.get("type", "") or item.get("section", "") or "").strip().lower()
                line_text = str(item.get("text", "")).strip()
                if not line_text or kind not in _REMOTE_LYRIC_LIST_TYPES:
                    continue
                if kind in {"chord", "metadata", "meta", "key", "tempo"} or _looks_like_chord_token(line_text):
                    continue
                lines.append(line_text)
            return "\n".join(lines).strip(), "list_text_objects"
        return "", "unknown"
    return "", "unknown"


def _extract_title_lyrics_and_shape(text: str) -> tuple[str | None, str, str]:
    cleaned = _strip_code_fence(text or "")
    if not cleaned:
        return None, "", "unknown"

    # JSON path: {"title":"...","lyrics":"..."}
    try:
        payload = json.loads(cleaned)
    except Exception:
        payload = None
    if isinstance(payload, dict):
        title = str(payload.get("title", "")).strip() or None
        lyrics, shape = _lyrics_payload_to_text(payload.get("lyrics", ""))
        return title, lyrics, shape

    # Plain-text path: first line starts with "Title:".
    lines = [ln.rstrip() for ln in cleaned.splitlines()]
    if lines:
        m = re.match(r"^\s*title\s*:\s*(.+?)\s*$", lines[0], flags=re.IGNORECASE)
        if m:
            title = m.group(1).strip() or None
            lyrics = "\n".join(lines[1:]).strip()
            return title, lyrics, "string"

    return None, cleaned, "string"


def _extract_title_and_lyrics(text: str) -> tuple[str | None, str]:
    title, lyrics, _shape = _extract_title_lyrics_and_shape(text)
    return title, lyrics


def _derive_lyric_style_guidance(*, genre: str, taste_hints: list[str] | None, mood: str) -> str:
    hints = [str(x).strip() for x in (taste_hints or []) if str(x).strip()]
    filtered: list[str] = []
    for item in hints:
        low = item.lower()
        if any(re.search(rf"\b{re.escape(term)}\b", low) for term in _LYRIC_PRODUCTION_TERMS):
            continue
        filtered.append(item)

    g = (genre or "").lower()
    if "rock" in g or "metal" in g:
        fallback = "anthemic, rebellious, road-trip energy, big emotional hooks"
    elif "synthwave" in g:
        fallback = "cinematic neon mood, nostalgic romance, night-drive atmosphere"
    elif "trap" in g or "rap" in g:
        fallback = "confident, gritty, streetwise focus, sharp punchlines"
    elif "lofi" in g or "lo-fi" in g:
        fallback = "introspective, calm, late-night reflection, soft imagery"
    else:
        fallback = f"{mood} emotional tone with genre-appropriate imagery"

    if not filtered:
        return fallback
    return ", ".join(filtered[:4])


def _is_nu_metal_like(*, genre: str, taste_hints: list[str] | None = None) -> bool:
    haystacks = [str(genre or "").lower()]
    haystacks.extend(str(x).lower() for x in (taste_hints or []) if str(x).strip())
    joined = " | ".join(haystacks)
    return any(token in joined for token in ["nu-metal", "numetal", "alternative metal", "industrial rock", "deftones", "nine inch nails"])


def _genre_lyric_direction(*, genre: str, taste_hints: list[str] | None, mood: str) -> tuple[str, str]:
    if _is_nu_metal_like(genre=genre, taste_hints=taste_hints):
        return (
            "Use tense, physical, claustrophobic imagery with short punchy lines, internal conflict, mechanical pressure, fractured glass, neon haze, failed escape, and strained human vulnerability.",
            "Avoid romantic night-drive language, optimistic skyline slogans, clean pop uplift, and generic city-lights freedom imagery.",
        )
    g = (genre or "").lower()
    if "rock" in g or "metal" in g:
        return (
            "Use concrete, visceral rock imagery with tension, motion, impact, and a strong emotional hook.",
            "Avoid dreamy synth-pop romance language, generic nightlife slogans, and lightweight self-help phrasing.",
        )
    if "synthwave" in g:
        return (
            "Lean into cinematic nocturnal imagery, chrome light, longing, velocity, and widescreen momentum.",
            "Avoid gritty metal aggression, rap brags, and stripped acoustic confessionals.",
        )
    if "trap" in g or "rap" in g:
        return (
            "Use sharp, direct, high-confidence language with pressure, ambition, and focused detail.",
            "Avoid arena-rock slogans, soft dream-pop abstraction, and nostalgic retro romance.",
        )
    return (
        f"Keep the imagery and line shape authentic to {genre} with a {mood} emotional arc.",
        "Avoid drifting into unrelated genre language or generic radio-safe platitudes.",
    )


def _lyric_bpm_range(genre: str, daypart: str) -> tuple[int, int]:
    g = (genre or "").lower()
    if "trap" in g or "rap" in g:
        return (132, 156)
    if "synthwave" in g:
        return (96, 122)
    if "lofi" in g or "lo-fi" in g or "chillhop" in g:
        return (72, 96)
    if "rock" in g or "metal" in g:
        return (108, 150)
    if daypart in {"late_night", "night"}:
        return (82, 112)
    return (92, 132)


def _lyric_keyscale_hint(*, genre: str, mood: str, topic: str, variation_salt: str) -> str:
    g = (genre or "").lower()
    mood_is_bright = str(mood).lower() in {"rise", "peak"}
    if "trap" in g or "rap" in g:
        pool = ["F minor", "D minor", "G minor", "A minor", "C minor"]
    elif "synthwave" in g:
        pool = ["D major", "A minor", "E minor", "G major", "B minor"]
    elif "lofi" in g or "lo-fi" in g:
        pool = ["C major", "A minor", "D minor", "F major", "E minor"]
    elif "rock" in g or "metal" in g:
        pool = ["E minor", "A minor", "D minor", "G major", "B minor"]
    else:
        pool = ["D minor", "A minor", "C major", "G major"]
    if mood_is_bright:
        pool = [k for k in pool if "major" in k.lower()] + [k for k in pool if "minor" in k.lower()]
    digest = hashlib.sha1(f"{genre}|{mood}|{topic}|{variation_salt}".encode("utf-8")).digest()
    return pool[digest[0] % len(pool)]


def _lyric_target_duration_sec(*, station_profile: dict[str, Any], genre: str, mood: str, lyrics_mode: str) -> int:
    base = int(station_profile.get("target_duration_sec", 320))
    if str(lyrics_mode) == "instrumental_only":
        base = max(150, base - 8)
    elif str(lyrics_mode) == "vocal_forward":
        base = min(320, base + 8)
    mood_offsets = {"baseline": 0, "rise": -6, "peak": -12, "release": 10}
    base += int(mood_offsets.get(str(mood).lower(), 0))
    min_sec = int(station_profile.get("duration_min_sec", 320))
    max_sec = int(station_profile.get("duration_max_sec", 320))
    min_sec = max(120, min(min_sec, 320))
    max_sec = max(120, min(max_sec, 320))
    if min_sec > max_sec:
        min_sec, max_sec = max_sec, min_sec
    base = max(min_sec, min(max_sec, base))
    return max(150, min(320, base))


def _build_lyric_constraints(
    *,
    station_profile: dict[str, Any],
    genre: str,
    daypart: str,
    mood: str,
    topic: str,
    variation_salt: str,
) -> dict[str, Any]:
    bpm_lo, bpm_hi = _lyric_bpm_range(genre, daypart)
    lyrics_mode = str(station_profile.get("lyrics_mode", "mixed"))
    vocal_ratio = int(station_profile.get("vocal_ratio", 40))
    cohesion = int(station_profile.get("cohesion_spectrum", 80))
    discovery = int(station_profile.get("discovery_depth", 20))
    mood_vol = int(station_profile.get("mood_volatility", 30))
    energy_var = int(station_profile.get("energy_variability", 30))
    return {
        "tempo_range_bpm": f"{bpm_lo}-{bpm_hi}",
        "key_hint": _lyric_keyscale_hint(genre=genre, mood=mood, topic=topic, variation_salt=variation_salt),
        "time_signature": "4/4",
        "target_duration_sec": _lyric_target_duration_sec(station_profile=station_profile, genre=genre, mood=mood, lyrics_mode=lyrics_mode),
        "lyrics_mode": lyrics_mode,
        "vocal_ratio": vocal_ratio,
        "cohesion": cohesion,
        "discovery": discovery,
        "mood_volatility": mood_vol,
        "energy_variability": energy_var,
        "daypart": daypart,
    }


def _remote_lyric_system_prompt() -> str:
    banned = ", ".join(f'"{phrase}"' for phrase in _REMOTE_BANNED_FILLER_PHRASES)
    return (
        f"Remote lyric prompt version: {_REMOTE_LYRIC_PROMPT_VERSION}.\n"
        "You are a professional songwriter writing record-ready lyrics, not an AI assistant and not a generic lyric generator.\n"
        "Write scenes: physical places, visible objects, actions, tension, consequence, and sensory details.\n"
        "Imply emotion through behavior and image; do not explain feelings with abstract statements.\n"
        "Every section must advance the same story from the song brief.\n"
        "Return strictly valid JSON with exactly two keys: title, lyrics. Use English words with ASCII characters only.\n"
        "NEGATIVE INSTRUCTIONS: forbid motivational filler, generic EDM slogans, crowd-hype commands, and empty uplift language. "
        f"Do not write these phrases or close variants: {banned}.\n"
        "BAD lyric examples:\n"
        "We rise through the night, hands up, feel alive\n"
        "City lights keep the signal strong and we never let go\n"
        "GOOD lyric examples:\n"
        "Paper wristband sticks to the payphone glass\n"
        "She leaves the keys under a blue exit light\n"
        "The chorus pays off the scene with one memorable repeated phrase, never a hype slogan."
    )


def _quality_repair_block(
    *,
    quality_reasons: list[str] | None,
    previous_lyrics: str | None,
) -> str:
    reasons = [str(x).strip() for x in (quality_reasons or []) if str(x).strip()]
    if not reasons:
        return ""
    reason_text = ", ".join(reasons)
    directives = {
        "repeated_chorus_lines": "Change the chorus payoff across repeats; keep a memorable phrase but do not duplicate full chorus lines.",
        "repeated_full_lines": "Do not reuse full lines between sections except one short hook phrase.",
        "generic_filler_phrases": "Remove all banned filler and replace slogans with objects, actions, and consequence.",
        "meta_prompt_leakage": "Do not mention prompts, concepts, profiles, instructions, or songwriting terminology inside the lyrics.",
        "song_brief_underused": "Use the narrator, setting, conflict, hook concept, and imagery from the song brief in visible lyric details.",
        "too_abstract_not_enough_imagery": "Replace abstract emotion words with concrete objects, physical places, and sensory details.",
        "too_similar_to_recent_lyrics": "Change line shapes, chorus phrasing, title image, and section openings from recent drafts.",
        "empty_lyrics": "Write a complete lyric with the required section labels.",
    }
    targeted = "\n".join(f"- {directives.get(reason, 'Correct this failed quality category with more concrete story detail.')}" for reason in reasons)
    previous_excerpt = "\n".join((previous_lyrics or "").splitlines()[:18]).strip()
    if previous_excerpt:
        previous_excerpt = f"\nPrevious weak draft excerpt to avoid copying:\n{previous_excerpt}"
    return (
        "\nQUALITY REPAIR PASS:\n"
        f"The previous lyric failed these quality categories: {reason_text}.\n"
        "Explicitly avoid the previous weaknesses:\n"
        f"{targeted}"
        f"{previous_excerpt}\n"
    )


def _build_remote_lyric_user_prompt(
    *,
    genre: str,
    chosen_topic: str,
    mood: str,
    station_name: str,
    station_description: str,
    personality: str,
    recent_tracks: list[dict[str, Any]],
    variation_salt: str,
    safety: str,
    feel_text: str,
    direction_text: str,
    avoid_text: str,
    concept: dict[str, str],
    brief_text: str,
    voice_directive: str,
    constraints_block: str,
    quality_reasons: list[str] | None = None,
    previous_lyrics: str | None = None,
) -> str:
    recent_titles = ", ".join(
        [str(x.get("title", "")).strip() for x in (recent_tracks or []) if str(x.get("title", "")).strip()][:5]
    ) or "none"
    banned = ", ".join(_REMOTE_BANNED_FILLER_PHRASES)
    return (
        f"Station: {station_name}. Personality: {personality}. Description: {station_description}\n"
        f"Genre: {genre}. Mood: {mood}. Exact topic: {chosen_topic}.\n"
        "Write as a songwriter building a short film in lyric form.\n\n"
        "SONG BRIEF FIELDS TO USE STRONGLY:\n"
        f"{brief_text or 'No structured brief supplied.'}\n\n"
        "STORY SOURCE:\n"
        f"Premise: {concept['premise']}\n"
        f"Physical setting: {concept['setting']}\n"
        f"Conflict: {concept['conflict']}\n"
        f"Imagery bank: {concept['images']}\n"
        f"Hook concept / chorus action: {concept['chorus_action']}\n\n"
        "VOICE PROFILE AND DELIVERY:\n"
        f"{voice_directive or 'Use a clear, genre-credible lead vocal with specific point of view.'}\n\n"
        "WRITING RULES:\n"
        "- Use concrete objects, physical places, actions, sensory details, and consequence in every section.\n"
        "- Show emotion indirectly through what the narrator notices, touches, avoids, breaks, carries, or leaves behind.\n"
        "- Let Verse 1 establish the room and pressure; Verse 2 must move the story forward, not repeat the setup.\n"
        "- The bridge must reveal a consequence or reversal.\n"
        "- The final chorus must pay off the emotional turn.\n"
        "- Use short singable lines with varied sentence shapes.\n"
        "- Never mention production terms or system/prompt text.\n\n"
        "CHORUS REQUIREMENTS:\n"
        "- Build around one memorable repeated phrase from the hook concept or title image.\n"
        "- Do not use generic hype phrases.\n"
        "- Follow the chorus strategy from the song brief when present; vary chorus structure by changing one line, tense, or consequence.\n"
        "- Chorus must deliver emotional payoff through a concrete image or action.\n\n"
        "NEGATIVE INSTRUCTION BLOCK:\n"
        f"Do not write motivational filler, generic EDM slogans, or these banned phrases: {banned}.\n"
        "BAD lyric examples:\n"
        "We rise through the night, hands up, feel alive\n"
        "City lights keep the signal strong and we never let go\n"
        "We own the night, never fade, right here right now\n"
        "GOOD lyric examples:\n"
        "Paper wristband sticks to the payphone glass\n"
        "Blue exit lights cut across the borrowed keys\n"
        "Static on platform four says her name before I do\n\n"
        f"The song should feel like: {feel_text}.\n"
        f"{direction_text}\n"
        f"{avoid_text}\n"
        f"Keep imagery and language authentic to {genre}. {constraints_block}\n"
        f"{safety}\n"
        f"Avoid copying these recent titles: {recent_titles}.\n"
        f"{_quality_repair_block(quality_reasons=quality_reasons, previous_lyrics=previous_lyrics)}"
        f"Variation token for uniqueness only, never print it: {variation_salt}.\n"
        "Return JSON only: {\"title\":\"...\",\"lyrics\":\"...\"}. "
        "Set title to a unique, musical, image-driven title (max 80 chars), not a raw topic copy. "
        "Lyrics must use this exact section order: "
        "[INTRO] -> [VERSE 1] -> optional [PRE-CHORUS] -> [CHORUS] -> [VERSE 2] -> optional [PRE-CHORUS] -> [CHORUS] -> [BRIDGE] -> [FINAL CHORUS] -> [OUTRO]. "
        "Lyrics value must be a plain string, not an object. "
        "Do not reuse any full line between Verse 1 and Verse 2."
    )


async def _try_remote_lyrics(
    *,
    base_urls: list[str],
    model: str,
    api_key: str | None,
    auth_email: str | None,
    auth_password: str | None,
    timeout_seconds: int,
    temperature: float,
    genre: str,
    title: str,
    mood: str,
    topic: str,
    clean_lyrics_only: bool,
    station_name: str,
    station_description: str,
    personality: str,
    recent_tracks: list[dict[str, Any]],
    variation_salt: str,
    topic_ideas: list[str] | None = None,
    taste_hints: list[str] | None = None,
    lyric_constraints: dict[str, Any] | None = None,
    voice_profile: dict[str, Any] | None = None,
    song_brief: dict[str, Any] | None = None,
    quality_reasons: list[str] | None = None,
    previous_lyrics: str | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[str | None, str | None, str | None]:
    def note_error(reason: str) -> None:
        if diagnostics is not None and not diagnostics.get("error"):
            diagnostics["error"] = reason

    def note_parse_shape(shape: str) -> None:
        if diagnostics is not None:
            diagnostics["parse_shape"] = shape

    safety = "Use radio-safe language only." if clean_lyrics_only else "Avoid gratuitous explicit content."
    topic_items = [str(x).strip() for x in (topic_ideas or []) if str(x).strip()]
    if topic.strip() and topic not in topic_items:
        topic_items.append(topic)
    chosen_topic = topic.strip() if topic.strip() else (topic_items[0] if topic_items else "night drive")
    feel_text = _derive_lyric_style_guidance(genre=genre, taste_hints=taste_hints, mood=mood)
    direction_text, avoid_text = _genre_lyric_direction(genre=genre, taste_hints=taste_hints, mood=mood)
    fallback_concept = _build_song_concept(
        genre=genre,
        topic=chosen_topic,
        daypart=str((lyric_constraints or {}).get("daypart", "")),
        mood=mood,
        station_description=station_description,
    )
    concept = _concept_from_song_brief(song_brief, fallback_concept)
    brief_text = format_song_brief(song_brief)
    voice_directive = format_voice_directive(voice_profile)
    system = _remote_lyric_system_prompt()
    constraints = lyric_constraints or {}
    constraints_block = (
        f"Tempo {constraints.get('tempo_range_bpm', 'genre-consistent')} BPM, "
        f"key hint {constraints.get('key_hint', 'genre-consistent')}, "
        f"meter {constraints.get('time_signature', '4/4')}, "
        f"target duration {constraints.get('target_duration_sec', 320)}s, "
        f"lyrics mode {constraints.get('lyrics_mode', 'mixed')}."
    )
    user = _build_remote_lyric_user_prompt(
        genre=genre,
        chosen_topic=chosen_topic,
        mood=mood,
        station_name=station_name,
        station_description=station_description,
        personality=personality,
        recent_tracks=recent_tracks,
        variation_salt=variation_salt,
        safety=safety,
        feel_text=feel_text,
        direction_text=direction_text,
        avoid_text=avoid_text,
        concept=concept,
        brief_text=brief_text,
        voice_directive=voice_directive,
        constraints_block=constraints_block,
        quality_reasons=quality_reasons,
        previous_lyrics=previous_lyrics,
    )

    fallback_text: str | None = None
    fallback_source: str | None = None
    fallback_title: str | None = None

    for raw_url in base_urls:
        base_url = raw_url.strip().rstrip("/")
        if not base_url:
            continue
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                headers = {"Content-Type": "application/json"}
                token = _get_cached_auth_token(base_url)
                auth_value = token or api_key
                if auth_value:
                    headers["Authorization"] = f"Bearer {auth_value}"
                for attempt in range(2):
                    payload = {
                        "model": model,
                        "temperature": min(0.95, temperature + (attempt * 0.12)),
                        # Bound remote output length so lyric calls finish within timeout budget.
                        "max_tokens": 260,
                        "messages": [
                            {"role": "system", "content": system},
                            {
                                "role": "user",
                                "content": user + f"\nUniqueness pass: {attempt + 1}",
                            },
                        ],
                    }
                    resp = await client.post(f"{base_url}/api/chat/completions", headers=headers, json=payload)
                    if resp.status_code == 401 and auth_email and auth_password:
                        token = await _signin_openwebui_token(
                            client=client,
                            base_url=base_url,
                            auth_email=auth_email,
                            auth_password=auth_password,
                        )
                        if token:
                            headers["Authorization"] = f"Bearer {token}"
                            resp = await client.post(f"{base_url}/api/chat/completions", headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    content = _extract_chat_content(data)
                    if not content:
                        note_error("empty_response")
                        continue
                    stripped_content = _strip_code_fence(content).strip()
                    if stripped_content.startswith("{"):
                        try:
                            parsed_payload = json.loads(stripped_content)
                        except Exception:
                            note_error("unparseable_lyrics")
                            continue
                        if not isinstance(parsed_payload, dict):
                            note_error("unparseable_lyrics")
                            continue
                    parsed_title, parsed_lyrics, parse_shape = _extract_title_lyrics_and_shape(content)
                    note_parse_shape(parse_shape)
                    if parse_shape == "unknown":
                        note_error("unparseable_lyrics")
                        continue
                    text = parsed_lyrics
                    if not text:
                        note_error("empty_lyrics")
                        continue
                    variation_key = variation_salt.strip().lower()
                    if variation_key and (
                        variation_key in text.lower() or variation_key in str(parsed_title or "").lower()
                    ):
                        note_error("variation_token_leak")
                        continue
                    # Keep the first non-empty remote response as a fallback candidate.
                    # This ensures we only fall back to local-template on true remote failures.
                    if fallback_text is None:
                        fallback_text = text
                        fallback_source = base_url
                        fallback_title = parsed_title
                    if _lyrics_is_too_templatey(text):
                        continue
                    try:
                        await _persist_openwebui_lyrics_chat(
                            client=client,
                            base_url=base_url,
                            headers=headers,
                            model=model,
                            station_name=station_name,
                            genre=genre,
                            topic=chosen_topic,
                            user_prompt=payload["messages"][1]["content"],
                            assistant_response=content,
                        )
                    except Exception:
                        pass
                    return text, base_url, parsed_title
        except httpx.HTTPStatusError as exc:
            note_error(f"request_failed:{exc.response.status_code}")
            continue
        except httpx.TimeoutException:
            note_error("request_failed:timeout")
            continue
        except httpx.HTTPError as exc:
            note_error(f"request_failed:{exc.__class__.__name__.lower()}")
            continue
        except Exception as exc:
            note_error(f"request_failed:{exc.__class__.__name__.lower()}")
            continue
    if fallback_text:
        try:
            async with httpx.AsyncClient(timeout=min(timeout_seconds, 20)) as client:
                headers = {"Content-Type": "application/json"}
                token = _get_cached_auth_token(fallback_source or "")
                auth_value = token or api_key
                if auth_value:
                    headers["Authorization"] = f"Bearer {auth_value}"
                await _persist_openwebui_lyrics_chat(
                    client=client,
                    base_url=fallback_source or "",
                    headers=headers,
                    model=model,
                    station_name=station_name,
                    genre=genre,
                    topic=chosen_topic,
                    user_prompt=user,
                    assistant_response=fallback_text,
                )
        except Exception:
            pass
        return fallback_text, fallback_source, fallback_title
    note_error("no_remote_lyrics")
    return None, None, None


async def _persist_openwebui_lyrics_chat(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    model: str,
    station_name: str,
    genre: str,
    topic: str,
    user_prompt: str,
    assistant_response: str,
) -> None:
    if not base_url:
        return
    ts = int(datetime.utcnow().timestamp())
    user_id = str(uuid.uuid4())
    assistant_id = str(uuid.uuid4())
    user_msg = {
        "id": user_id,
        "parentId": None,
        "childrenIds": [assistant_id],
        "role": "user",
        "content": user_prompt,
        "timestamp": ts,
    }
    assistant_msg = {
        "id": assistant_id,
        "parentId": user_id,
        "childrenIds": [],
        "role": "assistant",
        "content": assistant_response,
        "timestamp": ts + 1,
        "model": model,
        "done": True,
    }
    topic_short = " ".join((topic or "").split())[:48] or "lyrics"
    chat_title = f"AIRadio Lyrics | {station_name} | {topic_short}"[:120]
    chat_payload = {
        "title": chat_title,
        "models": [model],
        "params": {"temperature": 0.7},
        # Keep both modern and legacy-compatible structures for OpenWebUI rendering.
        "messages": [user_msg, assistant_msg],
        "history": {
            "messages": {
                user_id: user_msg,
                assistant_id: assistant_msg,
            },
            "currentId": assistant_id,
        },
        "tags": ["airadio", "lyrics", genre.lower().strip() or "genre"],
    }

    create_resp = await client.post(f"{base_url}/api/v1/chats/new", headers=headers, json={"chat": {}})
    create_resp.raise_for_status()
    created = create_resp.json()
    chat_id = str((created or {}).get("id", "")).strip()
    if not chat_id:
        return
    update_resp = await client.post(
        f"{base_url}/api/v1/chats/{chat_id}",
        headers=headers,
        json={"chat": chat_payload},
    )
    update_resp.raise_for_status()


def _get_cached_auth_token(base_url: str) -> str | None:
    now = datetime.utcnow().timestamp()
    cached = _AUTH_TOKEN_CACHE.get(base_url)
    if not cached:
        return None
    token, expires_at = cached
    if expires_at <= now:
        _AUTH_TOKEN_CACHE.pop(base_url, None)
        return None
    return token


async def _signin_openwebui_token(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    auth_email: str,
    auth_password: str,
) -> str | None:
    try:
        resp = await client.post(
            f"{base_url}/api/v1/auths/signin",
            json={"email": auth_email, "password": auth_password},
        )
        resp.raise_for_status()
        parsed = resp.json()
        payload = parsed if isinstance(parsed, dict) else {}
        token = str(payload.get("token", "")).strip()
        if token:
            _AUTH_TOKEN_CACHE[base_url] = (token, datetime.utcnow().timestamp() + 55 * 60)
            return token
    except Exception:
        return None
    return None


def _unpack_remote_lyrics_result(remote_result: Any) -> tuple[str | None, str | None, str | None]:
    if isinstance(remote_result, tuple) and len(remote_result) == 3:
        remote_lyrics, remote_source, remote_title = remote_result
    elif isinstance(remote_result, tuple) and len(remote_result) == 2:
        remote_lyrics, remote_source = remote_result
        remote_title = None
    else:
        remote_lyrics, remote_source, remote_title = None, None, None
    return remote_lyrics, remote_source, remote_title


def _remote_source_label(source: str | None) -> str:
    cleaned = str(source or "").strip()
    return f"openwebui:{cleaned}" if cleaned else "openwebui:unknown"


async def _call_remote_lyrics_with_diagnostics(
    *,
    diagnostics: dict[str, Any],
    **kwargs: Any,
) -> tuple[str | None, str | None, str | None]:
    try:
        return await _try_remote_lyrics(**kwargs, diagnostics=diagnostics)
    except TypeError as exc:
        if "diagnostics" not in str(exc):
            raise
        return await _try_remote_lyrics(**kwargs)


async def preprocess_generation(
    *,
    settings: Any,
    station_name: str,
    station_description: str,
    genre: str,
    personality: str,
    daypart: str,
    mood: str,
    station_profile: dict[str, Any],
    base_prompt: str,
    negative_prompt: str,
    recent_tracks: list[dict[str, Any]],
    voice_profile: dict[str, Any] | None = None,
    recent_generations: list[dict[str, Any]] | None = None,
) -> PreprocessedGeneration:
    force_ascii = bool(getattr(settings, "prompt_force_ascii_english", True))
    lyrics_mode = str(station_profile.get("lyrics_mode", "mixed"))
    clean_lyrics_only = bool(station_profile.get("clean_lyrics_only", True))
    variation_salt = uuid.uuid4().hex[:12]
    chosen_topic = _choose_song_topic(
        station_profile,
        mood,
        genre=genre,
        daypart=daypart,
        recent_tracks=recent_tracks,
        salt=variation_salt,
    )
    song_brief = build_song_brief(
        topic=chosen_topic,
        genre=genre,
        mood=mood,
        daypart=daypart,
        station_profile=station_profile,
        recent_generations=recent_generations or recent_tracks,
        voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
        salt=variation_salt,
    )
    suggested_title = suggest_track_title(
        genre=genre,
        mood=mood,
        topic=str(song_brief.get("title_seed") or chosen_topic),
        daypart=daypart,
        personality=personality,
        salt=datetime.utcnow().isoformat(),
    )
    lyric_constraints = _build_lyric_constraints(
        station_profile=station_profile,
        genre=genre,
        daypart=daypart,
        mood=mood,
        topic=chosen_topic,
        variation_salt=variation_salt,
    )
    technical_parameters = build_technical_parameters(
        genre=genre,
        mood=mood,
        daypart=daypart,
        station_profile=station_profile,
        duration_sec=int(lyric_constraints.get("target_duration_sec", station_profile.get("target_duration_sec", 320))),
        topic=chosen_topic,
    )
    music_caption = build_music_caption_formula(
        genre=genre,
        personality=personality,
        mood=mood,
        daypart=daypart,
        station_profile=station_profile,
        topic=chosen_topic,
        song_brief=song_brief,
        voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
    )

    lyrics = _build_lyrics_draft(
        genre=genre,
        personality=personality,
        station_name=station_name,
        station_description=station_description,
        daypart=daypart,
        mood=mood,
        station_profile=station_profile,
        song_topic=chosen_topic,
        variation_salt=variation_salt,
        recent_tracks=recent_tracks,
        voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
        song_brief=song_brief,
    )

    # Dedicated lyrics generation step (OpenWebUI/Ollama) before music caption refinement.
    lyrics_source = "local-template"
    lyrics_model = str(getattr(settings, "lyrics_refiner_model", "") or "").strip() or str(getattr(settings, "prompt_refiner_model", "") or "").strip()
    lyrics_urls_raw = str(getattr(settings, "lyrics_refiner_base_urls", "") or "") or str(getattr(settings, "prompt_refiner_base_urls", "") or "")
    # Bound remote lyrics timeout so station refill loops cannot stall for several minutes.
    lyrics_timeout = min(60, int(getattr(settings, "lyrics_refiner_timeout_seconds", 20)))
    lyrics_api_key = str(getattr(settings, "lyrics_refiner_api_key", "") or "").strip() or str(getattr(settings, "prompt_refiner_api_key", "") or "").strip() or None
    lyrics_auth_email = str(getattr(settings, "lyrics_refiner_auth_email", "") or "").strip() or None
    lyrics_auth_password = str(getattr(settings, "lyrics_refiner_auth_password", "") or "").strip() or None
    lyrics_temp = float(getattr(settings, "lyrics_refiner_temperature", 0.7))
    lyrics_urls = [x.strip() for x in lyrics_urls_raw.split(",") if x.strip()]
    quality_repair_attempted = False
    quality_repair_success = False
    remote_lyric_diagnostics: dict[str, Any] = {}

    def finalized_remote_candidate(raw_lyrics: str | None) -> str | None:
        candidate = raw_lyrics
        if force_ascii:
            candidate = _sanitize_ascii_text(candidate or "") or None
        return _finalize_lyrics_for_generator(candidate)

    def store_remote_candidate_diagnostics(
        *,
        prefix: str,
        raw_lyrics: str | None,
        source: str | None,
        title: str | None,
    ) -> None:
        finalized = finalized_remote_candidate(raw_lyrics)
        remote_lyric_diagnostics[f"{prefix}_quality"] = evaluate_lyrics_quality(
            lyrics=finalized,
            song_brief=song_brief,
            voice_profile=voice_profile,
            recent_generations=recent_generations,
        )
        remote_lyric_diagnostics[f"{prefix}_excerpt"] = compact_lyric_excerpt(finalized)
        remote_lyric_diagnostics[f"{prefix}_title"] = " ".join(str(title or "").split())[:80]
        remote_lyric_diagnostics[f"{prefix}_source"] = _remote_source_label(source)

    if lyrics_mode != "instrumental_only" and lyrics_model and lyrics_urls:
        title = _suggest_song_title(station_name=station_name, topic=chosen_topic, daypart=daypart)
        topic_ideas = [str(x).strip() for x in (station_profile.get("topic_ideas", []) or []) if str(x).strip()]
        taste_hints = [str(x).strip() for x in (station_profile.get("taste_hints", []) or []) if str(x).strip()]
        initial_remote_call_diagnostics: dict[str, Any] = {}
        remote_result = await _call_remote_lyrics_with_diagnostics(
            diagnostics=initial_remote_call_diagnostics,
            base_urls=lyrics_urls,
            model=lyrics_model,
            api_key=lyrics_api_key,
            auth_email=lyrics_auth_email,
            auth_password=lyrics_auth_password,
            timeout_seconds=lyrics_timeout,
            temperature=lyrics_temp,
            genre=genre,
            title=title,
            mood=mood,
            topic=chosen_topic,
            clean_lyrics_only=clean_lyrics_only,
            station_name=station_name,
            station_description=station_description,
            personality=personality,
            recent_tracks=recent_tracks,
            variation_salt=variation_salt,
            topic_ideas=topic_ideas,
            taste_hints=taste_hints,
            lyric_constraints=lyric_constraints,
            voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
            song_brief=song_brief,
        )
        remote_lyrics, lyrics_base_url, remote_title = _unpack_remote_lyrics_result(remote_result)
        remote_lyric_diagnostics["remote_initial_parse_shape"] = str(
            initial_remote_call_diagnostics.get("parse_shape") or ("string" if remote_lyrics else "unknown")
        )
        if remote_lyrics:
            store_remote_candidate_diagnostics(
                prefix="remote_initial",
                raw_lyrics=remote_lyrics,
                source=lyrics_base_url,
                title=remote_title,
            )
            lyrics = remote_lyrics
            lyrics_source = _remote_source_label(lyrics_base_url)
            if remote_title:
                suggested_title = " ".join(str(remote_title).split())[:80] or suggested_title
        else:
            remote_lyric_diagnostics["remote_initial_error"] = str(
                initial_remote_call_diagnostics.get("error") or "empty_lyrics"
            )[:80]

    if force_ascii:
        negative_prompt = _sanitize_ascii_text(negative_prompt, collapse_whitespace=True)
        lyrics = _sanitize_ascii_text(lyrics or "") or None
    lyrics = _finalize_lyrics_for_generator(lyrics)
    lyric_quality = {
        "passed": True,
        "score": 1.0,
        "reasons": [],
        "signature": {"mode": "instrumental_only"},
    }
    if lyrics_mode != "instrumental_only":
        lyric_quality = evaluate_lyrics_quality(
            lyrics=lyrics,
            song_brief=song_brief,
            voice_profile=voice_profile,
            recent_generations=recent_generations,
        )
        if not bool(lyric_quality.get("passed")) and lyrics_model and lyrics_urls:
            quality_repair_attempted = True
            repair_salt = f"{variation_salt}-repair"
            repair_remote_call_diagnostics: dict[str, Any] = {}
            remote_result = await _call_remote_lyrics_with_diagnostics(
                diagnostics=repair_remote_call_diagnostics,
                base_urls=lyrics_urls,
                model=lyrics_model,
                api_key=lyrics_api_key,
                auth_email=lyrics_auth_email,
                auth_password=lyrics_auth_password,
                timeout_seconds=lyrics_timeout,
                temperature=min(0.95, lyrics_temp + 0.12),
                genre=genre,
                title=_suggest_song_title(station_name=station_name, topic=chosen_topic, daypart=daypart),
                mood=mood,
                topic=chosen_topic,
                clean_lyrics_only=clean_lyrics_only,
                station_name=station_name,
                station_description=station_description,
                personality=personality,
                recent_tracks=[
                    *recent_tracks,
                    {
                        "title": "avoid failed lyric draft",
                        "song_topic": chosen_topic,
                        "quality_reasons": lyric_quality.get("reasons", []),
                    },
                ],
                variation_salt=repair_salt,
                topic_ideas=[str(x).strip() for x in (station_profile.get("topic_ideas", []) or []) if str(x).strip()],
                taste_hints=[str(x).strip() for x in (station_profile.get("taste_hints", []) or []) if str(x).strip()],
                lyric_constraints=lyric_constraints,
                voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
                song_brief=song_brief,
                quality_reasons=[str(x) for x in lyric_quality.get("reasons", [])],
                previous_lyrics=lyrics,
            )
            repair_lyrics, repair_source, repair_title = _unpack_remote_lyrics_result(remote_result)
            remote_lyric_diagnostics["remote_repair_parse_shape"] = str(
                repair_remote_call_diagnostics.get("parse_shape") or ("string" if repair_lyrics else "unknown")
            )
            if repair_lyrics:
                store_remote_candidate_diagnostics(
                    prefix="remote_repair",
                    raw_lyrics=repair_lyrics,
                    source=repair_source,
                    title=repair_title,
                )
                if force_ascii:
                    repair_lyrics = _sanitize_ascii_text(repair_lyrics or "") or None
                repaired = _finalize_lyrics_for_generator(repair_lyrics)
                repair_quality = evaluate_lyrics_quality(
                    lyrics=repaired,
                    song_brief=song_brief,
                    voice_profile=voice_profile,
                    recent_generations=recent_generations,
                )
                if bool(repair_quality.get("passed")):
                    lyrics = repaired
                    lyric_quality = repair_quality
                    lyrics_source = f"{_remote_source_label(repair_source)}:quality_repair"
                    quality_repair_success = True
                    if repair_title:
                        suggested_title = " ".join(str(repair_title).split())[:80] or suggested_title
            else:
                remote_lyric_diagnostics["remote_repair_error"] = str(
                    repair_remote_call_diagnostics.get("error") or "empty_lyrics"
                )[:80]
        if not bool(lyric_quality.get("passed")):
            lyrics = _finalize_lyrics_for_generator(
                _strict_local_lyrics_from_brief(
                    song_brief=song_brief,
                    genre=genre,
                    voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
                )
            )
            lyric_quality = evaluate_lyrics_quality(
                lyrics=lyrics,
                song_brief=song_brief,
                voice_profile=voice_profile,
                recent_generations=recent_generations,
            )
            lyrics_source = f"{lyrics_source}:strict_local_fallback"
    local_prompt = _build_local_prompt(
        base_prompt=base_prompt,
        music_caption=music_caption,
        technical_parameters=technical_parameters,
        genre=genre,
        daypart=daypart,
        mood=mood,
        station_profile=station_profile,
        lyrics=lyrics,
        chosen_topic=chosen_topic,
        song_brief=song_brief,
        voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
    )
    if force_ascii:
        local_prompt = _sanitize_ascii_text(local_prompt, collapse_whitespace=False)

    model = str(getattr(settings, "prompt_refiner_model", "") or "").strip()
    base_urls_raw = str(getattr(settings, "prompt_refiner_base_urls", "") or "")
    timeout_seconds = int(getattr(settings, "prompt_refiner_timeout_seconds", 20))
    api_key = str(getattr(settings, "prompt_refiner_api_key", "") or "").strip() or None
    base_urls = [x.strip() for x in base_urls_raw.split(",") if x.strip()]

    if model and base_urls:
        remote = await _try_remote_refine(
            base_urls=base_urls,
            model=model,
            api_key=api_key,
            auth_email=lyrics_auth_email,
            auth_password=lyrics_auth_password,
            timeout_seconds=timeout_seconds,
            base_prompt=base_prompt,
            local_prompt=local_prompt,
            negative_prompt=negative_prompt,
            lyrics=lyrics,
            lyrics_mode=lyrics_mode,
            context_payload={
                "station_name": station_name,
                "station_description": station_description,
                "genre": genre,
                "personality": personality,
                "daypart": daypart,
                "mood": mood,
                "station_profile": station_profile,
                "recent_tracks": recent_tracks,
                "voice_profile": voice_profile or {},
                "song_brief": song_brief,
            },
        )
        if remote:
            if force_ascii:
                remote.prompt = _sanitize_ascii_text(remote.prompt, collapse_whitespace=True)
                remote.negative_prompt = _sanitize_ascii_text(remote.negative_prompt, collapse_whitespace=True)
                remote.lyrics = _sanitize_ascii_text(remote.lyrics or "") or None
            remote.lyrics = _finalize_lyrics_for_generator(remote.lyrics)
            remote.diagnostics["lyrics_source"] = lyrics_source
            remote.diagnostics["lyrics_model"] = lyrics_model or "local-template"
            remote.diagnostics["song_topic"] = chosen_topic
            remote.diagnostics["suggested_title"] = suggested_title
            remote.diagnostics["lyric_constraints"] = lyric_constraints
            remote.diagnostics["voice_profile"] = voice_profile or {}
            remote.diagnostics["song_brief"] = song_brief
            remote.diagnostics["lyric_quality"] = lyric_quality
            remote.diagnostics.update(remote_lyric_diagnostics)
            remote.diagnostics["remote_prompt_version"] = _REMOTE_LYRIC_PROMPT_VERSION
            remote.diagnostics["quality_repair_attempted"] = quality_repair_attempted
            remote.diagnostics["quality_repair_success"] = quality_repair_success
            if not remote.technical_parameters:
                remote.technical_parameters = technical_parameters
            if not remote.music_caption:
                remote.music_caption = remote.prompt
            remote.diagnostics["technical_parameters"] = remote.technical_parameters
            remote.prompt = build_song_concept_prompt(
                music_caption=remote.music_caption,
                technical_parameters=remote.technical_parameters,
                lyrics=remote.lyrics,
                song_brief=song_brief,
                voice_profile=voice_profile if lyrics_mode != "instrumental_only" else None,
            )
            return remote

    return PreprocessedGeneration(
        prompt=local_prompt,
        negative_prompt=negative_prompt,
        lyrics=lyrics,
        source="local-template",
        diagnostics={
            "provider": "local",
            "lyrics_source": lyrics_source,
            "lyrics_model": lyrics_model or "local-template",
            "song_topic": chosen_topic,
            "suggested_title": suggested_title,
            "lyric_constraints": lyric_constraints,
            "voice_profile": voice_profile or {},
            "song_brief": song_brief,
            "lyric_quality": lyric_quality,
            **remote_lyric_diagnostics,
            "remote_prompt_version": _REMOTE_LYRIC_PROMPT_VERSION,
            "quality_repair_attempted": quality_repair_attempted,
            "quality_repair_success": quality_repair_success,
            "technical_parameters": technical_parameters,
        },
        music_caption=music_caption,
        technical_parameters=technical_parameters,
    )
