from app.services.anti_repetition import anti_repetition_notes, is_text_too_similar, is_too_similar


def test_anti_repetition_notes():
    note = anti_repetition_notes(
        [{"title": "Night Drive", "bpm": 120, "energy_score": 0.6, "song_topic": "neon escape", "voice_profile_id": "female_airy_synth"}]
    )
    assert "avoid BPM" in note
    assert "neon escape" in note
    assert "female_airy_synth" in note


def test_similarity_detection():
    assert is_too_similar("abc", ["abc", "def"])
    assert not is_too_similar("xyz", ["abc", "def"])


def test_text_similarity_detection_for_prompt_concepts():
    assert is_text_too_similar("neon escape through midnight city", ["midnight neon city escape"])
    assert not is_text_too_similar("rain on the quiet desk", ["arena thunder highway"])
