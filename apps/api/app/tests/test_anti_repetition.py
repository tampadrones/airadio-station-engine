from app.services.anti_repetition import anti_repetition_notes, is_too_similar


def test_anti_repetition_notes():
    note = anti_repetition_notes([{"bpm": 120, "energy_score": 0.6}])
    assert "avoid BPM" in note


def test_similarity_detection():
    assert is_too_similar("abc", ["abc", "def"])
    assert not is_too_similar("xyz", ["abc", "def"])
