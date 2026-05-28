from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.models.enums import StorageClass, TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.models.track_analysis import TrackAnalysis
from app.models.track_generation import TrackGeneration
from app.services.station_engine import StationEngine


def test_fit_gate_rejects_low_station_fit():
    engine = StationEngine()
    engine.settings.station_min_fit_score = 0.8
    engine.settings.station_min_qc_score = 0.4
    qc = SimpleNamespace(station_fit_score=0.6, qc_score=0.9)
    assert engine._fit_gate_reason(qc) == "station_fit_below_threshold"


def test_fit_gate_rejects_low_qc_score():
    engine = StationEngine()
    engine.settings.station_min_fit_score = 0.5
    engine.settings.station_min_qc_score = 0.7
    qc = SimpleNamespace(station_fit_score=0.9, qc_score=0.6)
    assert engine._fit_gate_reason(qc) == "qc_score_below_threshold"


def test_fit_gate_allows_good_scores():
    engine = StationEngine()
    engine.settings.station_min_fit_score = 0.5
    engine.settings.station_min_qc_score = 0.4
    qc = SimpleNamespace(station_fit_score=0.8, qc_score=0.8)
    assert engine._fit_gate_reason(qc) is None


def test_low_quality_title_flags_station_placeholders():
    assert StationEngine._is_low_quality_title("Synthwave Fm Baseline", "Synthwave FM") is True
    assert StationEngine._is_low_quality_title("Evening Synthwave Fm", "Synthwave FM") is True
    assert StationEngine._is_low_quality_title("Lo Fi Desk Echo", "Lo-Fi Desk") is True
    assert StationEngine._is_low_quality_title("Neon Skyline Anthem", "Synthwave FM") is False


def test_topic_from_existing_title_strips_station_and_generic_tokens():
    topic = StationEngine._topic_from_existing_title("GG Custom Track", "GG")
    assert topic == ""
    topic2 = StationEngine._topic_from_existing_title("Evening Speedrun Mindset", "GG")
    assert topic2 == "Evening Speedrun Mindset"


def test_title_from_generation_ignores_low_quality_hinted_title():
    engine = StationEngine()
    gen = SimpleNamespace(
        recent_context={"preprocessor": {"diagnostics": {"suggested_title": "Synthwave Fm Baseline", "song_topic": "neon skyline"}}},
        prompt_text="",
        genre="synthwave",
        mood_state="baseline",
        daypart="evening",
        personality="Retro host",
    )
    title = engine._title_from_generation(42, "Synthwave FM", gen)  # type: ignore[arg-type]
    assert title != "Synthwave Fm Baseline"


def test_enforce_title_quality_rewrites_weak_titles():
    engine = StationEngine()
    out = engine._enforce_title_quality(
        title="Trap Afterhours Baseline",
        station_name="Trap Afterhours",
        genre="trap",
        topic="final boss energy",
        salt="abc",
    )
    assert out != "Trap Afterhours Baseline"
    assert "Baseline" not in out


def test_build_reuse_title_collapses_suffix_chain_and_caps_length():
    chained = "Evening Synthwave " + " (reused)" * 25
    out = StationEngine._build_reuse_title(chained)
    assert out.endswith(" (reused)")
    assert out.lower().count("(reused)") == 1
    assert len(out) <= 200


def test_pick_reuse_candidate_prefers_fit_and_non_reused_title(db_session, tmp_path):
    st = Station(slug="sw", name="Synthwave FM", genre="Synthwave", personality="Host", description="d", circadian_profile={}, station_profile={"mood_seed": "baseline"})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    a_path = tmp_path / "a.wav"
    b_path = tmp_path / "b.wav"
    a_path.write_bytes(b"wave-a")
    b_path.write_bytes(b"wave-b")

    now = datetime.utcnow()
    track_a = Track(
        station_id=st.id,
        title="Neon Circuit",
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        file_path=str(a_path),
        aired_at=now - timedelta(hours=30),
    )
    track_b = Track(
        station_id=st.id,
        title="Retro Pulse (reused)",
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        file_path=str(b_path),
        aired_at=now - timedelta(hours=40),
    )
    db_session.add_all([track_a, track_b])
    db_session.commit()
    db_session.refresh(track_a)
    db_session.refresh(track_b)

    db_session.add(
        TrackAnalysis(
            track_id=track_a.id,
            station_fit_score=0.92,
            qc_score=0.88,
            replay_score=0.90,
            tags={"daypart": "evening", "mood": "baseline"},
        )
    )
    db_session.add(
        TrackAnalysis(
            track_id=track_b.id,
            station_fit_score=0.45,
            qc_score=0.40,
            replay_score=0.30,
            tags={"daypart": "evening", "mood": "baseline"},
        )
    )
    db_session.add(
        TrackGeneration(
            track_id=track_a.id,
            prompt_text="p",
            negative_prompt_text="",
            generator_model="m",
            generator_host="h",
            generation_seconds=1.0,
            seed=1,
            genre="Synthwave",
            personality="Host",
            mood_state="baseline",
            daypart="evening",
            recent_context={},
        )
    )
    db_session.add(
        TrackGeneration(
            track_id=track_b.id,
            prompt_text="p",
            negative_prompt_text="",
            generator_model="m",
            generator_host="h",
            generation_seconds=1.0,
            seed=2,
            genre="Synthwave",
            personality="Host",
            mood_state="baseline",
            daypart="evening",
            recent_context={},
        )
    )
    db_session.commit()

    engine = StationEngine()
    picked = engine._pick_reuse_candidate(db_session, st)
    assert picked is not None
    assert picked.id == track_a.id


