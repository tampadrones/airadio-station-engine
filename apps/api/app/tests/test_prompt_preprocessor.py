from __future__ import annotations

import json
import pytest
import httpx

from app.services import prompt_preprocessor as pp
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
    lyrics_refiner_auth_email = ""
    lyrics_refiner_auth_password = ""
    lyrics_refiner_temperature = 0.7


async def _run(profile: dict):
    return await preprocess_generation(
        settings=DummySettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile=profile,
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[{"title": "Track 1", "bpm": 112}],
    )


@pytest.mark.asyncio
async def test_preprocess_builds_lyrics_for_vocal_mode():
    out = await _run({"lyrics_mode": "vocal_forward", "clean_lyrics_only": True, "topic_ideas": ["night drive"]})
    assert out.source == "local-template"
    assert out.lyrics is not None
    assert "[INTRO]" in out.lyrics
    assert "[PRE-CHORUS]" in out.lyrics
    assert "[CHORUS]" in out.lyrics
    assert "[FINAL CHORUS]" in out.lyrics
    assert "[OUTRO]" in out.lyrics
    assert "Theme anchors:" not in out.lyrics
    assert "User-generated custom station." not in out.lyrics
    assert "kick" not in out.lyrics.lower()
    assert "snare" not in out.lyrics.lower()
    assert out.prompt.startswith("1) MUSIC CAPTION:")
    assert "\n\n2) TECHNICAL PARAMETERS:\n" in out.prompt
    assert "\n\n3) LYRICS:\n" in out.prompt
    assert "Duration: " in out.prompt
    assert out.technical_parameters is not None
    assert out.technical_parameters["BPM"].isdigit()


@pytest.mark.asyncio
async def test_preprocess_threads_voice_profile_and_concrete_topic_into_caption():
    voice = {
        "id": "male_dark_alt",
        "gender": "male",
        "vocal_tone": "dark, tense alternative tone",
        "delivery": "close brooding verses",
        "range_hint": "low to mid register",
        "negative_prompt_terms": ["no bright pop smile"],
    }
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
        voice_profile=voice,
    )

    assert "Vocal profile:" in out.music_caption
    assert "dark, tense alternative tone" in out.prompt
    assert "arcade goodbye" in out.prompt.lower()
    assert out.diagnostics["voice_profile"]["id"] == "male_dark_alt"
    assert out.lyrics is not None
    assert "Song concept:" not in out.lyrics
    assert "Vocal profile:" not in out.lyrics


@pytest.mark.asyncio
async def test_preprocess_generates_different_lyrics_per_track_for_same_station():
    profile = {"lyrics_mode": "vocal_forward", "clean_lyrics_only": True, "topic_ideas": ["night drive"]}
    a = await _run(profile)
    b = await _run(profile)
    assert a.lyrics is not None
    assert b.lyrics is not None
    assert a.lyrics != b.lyrics


@pytest.mark.asyncio
async def test_preprocess_omits_lyrics_for_instrumental():
    out = await _run({"lyrics_mode": "instrumental_only"})
    assert out.lyrics is None
    assert "3) LYRICS:" in out.prompt


@pytest.mark.asyncio
async def test_preprocess_forces_ascii_english():
    out = await preprocess_generation(
        settings=DummySettings(),
        station_name="Caf\u00e9 M\u00fcnchen",
        station_description="Nuit \u00e9lectrique \u2014 c\u0153ur et d\u00e9sir.",
        genre="Synthwave",
        personality="DJ Ren\u00e9",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward"},
        base_prompt="R\u00e9sum\u00e9 this style.",
        negative_prompt="\u00e9viter la distorsion",
        recent_tracks=[],
    )
    assert out.prompt.isascii()
    assert out.negative_prompt.isascii()
    assert out.lyrics is None or out.lyrics.isascii()


