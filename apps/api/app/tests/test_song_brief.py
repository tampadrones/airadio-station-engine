from __future__ import annotations

import pytest

from app.services.song_brief import build_song_brief, _pools
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


def test_topic_cleanup_removes_generic_energy_tokens_and_preserves_raw_topic():
    brief = build_song_brief(
        topic="adrenaline rush high energy",
        genre="pop",
        mood="peak",
        daypart="evening",
        station_profile={},
        recent_generations=[],
        salt="fixed",
    )

    assert brief["raw_topic"] == "adrenaline rush high energy"
    assert brief["topic"] == "adrenaline rush"
    assert "high energy" not in brief["title_seed"].lower()
    assert "energy" not in brief["title_seed"].lower()
    assert len(brief["title_seed"].split()) <= 6
    assert str(brief).isascii()


def test_angles_are_natural_premises_not_prompt_instructions():
    for salt in ["a", "b", "c", "d", "e"]:
        brief = build_song_brief(
            topic="adrenaline rush high energy",
            genre="pop",
            mood="peak",
            daypart="evening",
            station_profile={},
            recent_generations=[],
            salt=salt,
        )
        lowered = brief["angle"].lower()
        assert "make the topic" not in lowered
        assert "turn the topic" not in lowered
        assert "frame the topic" not in lowered
        assert "adrenaline rush" in lowered


def test_expanded_pools_meet_diversity_floor():
    pools = _pools("EDM trance")

    assert len(pools["setting"]) >= 40
    assert len(pools["conflict"]) >= 40
    assert len(pools["narrator"]) >= 25
    assert len(pools["emotional_turn"]) >= 25
    assert len(pools["hook_concept"]) >= 25


def test_ten_briefs_do_not_collapse_to_same_grammar():
    recent = []
    briefs = []
    for idx in range(10):
        brief = build_song_brief(
            topic="late apology",
            genre="pop",
            mood="rise",
            daypart="night",
            station_profile={},
            recent_generations=recent,
            salt=f"grammar-{idx}",
        )
        briefs.append(brief)
        recent.insert(0, {"song_brief": brief})

    assert len({brief["structure_mode"] for brief in briefs}) >= 4
    assert len({brief["angle_template"] for brief in briefs}) >= 8
    assert len({brief["angle"].split()[0].lower() for brief in briefs}) >= 5


def test_settings_rotate_with_recent_generations():
    recent = []
    settings = []
    for idx in range(10):
        brief = build_song_brief(
            topic="afterparty truth",
            genre="EDM trance",
            mood="peak",
            daypart="late_night",
            station_profile={},
            recent_generations=recent,
            salt=f"setting-{idx}",
        )
        settings.append(brief["setting"])
        recent.insert(0, {"song_brief": brief})

    assert len(set(settings)) >= 9
    assert all(a != b for a, b in zip(settings, settings[1:]))


def test_title_seeds_vary_naturally_without_repeated_prefixes():
    recent = []
    titles = []
    for idx in range(10):
        brief = build_song_brief(
            topic="night drive",
            genre="synthwave",
            mood="rise",
            daypart="night",
            station_profile={},
            recent_generations=recent,
            salt=f"title-{idx}",
        )
        titles.append(brief["title_seed"])
        recent.insert(0, {"song_brief": brief})

    prefixes = [title.split()[0].lower() for title in titles]
    assert len(set(titles)) >= 9
    assert len(set(prefixes)) >= 6
    assert "night drive" not in {title.lower() for title in titles}
    assert not any(title.lower().startswith("night ") for title in titles)


def test_repeated_topic_produces_distinct_concepts_with_recent_avoidance():
    recent = []
    concepts = []
    for idx in range(10):
        brief = build_song_brief(
            topic="love",
            genre="rap trap",
            mood="baseline",
            daypart="evening",
            station_profile={},
            recent_generations=recent,
            salt=f"repeat-{idx}",
        )
        concepts.append((brief["angle"], brief["setting"], brief["conflict"], brief["title_seed"]))
        recent.insert(0, {"song_brief": brief})

    assert len(set(concepts)) >= 9
    assert len({concept[1] for concept in concepts}) >= 9
    assert len({concept[2] for concept in concepts}) >= 9


def test_repeated_topic_avoids_before_dawn_and_chance_disappears_spam():
    recent = []
    text = []
    for idx in range(10):
        brief = build_song_brief(
            topic="second chance",
            genre="pop",
            mood="release",
            daypart="morning",
            station_profile={},
            recent_generations=recent,
            salt=f"spam-{idx}",
        )
        text.append(" ".join(str(brief[field]) for field in ["angle", "setting", "conflict", "emotional_turn", "hook_concept"]))
        recent.insert(0, {"song_brief": brief})

    lowered = " ".join(text).lower()
    assert "before dawn" not in lowered
    assert "chance disappears" not in lowered


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
