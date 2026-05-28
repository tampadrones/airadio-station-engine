from app.schemas.station import StationCreateFromTaste, StationUpdate
from app.services.station_profile import infer_station_taste_hints, normalize_station_profile, reprofile_station_profile, slugify_station_name


def test_station_profile_defaults_and_clamps():
    profile = normalize_station_profile({"cohesion_spectrum": 200, "discovery_depth": -5, "lyrics_mode": "bad"})
    assert profile["cohesion_spectrum"] == 100
    assert profile["discovery_depth"] == 0
    assert profile["lyrics_mode"] == "mixed"
    assert profile["mood_seed"] == "baseline"
    assert profile["topic_ideas"] == []
    assert normalize_station_profile({"lyrics_mode": "instrumental"})["lyrics_mode"] == "instrumental_only"
    assert normalize_station_profile({"mood_seed": "peak"})["mood_seed"] == "peak"
    assert normalize_station_profile({"target_duration_sec": 320, "duration_max_sec": 320})["target_duration_sec"] == 320


def test_slugify_station_name():
    assert slugify_station_name("My Dream Station!!!") == "my-dream-station"


def test_station_create_from_taste_schema():
    payload = StationCreateFromTaste(name="X", genre="Lo-Fi", cohesion_spectrum=75, topic_ideas=["night drive"])
    assert payload.cohesion_spectrum == 75
    assert payload.topic_ideas == ["night drive"]


def test_reprofile_station_profile_merges_and_infers_hints():
    updated = reprofile_station_profile(
        current_profile={"cohesion_spectrum": 70, "taste_hints": ["warm pads"]},
        genre="Synthwave",
        personality="Velvet Static",
        description="Neon dusk cruiselanes and cinematic retro pulse.",
        overrides={"lyrics_mode": "vocal_forward"},
        include_inferred_taste_hints=True,
    )
    assert updated["cohesion_spectrum"] == 70
    assert updated["lyrics_mode"] == "vocal_forward"
    assert "warm pads" in updated["taste_hints"]
    assert "Synthwave" in updated["taste_hints"]


def test_infer_station_taste_hints_has_identity_fields():
    hints = infer_station_taste_hints(genre="Trap", personality="Riot Bloom", description="Dark kinetic rhythm and bass pressure.")
    assert hints[0] == "Trap"
    assert hints[1] == "Riot Bloom"


def test_station_update_schema_accepts_profile_fields():
    payload = StationUpdate(
        lyrics_mode="vocal_forward",
        mood_seed="rise",
        cohesion_spectrum=88,
        target_queue_depth=6,
        target_duration_sec=320,
        topic_ideas=["sunset"],
    )
    assert payload.lyrics_mode == "vocal_forward"
    assert payload.mood_seed == "rise"
    assert payload.cohesion_spectrum == 88
    assert payload.target_queue_depth == 6
    assert payload.target_duration_sec == 320
    assert payload.topic_ideas == ["sunset"]