@pytest.mark.asyncio
async def test_preprocess_uses_dedicated_remote_lyrics_when_configured(monkeypatch):
    class LyricsSettings(DummySettings):
        lyrics_refiner_base_urls = "http://openwebui.local"
        lyrics_refiner_model = "qwen2.5"

    async def fake_remote_lyrics(**kwargs: object):
        brief = kwargs.get("song_brief") if isinstance(kwargs.get("song_brief"), dict) else {}
        setting = str(brief.get("setting") or "chrome dashboard glow")
        conflict = str(brief.get("conflict") or "the past keeps calling while the road demands a choice")
        hook = str(brief.get("hook_concept") or "the message I cannot ignore")
        image = str((brief.get("imagery_bank") or ["tail lights"])[0]) if isinstance(brief.get("imagery_bank"), list) else "tail lights"
        return (
            f"[INTRO]\n{image.title()} marks the city escape before the turn\n\n"
            "[VERSE 1]\nI stand inside the chrome dashboard glow\n"
            f"The scene is {setting}\n"
            f"{conflict.capitalize()}\n"
            "Cassette hiss keeps the message honest\n\n"
            "[CHORUS]\nCity escape is the message I cannot ignore\n"
            f"{hook.capitalize()}\n"
            f"{image.title()} catches the warning in a sharper light\n"
            "I choose the road before it chooses me\n\n"
            "[VERSE 2]\nThe violet signs lean over the last lane\n"
            "Blue rain turns the old promise into proof\n"
            "The message arrives with no room left for hiding\n"
            "Tail lights pull the memory out of reach\n\n"
            "[BRIDGE]\nThe key ring shakes against the payphone shelf\n"
            f"{setting.capitalize()} keeps the proof in view\n"
            "I stop treating the warning like weather\n\n"
            "[FINAL CHORUS]\nCity escape becomes the turn I finally take\n"
            f"{hook.capitalize()} before the fade\n"
            f"{image.title()} answers back in a different light\n"
            "I leave with proof and not a slogan\n",
            "http://openwebui.local",
        )

    monkeypatch.setattr(pp, "_try_remote_lyrics", fake_remote_lyrics)

    out = await preprocess_generation(
        settings=LyricsSettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward", "topic_ideas": ["city escape"]},
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )

    assert out.lyrics is not None
    assert "chrome dashboard glow" in out.lyrics.lower()
    assert out.diagnostics["lyrics_source"] == "openwebui:http://openwebui.local"
    assert out.diagnostics["lyrics_model"] == "qwen2.5"
    assert out.diagnostics["remote_prompt_version"] == "cinematic-brief-v2"
    assert out.diagnostics["quality_repair_attempted"] is False
    assert out.diagnostics["quality_repair_success"] is False
    assert isinstance(out.diagnostics.get("suggested_title"), str)
    assert str(out.diagnostics.get("suggested_title")).strip() != ""


@pytest.mark.asyncio
async def test_preprocess_stores_failed_remote_quality_and_keeps_final_quality(monkeypatch):
    class LyricsSettings(DummySettings):
        lyrics_refiner_base_urls = "http://openwebui.local"
        lyrics_refiner_model = "qwen2.5"

    async def fake_remote_lyrics(**kwargs: object):
        if kwargs.get("quality_reasons"):
            return None, None, None
        return (
            "[VERSE 1]\n"
            "We rise through the night under city lights\n"
            "We shine and feel alive right here right now\n\n"
            "[CHORUS]\n"
            "We rise through the night under city lights\n"
            "We rise through the night under city lights\n",
            "http://openwebui.local",
            "Generic Draft",
        )

    monkeypatch.setattr(pp, "_try_remote_lyrics", fake_remote_lyrics)

    out = await preprocess_generation(
        settings=LyricsSettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward", "topic_ideas": ["arcade goodbye"]},
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )

    initial_quality = out.diagnostics["remote_initial_quality"]
    final_quality = out.diagnostics["lyric_quality"]
    assert initial_quality["passed"] is False
    assert "generic_filler_phrases" in initial_quality["reasons"]
    assert final_quality["passed"] is True
    assert final_quality != initial_quality
    assert out.diagnostics["remote_initial_title"] == "Generic Draft"
    assert out.diagnostics["remote_initial_source"] == "openwebui:http://openwebui.local"
    assert len(out.diagnostics["remote_initial_excerpt"].splitlines()) <= 8
    assert out.diagnostics["lyrics_source"].endswith(":strict_local_fallback")


@pytest.mark.asyncio
async def test_preprocess_stores_repair_quality_as_final_when_accepted(monkeypatch):
    class LyricsSettings(DummySettings):
        lyrics_refiner_base_urls = "http://openwebui.local"
        lyrics_refiner_model = "qwen2.5"

    async def fake_remote_lyrics(**kwargs: object):
        if kwargs.get("quality_reasons"):
            brief = kwargs.get("song_brief") if isinstance(kwargs.get("song_brief"), dict) else {}
            repaired = pp._strict_local_lyrics_from_brief(
                song_brief=brief,
                genre=str(kwargs.get("genre") or ""),
                voice_profile=None,
            )
            return repaired, "http://openwebui.local", "Repair Draft"
        return (
            "[VERSE 1]\n"
            "City lights keep the signal strong\n\n"
            "[CHORUS]\n"
            "City lights keep the signal strong\n"
            "City lights keep the signal strong\n",
            "http://openwebui.local",
            "Weak Draft",
        )

    monkeypatch.setattr(pp, "_try_remote_lyrics", fake_remote_lyrics)

    out = await preprocess_generation(
        settings=LyricsSettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward", "topic_ideas": ["arcade goodbye"]},
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )

    assert out.diagnostics["remote_initial_quality"]["passed"] is False
    assert out.diagnostics["remote_repair_quality"]["passed"] is True
    assert out.diagnostics["remote_repair_title"] == "Repair Draft"
    assert out.diagnostics["remote_repair_source"] == "openwebui:http://openwebui.local"
    assert out.diagnostics["lyric_quality"] == out.diagnostics["remote_repair_quality"]
    assert out.diagnostics["lyrics_source"] == "openwebui:http://openwebui.local:quality_repair"


