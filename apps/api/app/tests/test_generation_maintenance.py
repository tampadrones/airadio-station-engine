from datetime import datetime, timedelta

from app.models.enums import TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.services.generation_maintenance import mark_stale_generating_tracks


def test_mark_stale_generating_tracks_respects_ttl(db_session):
    station = Station(
        slug="stale-check",
        name="Stale Check",
        genre="Rock",
        personality="Host",
        description="d",
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    stale_track = Track(
        station_id=station.id,
        title="Old inflight",
        status=TrackStatus.generating,
        created_at=datetime.utcnow() - timedelta(minutes=45),
    )
    fresh_track = Track(
        station_id=station.id,
        title="Fresh inflight",
        status=TrackStatus.generating,
        created_at=datetime.utcnow() - timedelta(minutes=5),
    )
    db_session.add_all([stale_track, fresh_track])
    db_session.commit()

    repaired = mark_stale_generating_tracks(db_session, max_age_minutes=30)
    db_session.commit()

    db_session.refresh(stale_track)
    db_session.refresh(fresh_track)
    assert repaired == 1
    assert stale_track.status == TrackStatus.failed
    assert fresh_track.status == TrackStatus.generating
