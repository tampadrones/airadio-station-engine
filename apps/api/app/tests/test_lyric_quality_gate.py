from __future__ import annotations

import pytest

from app.services.lyric_quality_gate import evaluate_lyrics_quality
from app.services.prompt_preprocessor import preprocess_generation


class DummySettings:
    prompt_refiner_base_urls = ""
    prompt_refiner_model = ""
    prompt_refiner_timeout_seconds = 1
    prompt_refiner_api_key = ""
    lyrics_refiner_base_urls = ""
    lyrics_refiner_model = ""
    lyrics_refiner_timeout_seconds = 1
    lyrics_refiner_api_key = ""
    lyrics_refiner_temperature = 0.7


BRIEF = {
    "topic": "arcade goodbye",
    "angle": "turn the topic into a neon chase with emotional stakes: arcade goodbye",
    "narrator": "driver narrating the moment before the turn",
    "setting": "empty arcade glowing after close",
    "conflict": "the message arrives after the exit is already missed",
    "emotional_turn": "nostalgia becomes forward motion",
    "hook_concept": "the hook repeats the message the narrator cannot ignore",
    "chorus_strategy": "repeat one concrete image with a changed final line",
    "imagery_bank": ["neon", "chrome", "arcade glass", "tail lights", "cassette hiss", "blue rain"],
    "forbidden_phrases": ["city lights", "right here right now"],
    "title_seed": "Arcade Goodbye Neon",
}


def test_quality_gate_catches_repeated_chorus():
    lyrics = (
        "[VERSE 1]\n"
        "Neon waits inside the empty arcade\n\n"
        "[CHORUS]\n"
        "Arcade goodbye is the message I cannot ignore\n"
        "Arcade goodbye is the message I cannot ignore\n\n"
        "[FINAL CHORUS]\n"
        "Arcade goodbye is the message I cannot ignore\n"
    )
    out = evaluate_lyrics_quality(lyrics=lyrics, song_brief=BRIEF, voice_profile=None)

    assert not out["passed"]
    assert "repeated_chorus_lines" in out["reasons"]


def test_quality_gate_catches_meta_prompt_leakage():
    lyrics = "[VERSE 1]\nSong concept: use the brief\nVocal profile: airy synth\nTheme anchors: arcade goodbye"
    out = evaluate_lyrics_quality(lyrics=lyrics, song_brief=BRIEF, voice_profile=None)

    assert not out["passed"]
    assert "meta_prompt_leakage" in out["reasons"]


def test_quality_gate_catches_generic_city_night_filler():
    lyrics = (
        "[VERSE 1]\n"
        "We rise through the night under city lights\n"
        "We shine and feel alive right here right now\n"
        "Hold the line and never fade\n"
    )
    out = evaluate_lyrics_quality(lyrics=lyrics, song_brief=BRIEF, voice_profile=None)

    assert not out["passed"]
    assert "generic_filler_phrases" in out["reasons"]


def test_quality_gate_passes_concrete_brief_driven_lyrics():
    lyrics = (
        "[INTRO]\n"
        "Neon waits inside the empty arcade\n\n"
        "[VERSE 1]\n"
        "I stand where the machines glow after close\n"
        "The message arrives after the exit is missed\n"
        "Arcade glass holds my face in blue rain\n"
        "Chrome on my sleeve remembers the turn\n\n"
        "[CHORUS]\n"
        "Arcade goodbye is the message I cannot ignore\n"
        "Tail lights pull the old room out of sight\n"
        "Cassette hiss keeps the last words honest\n"
        "I leave before the exit chooses me\n\n"
        "[VERSE 2]\n"
        "The empty arcade gives the story a shape\n"
        "Neon scratches the truth across my hands\n"
        "The missed exit becomes a clean decision\n"
        "Blue rain follows but I keep driving\n\n"
        "[FINAL CHORUS]\n"
        "Arcade goodbye names the turn I finally take\n"
        "Chrome catches the message in a different light\n"
        "Tail lights answer from the wet road\n"
        "I leave with proof and not a slogan\n"
    )
    out = evaluate_lyrics_quality(lyrics=lyrics, song_brief=BRIEF, voice_profile=None)

    assert out["passed"]
    assert out["score"] >= 0.68


@pytest.mark.asyncio
async def test_preprocess_stores_lyric_quality_diagnostics():
    out = await preprocess_generation(
        settings=DummySettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward", "clean_lyrics_only": True, "topic_ideas": ["arcade goodbye"]},
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
        voice_profile={
            "id": "female_airy_synth",
            "gender": "female",
            "vocal_tone": "airy synth-pop tone",
            "delivery": "floating lead",
            "range_hint": "upper register",
            "negative_prompt_terms": [],
        },
    )

    quality = out.diagnostics.get("lyric_quality")
    assert isinstance(quality, dict)
    assert quality["passed"] is True
    assert isinstance(quality.get("score"), float)
    assert "signature" in quality