@pytest.mark.asyncio
async def test_preprocess_stores_remote_empty_lyrics_error(monkeypatch):
    class LyricsSettings(DummySettings):
        lyrics_refiner_base_urls = "http://openwebui.local"
        lyrics_refiner_model = "qwen2.5"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"title": "No Words", "lyrics": ""})}}
                    ]
                },
            )
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    out = await preprocess_generation(
        settings=LyricsSettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward", "topic_ideas": ["arcade goodbye"]},
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )

    assert out.diagnostics["remote_initial_error"] == "empty_lyrics"
    assert "Traceback" not in out.diagnostics["remote_initial_error"]


@pytest.mark.asyncio
async def test_preprocess_sets_remote_initial_parse_shape_for_list_payload(monkeypatch):
    class LyricsSettings(DummySettings):
        lyrics_refiner_base_urls = "http://openwebui.local"
        lyrics_refiner_model = "tinyllama:latest"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            content = json.dumps(
                {
                    "title": "Tiny List",
                    "lyrics": [
                        {"type": "lyric", "text": "[INTRO]"},
                        {"type": "chord", "text": "G#m"},
                        {"type": "verse", "text": "Glass on the stairwell catches my sleeve"},
                        {"type": "chorus", "text": "[CHORUS]\nThe exit sign knows what I carried"},
                        {"type": "outro", "text": "[OUTRO]\nThe doorway keeps the last word"},
                    ],
                }
            )
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        if request.url.path.endswith("/api/v1/chats/new"):
            return httpx.Response(200, json={"id": "chat-123"})
        if request.url.path.endswith("/api/v1/chats/chat-123"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    out = await preprocess_generation(
        settings=LyricsSettings(),
        station_name="Neon Harbor",
        station_description="Retro city pulse and chrome midnight air.",
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        mood="rise",
        station_profile={"lyrics_mode": "vocal_forward", "topic_ideas": ["arcade goodbye"]},
        base_prompt="Generate a full, radio-ready Synthwave track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )

    assert out.diagnostics["remote_initial_parse_shape"] == "list_text_objects"
    assert "remote_initial_error" not in out.diagnostics


def test_compact_lyric_excerpt_bounds_lines():
    lyrics = "\n".join(f"line {idx}" for idx in range(20))
    excerpt = pp.compact_lyric_excerpt(lyrics, max_lines=5)
    assert excerpt.splitlines() == ["line 0", "line 1", "line 2", "line 3", "line 4"]


def test_finalize_lyrics_for_generator_strips_meta_and_formats_sections():
    sample = (
        "[Intro]\nNeon hum\n\n"
        "[Verse 1]\nCity lights\n\n"
        "[Bridge]\nTone: confident and hook-heavy. Theme anchors: boss fights.\n"
        "Keep language clean and radio-safe.\n\n"
        "[Final Chorus]\nStay in the signal\n\n"
        "[Outro]\nNight is ours\n"
    )
    out = pp._finalize_lyrics_for_generator(sample)
    assert out is not None
    assert "[Intro]" not in out
    assert "[INTRO]" in out
    assert "[VERSE 1]" in out
    assert "[FINAL CHORUS]" in out
    assert "Tone:" not in out
    assert "Keep language clean" not in out


def test_extract_title_and_lyrics_supports_section_object_json():
    sample = json.dumps(
        {
            "title": "Failed Escape",
            "lyrics": {
                "[INTRO]": "Glass walls",
                "[VERSE 1]": "Wires wrap tight",
                "[PRE-CHORUS]": "Strained breath",
                "[CHORUS]": "Failed escape",
                "[VERSE 2]": "Steel door clangs",
                "[BRIDGE]": "Hands against bars",
                "[FINAL CHORUS]": "Endless night",
                "[OUTRO]": "Glass shatters",
            },
        }
    )
    title, lyrics = pp._extract_title_and_lyrics(sample)
    assert title == "Failed Escape"
    assert "[INTRO]\nGlass walls" in lyrics
    assert "[VERSE 1]\nWires wrap tight" in lyrics
    assert "[FINAL CHORUS]\nEndless night" in lyrics


def test_extract_title_and_lyrics_supports_tinyllama_list_object_json():
    sample = json.dumps(
        {
            "title": "Test",
            "lyrics": [
                {"type": "lyric", "text": "[INTRO]"},
                {"type": "chord", "text": "G#m"},
                {"type": "verse", "text": "Glass on the stairwell catches my sleeve"},
                {"type": "metadata", "text": "tempo 120"},
                {"type": "chorus", "text": "[CHORUS]\nThe exit sign knows what I carried"},
                {"type": "bridge", "text": "Keys on the counter make the verdict plain"},
            ],
        }
    )

    title, lyrics, shape = pp._extract_title_lyrics_and_shape(sample)

    assert title == "Test"
    assert shape == "list_text_objects"
    assert "[INTRO]" in lyrics
    assert "Glass on the stairwell catches my sleeve" in lyrics
    assert "[CHORUS]" in lyrics
    assert "Keys on the counter make the verdict plain" in lyrics
    assert "G#m" not in lyrics
    assert "tempo 120" not in lyrics


def test_extract_title_and_lyrics_supports_list_strings():
    sample = json.dumps(
        {
            "title": "String List",
            "lyrics": [
                "[INTRO]",
                "Neon reflects across the receipt",
                "F#m",
                "[OUTRO]",
                "The doorway keeps the last word",
            ],
        }
    )

    title, lyrics, shape = pp._extract_title_lyrics_and_shape(sample)

    assert title == "String List"
    assert shape == "list_strings"
    assert "Neon reflects across the receipt" in lyrics
    assert "The doorway keeps the last word" in lyrics
    assert "F#m" not in lyrics


@pytest.mark.asyncio
async def test_remote_lyrics_records_list_parse_shape_without_request_failed(monkeypatch):
    diagnostics: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            content = json.dumps(
                {
                    "title": "Tiny List",
                    "lyrics": [
                        {"type": "lyric", "text": "[INTRO]"},
                        {"type": "chord", "text": "G#m"},
                        {"type": "verse", "text": "Glass on the stairwell catches my sleeve"},
                        {"type": "chorus", "text": "[CHORUS]\nThe exit sign knows what I carried"},
                        {"type": "outro", "text": "[OUTRO]\nThe doorway keeps the last word"},
                    ],
                }
            )
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        if request.url.path.endswith("/api/v1/chats/new"):
            return httpx.Response(200, json={"id": "chat-123"})
        if request.url.path.endswith("/api/v1/chats/chat-123"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="tinyllama:latest",
        api_key=None,
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.7,
        genre="Synthwave",
        title="Tiny List",
        mood="rise",
        topic="arcade goodbye",
        clean_lyrics_only=True,
        station_name="Neon Harbor",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="tinylist",
        diagnostics=diagnostics,
    )

    assert title == "Tiny List"
    assert source == "http://openwebui.local"
    assert lyrics is not None
    assert "Glass on the stairwell catches my sleeve" in lyrics
    assert "G#m" not in lyrics
    assert diagnostics["parse_shape"] == "list_text_objects"
    assert not str(diagnostics.get("error", "")).startswith("request_failed")


@pytest.mark.asyncio
async def test_remote_lyrics_request_failure_includes_http_status(monkeypatch):
    diagnostics: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            return httpx.Response(400, json={"detail": "bad request"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="tinyllama:latest",
        api_key=None,
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.7,
        genre="Synthwave",
        title="Tiny List",
        mood="rise",
        topic="arcade goodbye",
        clean_lyrics_only=True,
        station_name="Neon Harbor",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="tinylist",
        diagnostics=diagnostics,
    )

    assert lyrics is None
    assert source is None
    assert title is None
    assert diagnostics["error"] == "request_failed:400"


@pytest.mark.asyncio
async def test_remote_lyrics_request_failure_preserves_model_not_found(monkeypatch):
    diagnostics: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            return httpx.Response(400, json={"detail": "Model not found"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="missing-model",
        api_key=None,
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.7,
        genre="Synthwave",
        title="Tiny List",
        mood="rise",
        topic="arcade goodbye",
        clean_lyrics_only=True,
        station_name="Neon Harbor",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="tinylist",
        diagnostics=diagnostics,
    )

    assert lyrics is None
    assert source is None
    assert title is None
    assert diagnostics["error"] == "request_failed:400:model_not_found"


def test_finalize_lyrics_for_generator_strips_production_terms():
    sample = (
        "[Verse 1]\n"
        "The kick lands first and the snare cracks hard\n"
        "Streetlights blur while we race the skyline\n"
    )
    out = pp._finalize_lyrics_for_generator(sample)
    assert out is not None
    assert "kick" not in out.lower()
    assert "snare" not in out.lower()
    assert "Streetlights blur" in out


def test_derive_lyric_style_guidance_filters_production_jargon():
    text = pp._derive_lyric_style_guidance(
        genre="classic rock",
        taste_hints=["anthemic", "kick heavy", "snare snaps", "open highway"],
        mood="rise",
    )
    assert "kick" not in text.lower()
    assert "snare" not in text.lower()
    assert "anthemic" in text.lower()


def test_choose_song_topic_ignores_musical_metadata_taste_hints():
    topic = pp._choose_song_topic(
        {
            "topic_ideas": [],
            "taste_hints": [
                "aggressive mid-tempo pulse",
                "gritty strained male vocals",
                "psychological entrapment and failed escape cycles",
            ],
        },
        "peak",
        genre="Nu-Metal",
        daypart="night",
        recent_tracks=[],
        salt="fixed",
    )
    lowered = topic.lower()
    assert "tempo" not in lowered
    assert "pulse" not in lowered
    assert "vocals" not in lowered


def test_genre_lyric_direction_for_nu_metal_blocks_city_lights_language():
    direction, avoid = pp._genre_lyric_direction(
        genre="Nu-Metal",
        taste_hints=["Nine Inch Nails and Deftones inspired", "dark oppressive"],
        mood="peak",
    )
    assert "claustrophobic" in direction.lower()
    assert "city-lights freedom" in avoid.lower()


def test_suggest_track_title_avoids_seed_mood_words():
    title = pp.suggest_track_title(
        genre="synthwave",
        mood="baseline",
        topic="",
        daypart="evening",
        personality="Neon host",
        salt="x1",
    )
    assert "Baseline" not in title


def test_choose_song_topic_uses_genre_fallback_not_baseline_momentum():
    topic = pp._choose_song_topic(
        {"topic_ideas": [], "taste_hints": []},
        "baseline",
        genre="trap",
        daypart="late_night",
        recent_tracks=[],
        salt="fixed",
    )
    assert topic.strip()
    assert topic.lower() != "baseline momentum"


def test_choose_song_topic_for_nu_metal_uses_dark_genre_fallbacks():
    topic = pp._choose_song_topic(
        {"topic_ideas": [], "taste_hints": []},
        "peak",
        genre="Nu-Metal",
        daypart="night",
        recent_tracks=[],
        salt="fixed",
    )
    lowered = topic.lower()
    assert lowered in {
        "failed escape cycle",
        "psychological entrapment",
        "glass city breakdown",
        "pressure in wires",
        "fractured identity",
        "static in blood",
    }


@pytest.mark.asyncio
async def test_preprocess_nu_metal_lyrics_avoid_generic_city_uplift():
    out = await preprocess_generation(
        settings=DummySettings(),
        station_name="Nu-Metal",
        station_description="Industrial pressure and neon glass confinement.",
        genre="Nu-Metal",
        personality="Strained Signal",
        daypart="night",
        mood="peak",
        station_profile={
            "lyrics_mode": "vocal_forward",
            "clean_lyrics_only": True,
            "taste_hints": [
                "Nine Inch Nails and Deftones inspired",
                "dark oppressive",
                "psychological entrapment and failed escape cycles",
            ],
        },
        base_prompt="Generate a full, radio-ready Nu-Metal track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )
    assert out.lyrics is not None
    lowered = out.lyrics.lower()
    assert "streetlights roll" not in lowered
    assert "skyline pulls us through" not in lowered
    assert "city turns us loose" not in lowered
    assert any(token in lowered for token in ["glass", "wires", "sealed", "pressure", "static", "fracture"])


def test_choose_song_topic_avoids_recent_topic_when_options_exist():
    topic = pp._choose_song_topic(
        {"topic_ideas": ["night drive", "city escape"], "taste_hints": ["neon skyline"]},
        "baseline",
        genre="synthwave",
        daypart="night",
        recent_tracks=[{"song_topic": "night drive"}],
        salt="fixed",
    )
    assert pp._clean_topic_phrase(topic).lower() != "night drive"


def test_choose_song_topic_prefers_topic_ideas_when_present():
    topic = pp._choose_song_topic(
        {"topic_ideas": ["loot and rewards", "boss fights"], "taste_hints": ["gaming grind"]},
        "baseline",
        genre="trap",
        daypart="night",
        recent_tracks=[],
        salt="fixed",
    )
    cleaned = pp._clean_topic_phrase(topic).lower()
    assert cleaned.startswith("loot rewards") or cleaned.startswith("boss fights")


@pytest.mark.asyncio
async def test_preprocess_song_topic_not_locked_to_baseline_momentum():
    out = await preprocess_generation(
        settings=DummySettings(),
        station_name="Trap Afterhours",
        station_description="Dark room pulse and sharp focus.",
        genre="Trap",
        personality="Riot Bloom",
        daypart="night",
        mood="baseline",
        station_profile={"lyrics_mode": "vocal_forward", "clean_lyrics_only": True},
        base_prompt="Generate a full, radio-ready Trap track.",
        negative_prompt="avoid clipping",
        recent_tracks=[],
    )
    song_topic = str((out.diagnostics or {}).get("song_topic", "")).strip().lower()
    assert song_topic
    assert song_topic != "baseline momentum"


def test_lyrics_template_detector_blocks_known_boilerplate():
    bad = (
        "Verse 1:\n"
        "We move through the noise with our heads held high\n"
        "The night keeps turning and the signal stays strong\n"
        "We lean into baseline, where we know we belong\n"
        "\nChorus:\n"
        "Stay in the signal, stay in the sound\n"
        "We rise then settle when the beat comes around\n"
        "Hold this moment, frame by frame, in time\n"
    )
    assert pp._lyrics_is_too_templatey(bad) is True


@pytest.mark.asyncio
async def test_remote_lyrics_uses_signin_token_after_401(monkeypatch):
    calls = {"chat": 0, "signin": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            calls["chat"] += 1
            auth = request.headers.get("Authorization", "")
            if auth == "Bearer jwt-token-1":
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "[Intro]\\nHi\\n[Verse 1]\\nHello"}}]},
                )
            return httpx.Response(401, json={"detail": "Unauthorized"})
        if request.url.path.endswith("/api/v1/auths/signin"):
            calls["signin"] += 1
            return httpx.Response(200, json={"token": "jwt-token-1"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    pp._AUTH_TOKEN_CACHE.clear()

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5:3b",
        api_key=None,
        auth_email="user@example.com",
        auth_password="pw",
        timeout_seconds=3,
        temperature=0.7,
        genre="synthwave",
        title="City Lights",
        mood="rise",
        topic="night drive",
        clean_lyrics_only=True,
        station_name="Neon Harbor",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="abc123",
    )
    assert lyrics is not None
    assert source == "http://openwebui.local"
    assert title is None
    assert calls["signin"] == 1
    assert calls["chat"] == 2


@pytest.mark.asyncio
async def test_remote_lyrics_prompt_contains_song_brief_voice_and_negative_blocks(monkeypatch):
    captured = {"system": "", "user": ""}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/chat/completions"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["system"] = str(payload["messages"][0]["content"])
            captured["user"] = str(payload["messages"][1]["content"])
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": "Blue Exit Lights",
                                        "lyrics": "[INTRO]\nBlue exit lights\n\n[VERSE 1]\nReceipt ink on my sleeve",
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        if path.endswith("/api/v1/chats/new"):
            return httpx.Response(200, json={"id": "chat-123"})
        if path.endswith("/api/v1/chats/chat-123"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    song_brief = {
        "topic": "arcade goodbye",
        "angle": "a paper wristband turns arcade goodbye into proof that daylight can ruin",
        "narrator": "door person stamping wrists like tiny verdicts",
        "setting": "neon bathroom with marker on the mirror",
        "conflict": "two people pretend not to notice the packed bag by the door",
        "emotional_turn": "bravado drops into a private apology",
        "hook_concept": "the chorus should feel handwritten on the back of a wristband",
        "chorus_strategy": "repeat the title only at the end of the chorus",
        "imagery_bank": ["paper wristband", "blue exit lights", "receipt ink"],
        "title_seed": "After the Wristband",
    }
    voice_profile = {
        "gender": "female",
        "vocal_tone": "airy, glassy synth-pop tone",
        "delivery": "floating lead with long vowels",
        "range_hint": "upper register",
    }

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5",
        api_key="token",
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.7,
        genre="Synthwave",
        title="After the Wristband",
        mood="release",
        topic="arcade goodbye",
        clean_lyrics_only=True,
        station_name="Neon Harbor",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="briefprompt",
        voice_profile=voice_profile,
        song_brief=song_brief,
        lyric_constraints={"tempo_range_bpm": "96-122", "key_hint": "D major", "time_signature": "4/4", "target_duration_sec": 212, "lyrics_mode": "vocal_forward"},
    )

    prompt_text = f"{captured['system']}\n{captured['user']}"
    assert lyrics is not None
    assert source == "http://openwebui.local"
    assert title == "Blue Exit Lights"
    assert "professional songwriter" in captured["system"]
    assert "not an AI assistant" in captured["system"]
    assert "SONG BRIEF FIELDS TO USE STRONGLY" in captured["user"]
    assert "door person stamping wrists like tiny verdicts" in captured["user"]
    assert "neon bathroom with marker on the mirror" in captured["user"]
    assert "two people pretend not to notice the packed bag by the door" in captured["user"]
    assert "bravado drops into a private apology" in captured["user"]
    assert "the chorus should feel handwritten on the back of a wristband" in captured["user"]
    assert "repeat the title only at the end of the chorus" in captured["user"]
    assert "Vocal profile: female; airy, glassy synth-pop tone" in captured["user"]
    assert "NEGATIVE INSTRUCTION BLOCK" in captured["user"]
    for phrase in ["we rise", "feel alive", "through the night", "city lights", "signal strong", "hands up", "never let go"]:
        assert phrase in prompt_text


@pytest.mark.asyncio
async def test_remote_lyrics_repair_prompt_includes_failure_reasons(monkeypatch):
    captured = {"user": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["user"] = str(payload["messages"][1]["content"])
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "title": "Receipt Under Glass",
                                        "lyrics": "[INTRO]\nReceipt under glass\n\n[VERSE 1]\nThe diner booth waits",
                                    }
                                )
                            }
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)

    lyrics, source, _ = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5",
        api_key="token",
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.82,
        genre="Pop",
        title="Receipt Under Glass",
        mood="release",
        topic="hard apology",
        clean_lyrics_only=True,
        station_name="Neon Harbor",
        station_description="late night pop station",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="repairprompt",
        quality_reasons=["generic_filler_phrases", "song_brief_underused", "repeated_chorus_lines"],
        previous_lyrics="[CHORUS]\nWe rise through the night\nWe rise through the night",
    )

    assert lyrics is not None
    assert source == "http://openwebui.local"
    assert "QUALITY REPAIR PASS" in captured["user"]
    assert "generic_filler_phrases" in captured["user"]
    assert "song_brief_underused" in captured["user"]
    assert "repeated_chorus_lines" in captured["user"]
    assert "Remove all banned filler" in captured["user"]
    assert "Use the narrator, setting, conflict, hook concept" in captured["user"]
    assert "Previous weak draft excerpt to avoid copying" in captured["user"]


