from app.services.voice_profiles import choose_voice_profile, format_voice_directive


def test_choose_voice_profile_rotates_away_from_recent_same_id():
    profile = choose_voice_profile(
        "synthwave pop",
        {},
        [{"voice_profile_id": "female_airy_synth"}, {"voice_profile_id": "female_bright_pop"}],
        "fixed",
    )

    assert profile["id"] not in {"female_airy_synth", "female_bright_pop"}
    assert profile["id"]


def test_choose_voice_profile_honors_station_override():
    profile = choose_voice_profile("rock", {"voice_profile_id": "male_dark_alt"}, [], "fixed")

    assert profile["id"] == "male_dark_alt"


def test_format_voice_directive_contains_actionable_vocal_shape():
    profile = choose_voice_profile("trap", {}, [], "fixed")
    directive = format_voice_directive(profile)

    assert directive.startswith("Vocal profile:")
    assert str(profile["gender"]) in directive
    assert str(profile["delivery"]) in directive
