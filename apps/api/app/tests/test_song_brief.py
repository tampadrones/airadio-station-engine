from __future__ import annotations

import pytest

from app.services.song_brief import build_song_brief
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


def test_repeated_topic_produces_different_angles_with_different_salts():
    a = build_song_brief(
        topic="night drive",
        genre="synthwave",
        mood="rise",
        daypart="night",
        station_profile={},
        recent_generations=[],
        salt="salt-a",
    )
    b = build_song_brief(
        topic="night drive",
        genre="synthwave",
        mood="rise",
        daypart="night",
        station_profile={},
        recent_generations=[],
        salt="salt-b",
    )

    assert a["angle"] != b["angle"]


def test_recent_settings_conflicts_and_hooks_are_avoided_when_possible():
    recent = [
        {
            "song_brief": {
                "setting": "rain-slick overpass under violet signs",
                "conflict": "the past keeps calling while the road demands a choice",
                "hook_concept": "the hook is the turn signal before the emotional crash",
                "narrator": "first-person narrator making one risky choice",
            }
        }
    ]
    brief = build_song_brief(
        topic="night drive",
        genre="synthwave",
        mood="rise",
        daypart="night",
        station_profile={},
        recent_generations=recent,
        salt="fixed",
    )

    assert brief["setting"] != recent[0]["song_brief"]["setting"]
    assert brief["conflict"] != recent[0]["song_brief"]["conflict"]
    assert brief["hook_concept"] != recent[0]["song_brief"]["hook_concept"]
    assert brief["narrator"] != recent[0]["song_brief"]["narrator"]


def test_song_brief_is_ascii_only():
    brief = build_song_brief(
        topic="caf\u00e9 d\u00e9j\u00e0 vu",
        genre="lo-fi",
        mood="release",
        daypart="late_night",
        station_profile={"taste_hints": ["r\u00eave"]},
        recent_generations=[],
        salt="fixed",
    )

    assert str(brief).isascii()


def test_broad_topic_becomes_concrete_song_concept():
    brief = build_song_brief(
        topic="love",
        genre="rock",
        mood="peak",
        daypart="evening",
        station_profile={},
        recent_generations=[],
        salt="fixed",
    )

    assert brief["topic"] == "love"
    assert "love" in brief["angle"]
    assert brief["setting"]
    assert brief["conflict"]
    assert brief["hook_concept"]
    assert brief["angle"] != "love"


@pytest.mark.asyncio
async def test_preprocess_final_prompt_and_diagnostics_include_song_brief():
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

    brief = out.diagnostics.get("song_brief")
    assert isinstance(brief, dict)
    assert brief["topic"]
    assert "SONG BRIEF:" in out.prompt
    assert f"Topic: {brief['topic']}" in out.prompt
    assert f"Narrator: {brief['narrator']}" in out.prompt
    assert f"Setting: {brief['setting']}" in out.prompt
    assert f"Conflict: {brief['conflict']}" in out.prompt
    assert f"Emotional Turn: {brief['emotional_turn']}" in out.prompt
    assert f"Hook Concept: {brief['hook_concept']}" in out.prompt
    assert f"Chorus Strategy: {brief['chorus_strategy']}" in out.prompt
    assert "VOICE DIRECTIVE:" in out.prompt