@pytest.mark.asyncio
async def test_remote_lyrics_returns_templatey_text_as_remote_fallback(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "Verse 1:\n"
                                    "We move through the noise with our heads held high\n"
                                    "The night keeps turning and the signal stays strong\n"
                                )
                            }
                        }
                    ]
                },
            )
        if request.url.path.endswith("/api/v1/auths/signin"):
            return httpx.Response(200, json={"token": "jwt-token-1"})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    pp._AUTH_TOKEN_CACHE.clear()

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5:latest",
        api_key=None,
        auth_email="user@example.com",
        auth_password="pw",
        timeout_seconds=3,
        temperature=0.7,
        genre="trap",
        title="City Escape",
        mood="baseline",
        topic="city escape",
        clean_lyrics_only=True,
        station_name="Trap Afterhours",
        station_description="night station",
        personality="Riot Bloom",
        recent_tracks=[],
        variation_salt="abc123",
    )

    assert lyrics is not None
    assert "signal stays strong" in lyrics
    assert source == "http://openwebui.local"
    assert title is None


@pytest.mark.asyncio
async def test_remote_lyrics_persists_chat_to_openwebui(monkeypatch):
    calls = {"chat_completion": 0, "chats_new": 0, "chats_update": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/chat/completions"):
            calls["chat_completion"] += 1
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "[Intro]\\nGlow\\n[Verse 1]\\nRide"}}]},
            )
        if path.endswith("/api/v1/chats/new"):
            calls["chats_new"] += 1
            return httpx.Response(200, json={"id": "chat-123"})
        if path.endswith("/api/v1/chats/chat-123"):
            calls["chats_update"] += 1
            payload = json.loads(request.content.decode("utf-8"))
            assert "chat" in payload
            assert payload["chat"].get("title", "").startswith("AIRadio Lyrics |")
            history = payload["chat"].get("history", {})
            assert isinstance(history.get("messages"), dict)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    pp._AUTH_TOKEN_CACHE.clear()

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5:latest",
        api_key="key",
        auth_email=None,
        auth_password=None,
        timeout_seconds=3,
        temperature=0.7,
        genre="synthwave",
        title="Neon Drive",
        mood="baseline",
        topic="night drive",
        clean_lyrics_only=True,
        station_name="Synthwave FM",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="abc123",
    )

    assert lyrics is not None
    assert source == "http://openwebui.local"
    assert title is None
    assert calls["chat_completion"] >= 1
    assert calls["chats_new"] == 1
    assert calls["chats_update"] == 1