def test_ensure_unique_title_avoids_recent_duplicates(db_session):
    st = Station(
        slug="dup-title",
        name="Dup Title FM",
        genre="Synthwave",
        personality="Host",
        description="d",
        circadian_profile={},
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    db_session.add_all(
        [
            Track(
                station_id=st.id,
                title="Respawn Mentality Respawn",
                status=TrackStatus.aired,
                storage_class=StorageClass.hot,
            ),
            Track(
                station_id=st.id,
                title="Respawn Mentality Respawn",
                status=TrackStatus.queued,
                storage_class=StorageClass.hot,
            ),
        ]
    )
    db_session.commit()

    engine = StationEngine()
    out = engine._ensure_unique_title(
        db=db_session,
        station=st,
        base_title="Respawn Mentality Respawn",
        genre="Trap",
        mood="peak",
        topic="respawn mentality",
        daypart="night",
        personality="Host",
    )
    assert out != "Respawn Mentality Respawn"


def test_resolve_target_duration_uses_station_profile_controls():
    engine = StationEngine()
    duration = engine._resolve_target_duration_sec(
        genre="Trap",
        daypart="night",
        mood="peak",
        station_profile={
            "target_duration_sec": 240,
            "duration_jitter_sec": 0,
            "duration_min_sec": 180,
            "duration_max_sec": 260,
            "vocal_ratio": 80,
            "lyrics_mode": "vocal_forward",
            "energy_variability": 20,
            "mood_volatility": 20,
        },
        lyrics_present=True,
        topic="victory lap",
    )
    # Peak mood reduces a little, but configured target envelope still drives output.
    assert 210 <= duration <= 260


def test_resolve_target_duration_allows_320_second_target():
    engine = StationEngine()
    duration = engine._resolve_target_duration_sec(
        genre="Post Rock",
        daypart="day",
        mood="baseline",
        station_profile={
            "target_duration_sec": 320,
            "duration_jitter_sec": 0,
            "duration_min_sec": 320,
            "duration_max_sec": 320,
            "vocal_ratio": 40,
            "lyrics_mode": "mixed",
            "energy_variability": 0,
            "mood_volatility": 0,
        },
        lyrics_present=True,
        topic="longform arc",
    )
    assert duration == 320


def test_build_ace_params_and_payload_include_extended_fields():
    engine = StationEngine()
    duration = 214
    params = engine._build_ace_params(
        genre="Synthwave",
        daypart="evening",
        mood="rise",
        station_profile={
            "cohesion_spectrum": 72,
            "discovery_depth": 38,
            "mood_volatility": 44,
            "energy_variability": 51,
            "vocal_ratio": 67,
            "lyrics_mode": "vocal_forward",
        },
        lyrics_present=True,
        topic="chrome horizon",
        duration_sec=duration,
    )
    payload = engine._build_ace_format_payload(
        prompt="caption",
        negative_prompt="negative",
        lyrics="Verse:",
        mood="rise",
        topic="chrome horizon",
        ace_params=params,
        duration_sec=duration,
    )
    assert payload is not None
    assert int(payload.get("duration", 0)) == duration
    assert payload.get("timesignature") == "4/4"
    assert isinstance(payload.get("keyscale"), str) and str(payload.get("keyscale")).strip()
    assert payload.get("thinking") == params.get("thinking")
    assert payload.get("use_cot_lyrics") == params.get("use_cot_lyrics")
    assert payload.get("cot_duration") == duration
    assert payload.get("cot_bpm") == payload.get("bpm")


def test_build_ace_params_fast_mode_uses_quick_profile():
    engine = StationEngine()
    params = engine._build_ace_params(
        genre="Synthwave",
        daypart="evening",
        mood="rise",
        station_profile={
            "cohesion_spectrum": 80,
            "discovery_depth": 25,
            "mood_volatility": 30,
            "energy_variability": 30,
            "vocal_ratio": 50,
            "lyrics_mode": "mixed",
        },
        lyrics_present=True,
        topic="neon night drive",
        duration_sec=180,
        fast_mode=True,
    )
    assert int(params.get("dit_inference_steps", 0)) == 8
    assert float(params.get("dit_guidance_scale", 9.9)) <= 6.0
    assert params.get("thinking") is False
    assert params.get("use_cot_metas") is False
    assert params.get("use_cot_lyrics") is False


def test_build_ace_payload_clears_template_audio_codes():
    engine = StationEngine()
    params = engine._build_ace_params(
        genre="Synthwave",
        daypart="evening",
        mood="rise",
        station_profile={},
        lyrics_present=False,
        topic="city lights",
        duration_sec=140,
    )
    payload = engine._build_ace_format_payload(
        prompt="caption",
        negative_prompt="negative",
        lyrics="",
        mood="rise",
        topic="city lights",
        ace_params=params,
        duration_sec=140,
    )
    assert payload is not None
    assert payload.get("audio_codes") == ""


def test_should_use_fast_mode_when_queue_below_min_ready(db_session):
    st = Station(
        slug="fast-mode",
        name="Fast Mode FM",
        genre="Synthwave",
        personality="Host",
        description="d",
        circadian_profile={},
        min_ready_tracks=3,
        target_queue_depth=6,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    enabled = StationEngine._should_use_fast_mode(
        db_session,
        station=st,
        ready_count=0,
        queued_count=1,
    )
    assert enabled is True
