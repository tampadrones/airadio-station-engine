from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import re
from sqlalchemy.orm import Session

from playback.schemas import PlaybackTrack
from app.models.enums import TrackStatus
from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.models.track import Track
from app.services.playback_backend import get_playback_backend


def _origin_track_id(track: Track) -> int:
    name = Path(str(track.file_path or "")).name
    m = re.match(r"^reused_(\d+)_", name)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return int(track.id)
    return int(track.id)


def _dedupe_by_origin(items: list[Track]) -> list[Track]:
    out: list[Track] = []
    seen: set[int] = set()
    for t in items:
        oid = _origin_track_id(t)
        if oid in seen:
            continue
        seen.add(oid)
        out.append(t)
    return out


def sync_station_queue_export(db: Session, station: Station) -> int:
    backend = get_playback_backend()
    playback_state = db.query(StationPlaybackState).filter(StationPlaybackState.station_id == station.id).first()
    current_track_id = int(playback_state.current_track_id) if playback_state and playback_state.current_track_id else None

    export_limit = max(
        int(getattr(station, "target_queue_depth", 0) or 0),
        int(getattr(station, "min_ready_tracks", 0) or 0),
        8,
    )

    queue_tracks = (
        db.query(Track)
        .filter(
            Track.station_id == station.id,
            Track.status.in_([TrackStatus.queued, TrackStatus.ready]),
            Track.file_path.is_not(None),
            Track.deleted_at.is_(None),
        )
        # Prefer tracks that have not aired yet, then oldest generated first.
        # This avoids repeatedly exporting the same newest/fallback tracks.
        .order_by(Track.aired_at.asc().nullsfirst(), Track.created_at.asc())
        .limit(export_limit)
        .all()
    )

    if current_track_id and all(int(t.id) != current_track_id for t in queue_tracks):
        current_track = (
            db.query(Track)
            .filter(
                Track.id == current_track_id,
                Track.station_id == station.id,
                Track.status.in_([TrackStatus.queued, TrackStatus.ready, TrackStatus.aired]),
            )
            .first()
        )
        if current_track and current_track.file_path:
            queue_tracks = [current_track, *queue_tracks]

    queue_tracks = _dedupe_by_origin(queue_tracks)
    if len(queue_tracks) < 4:
        # During low-queue windows, avoid immediate audible loops while still
        # preferring recently aired tracks that are likely still on hot storage.
        cooldown_cutoff = datetime.utcnow() - timedelta(minutes=10)
        aired_candidates = (
            db.query(Track)
            .filter(
                Track.station_id == station.id,
                Track.status == TrackStatus.aired,
                Track.file_path.is_not(None),
                Track.aired_at.is_not(None),
                Track.aired_at <= cooldown_cutoff,
            )
            .order_by(Track.aired_at.desc())
            .limit(8)
            .all()
        )
        if len(aired_candidates) < 4:
            aired_candidates = (
                db.query(Track)
                .filter(
                    Track.station_id == station.id,
                    Track.status == TrackStatus.aired,
                    Track.file_path.is_not(None),
                    Track.aired_at.is_not(None),
                )
                .order_by(Track.aired_at.desc())
                .limit(8)
                .all()
            )
        existing_ids = {x.id for x in queue_tracks}
        existing_origins = {_origin_track_id(x) for x in queue_tracks}
        for t in aired_candidates:
            if t.id in existing_ids:
                continue
            oid = _origin_track_id(t)
            if oid in existing_origins:
                continue
            queue_tracks.append(t)
            existing_ids.add(t.id)
            existing_origins.add(oid)
        # Keep current track in exported queue. Reconcile logic depends on queue.json
        # containing the active track to avoid premature now-playing rotation.

    playable: list[PlaybackTrack] = []
    stale_deleted = 0
    fallback_promoted = 0
    for t in queue_tracks:
        if not t.file_path:
            if t.status in (TrackStatus.ready, TrackStatus.queued):
                t.status = TrackStatus.deleted
                db.add(t)
                stale_deleted += 1
            continue
        source = Path(t.file_path)
        if not source.exists():
            if t.status in (TrackStatus.ready, TrackStatus.queued):
                t.status = TrackStatus.deleted
                db.add(t)
                stale_deleted += 1
            continue
        if t.status == TrackStatus.aired:
            t.status = TrackStatus.queued
            db.add(t)
            fallback_promoted += 1
        playback_path = _ensure_liquidsoap_playable(source)
        playable.append(
            PlaybackTrack(
                track_id=t.id,
                title=t.title,
                file_path=str(playback_path),
                duration_sec=t.duration_sec,
            )
        )
    if not playable and queue_tracks:
        # Never export an empty queue if we have at least one track candidate.
        # This prevents stations from appearing stalled in the UI/player.
        first = queue_tracks[0]
        if first.file_path and Path(first.file_path).exists():
            fallback_path = _ensure_liquidsoap_playable(Path(first.file_path))
            playable.append(
                PlaybackTrack(
                    track_id=first.id,
                    title=first.title,
                    file_path=str(fallback_path),
                    duration_sec=first.duration_sec,
                )
            )
    if stale_deleted or fallback_promoted:
        db.commit()
    backend.sync_station_queue(station.slug, playable)
    return len(playable)


def _ensure_liquidsoap_playable(source: Path) -> Path:
    # Liquidsoap in our runtime reliably decodes WAV sources while MP3 queue exports
    # can degrade into silent HLS output. Keep playback paths on original assets.
    return source