@pytest.mark.asyncio
async def test_remote_lyrics_prompt_includes_music_constraints(monkeypatch):
    captured = {"user_prompt": ""}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/api/chat/completions"):
            payload = json.loads(request.content.decode("utf-8"))
            captured["user_prompt"] = str(payload["messages"][1]["content"])
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "[Intro]\\nGlow\\n[Verse 1]\\nRide"}}]},
            )
        if path.endswith("/api/v1/chats/new"):
            return httpx.Response(200, json={"id": "chat-123"})
        if path.endswith("/api/v1/chats/chat-123"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    transport = httpx.MockTransport(handler)

    class FakeAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    pp._AUTH_TOKEN_CACHE.clear()

    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5:latest",
        api_key="key",
        auth_email=None,
        auth_password=None,
        timeout_seconds=3,
        temperature=0.7,
        genre="synthwave",
        title="Neon Drive",
        mood="rise",
        topic="night drive",
        clean_lyrics_only=True,
        station_name="Synthwave FM",
        station_description="retro glow",
        personality="Velvet Static",
        recent_tracks=[],
        variation_salt="abc123",
        lyric_constraints={
            "tempo_range_bpm": "96-122",
            "key_hint": "D major",
            "time_signature": "4/4",
            "target_duration_sec": 212,
            "lyrics_mode": "mixed",
            "vocal_ratio": 40,
            "cohesion": 80,
            "discovery": 20,
            "mood_volatility": 30,
            "energy_variability": 30,
            "daypart": "evening",
        },
    )

    assert lyrics is not None
    assert "Tempo 96-122 BPM" in captured["user_prompt"]
    assert "key hint D major" in captured["user_prompt"]


