from app.services.prompt_builder import build_music_caption_formula, build_negative_prompt, build_prompt, build_technical_parameters


def test_prompt_builder_has_all_sections():
    prompt = build_prompt(
        genre="Synthwave",
        personality="Velvet Static",
        daypart="evening",
        daypart_bias="energetic",
        mood="rise",
        recent_tracks=[{"title": "A", "energy_score": 0.5, "bpm": 110, "tags": ["lush"]}],
        anti_repetition_notes="avoid same bpm",
    )
    assert "Synthwave" in prompt
    assert "1) MUSIC CAPTION:" in prompt
    assert "2) TECHNICAL PARAMETERS:" in prompt
    assert "3) LYRICS:" in prompt
    assert "Velvet Static" in prompt
    assert "evening" in prompt
    assert "avoid same bpm" in prompt
    assert "around 5:20" in prompt
    assert "BPM:" in prompt
    assert "Duration: 5:20" in prompt


def test_music_caption_and_technical_parameters_follow_required_shape():
    caption = build_music_caption_formula(
        genre="Nu-metal industrial rock",
        personality="Grit Host",
        mood="peak",
        daypart="night",
        station_profile={
            "taste_hints": ["Nine Inch Nails", "Deftones"],
            "topic_ideas": ["failed escape cycles"],
            "energy_variability": 78,
            "lyrics_mode": "vocal_forward",
        },
    )
    params = build_technical_parameters(
        genre="Nu-metal industrial rock",
        mood="peak",
        daypart="night",
        station_profile={"energy_variability": 78, "lyrics_mode": "vocal_forward"},
        duration_sec=215,
        topic="failed escape cycles",
    )
    assert len(caption.split(",")) >= 8
    assert "Nine Inch Nails" in caption
    assert params["BPM"].isdigit()
    assert params["Duration"] == "3:35"
    assert params["Time Signature"] == "4/4"
    assert params["Energy Level"] in {"Low", "Medium", "High", "Extreme"}
    assert params["Structure Density"] in {"Sparse", "Balanced", "Dense"}


def test_prompt_builder_uses_hard_genre_boundaries_for_rock():
    prompt = build_prompt(
        genre="80s big hair rock and roll",
        personality="Custom Host",
        daypart="evening",
        daypart_bias="energetic",
        mood="peak",
        recent_tracks=[],
        anti_repetition_notes="vary textures",
        station_profile={"lyrics_mode": "vocal_forward", "clean_lyrics_only": True, "topic_ideas": ["night drive"]},
    )
    assert "Hard genre boundary" in prompt
    assert "arena/hair rock" in prompt
    assert "clean/radio-safe" in prompt
    assert "Song topic ideas for upcoming vocal content: night drive." in prompt


def test_negative_prompt_has_exclusions():
    neg = build_negative_prompt(genre="80s big hair rock and roll", station_profile={"lyrics_mode": "vocal_forward"})
    assert "no trap hats" in neg
    assert "avoid obvious loops" in neg
