from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.enums import Severity, TrackStatus
from app.models.track import Track
from app.services.ops_events import emit_event


def mark_stale_generating_tracks(db: Session, max_age_minutes: int = 8) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    stale = (
        db.query(Track)
        .filter(Track.status == TrackStatus.generating, Track.created_at < cutoff)
        .all()
    )
    for track in stale:
        track.status = TrackStatus.failed
        db.add(track)
        emit_event(
            db,
            service="worker",
            event_type="generation_failed",
            message="Marked stale generating track as failed",
            severity=Severity.warning,
            station_id=track.station_id,
            track_id=track.id,
            error_code="stale_generation_timeout",
        )
    return len(stale)