@pytest.mark.asyncio
async def test_remote_lyrics_uses_compact_token_budget(monkeypatch):
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            observed["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "Failed Escape",
                                    "lyrics": "[INTRO]\nGlass walls\n\n[VERSE 1]\nWires wrap tight",
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)
    lyrics, source, _ = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5",
        api_key="token",
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.7,
        genre="Nu-Metal",
        title="Failed Escape",
        mood="peak",
        topic="failed escape cycle",
        clean_lyrics_only=True,
        station_name="Nu-Metal",
        station_description="desc",
        personality="voice",
        recent_tracks=[],
        variation_salt="x",
        taste_hints=["Nine Inch Nails and Deftones inspired"],
        lyric_constraints={"tempo_range_bpm": "108-150", "key_hint": "E minor", "time_signature": "4/4", "target_duration_sec": 215, "lyrics_mode": "vocal_forward"},
    )
    assert lyrics is not None
    body = observed["body"]
    assert isinstance(body, dict)
    assert body["max_tokens"] == 260
    assert source == "http://openwebui.local"


@pytest.mark.asyncio
async def test_remote_lyrics_rejects_variation_token_leak(monkeypatch):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/chat/completions"):
            calls["count"] += 1
            content = json.dumps(
                {
                    "title": "Failed Escape",
                    "lyrics": "[INTRO]\naudit123 in the wall\n\n[VERSE 1]\nWires wrap tight",
                }
            )
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(pp.httpx, "AsyncClient", Client)
    lyrics, source, title = await pp._try_remote_lyrics(
        base_urls=["http://openwebui.local"],
        model="qwen2.5",
        api_key="token",
        auth_email=None,
        auth_password=None,
        timeout_seconds=5,
        temperature=0.7,
        genre="Nu-Metal",
        title="Failed Escape",
        mood="peak",
        topic="failed escape cycle",
        clean_lyrics_only=True,
        station_name="Nu-Metal",
        station_description="desc",
        personality="voice",
        recent_tracks=[],
        variation_salt="audit123",
        taste_hints=["Nine Inch Nails and Deftones inspired"],
        lyric_constraints={"tempo_range_bpm": "108-150", "key_hint": "E minor", "time_signature": "4/4", "target_duration_sec": 215, "lyrics_mode": "vocal_forward"},
    )
    assert calls["count"] >= 1
    assert lyrics is None
    assert source is None
    assert title is None
