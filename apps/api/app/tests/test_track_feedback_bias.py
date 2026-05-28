from __future__ import annotations

from datetime import datetime

from app.models.station import Station
from app.models.track import Track
from app.models.track_feedback import TrackFeedback
from app.models.track_generation import TrackGeneration
from app.models.enums import TrackStatus
from app.services.station_engine import StationEngine


def test_feedback_bias_collects_like_dislike_context(db_session):
    st = Station(
        slug="feedback-test",
        name="Feedback Test",
        genre="Synthwave",
        personality="DJ Neon",
        description="x",
        circadian_profile={},
        station_profile={},
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    tr_like = Track(station_id=st.id, title="Neon Drive", status=TrackStatus.aired, created_at=datetime.utcnow())
    tr_dislike = Track(station_id=st.id, title="Flatline Dawn", status=TrackStatus.aired, created_at=datetime.utcnow())
    db_session.add_all([tr_like, tr_dislike])
    db_session.commit()

    db_session.add_all(
        [
            TrackGeneration(
                track_id=tr_like.id,
                prompt_text="p",
                negative_prompt_text="n",
                generator_model="ace-step",
                generator_host="http://gen",
                genre="Synthwave",
                personality="DJ Neon",
                mood_state="rise",
                daypart="night",
                recent_context={
                    "preprocessor": {
                        "diagnostics": {"song_topic": "city afterglow"},
                        "ace_params": {"bpm": 108, "keyscale": "A minor"},
                    }
                },
            ),
            TrackGeneration(
                track_id=tr_dislike.id,
                prompt_text="p",
                negative_prompt_text="n",
                generator_model="ace-step",
                generator_host="http://gen",
                genre="Synthwave",
                personality="DJ Neon",
                mood_state="release",
                daypart="night",
                recent_context={
                    "preprocessor": {
                        "diagnostics": {"song_topic": "slow static"},
                        "ace_params": {"bpm": 88, "keyscale": "F major"},
                    }
                },
            ),
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            TrackFeedback(station_id=st.id, track_id=tr_like.id, session_id="s1", vote=1),
            TrackFeedback(station_id=st.id, track_id=tr_like.id, session_id="s2", vote=1),
            TrackFeedback(station_id=st.id, track_id=tr_dislike.id, session_id="s3", vote=-1),
        ]
    )
    db_session.commit()

    engine = StationEngine()
    bias = engine._build_feedback_bias(db_session, st)

    assert "city afterglow" in bias["liked_topics"]
    assert "slow static" in bias["disliked_topics"]
    assert "rise" in bias["liked_moods"]
    assert "release" in bias["disliked_moods"]
