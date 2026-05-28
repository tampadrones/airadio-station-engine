from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from observability.metrics import (
    playback_backend_alive,
    playback_backend_db_drift_total,
    playback_fallback_active,
    playback_manifest_age_seconds,
    playback_queue_export_age_seconds,
)
from app.models.enums import Severity, TrackStatus
from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.models.track import Track
from app.models.track_play_event import TrackPlayEvent
from app.services.listeners import get_listener_counts
from app.services.ops_events import emit_event
from app.services.playback_backend import get_playback_backend


def get_backend():
    return get_playback_backend()


def reconcile_station_playback(db: Session, station: Station) -> StationPlaybackState:
    backend = get_backend()
    np = backend.get_now_playing(station.slug)
    health = backend.get_health(station.slug)

    playback_backend_alive.labels(station.slug).set(1 if health.alive else 0)
    playback_manifest_age_seconds.labels(station.slug).set(float(health.manifest_age_seconds or -1))
    playback_queue_export_age_seconds.labels(station.slug).set(float(health.queue_export_age_seconds or -1))
    playback_fallback_active.labels(station.slug).set(1 if np.fallback_active else 0)

    state = db.query(StationPlaybackState).filter(StationPlaybackState.station_id == station.id).first()
    if not state:
        state = StationPlaybackState(station_id=station.id, playback_backend="liquidsoap")
        db.add(state)
        db.commit()
        db.refresh(state)

    prev_track_id = state.current_track_id
    queue_tracks = _load_queue_tracks(station.slug)

    current_track_id = state.current_track_id
    current_title = state.current_title
    started_at = state.started_at
    position_sec = state.position_sec
    advanced_track_ids: list[int] = []
    current_track_id, current_title, started_at, position_sec, advanced_track_ids = _estimate_now_playing(
        state=state,
        queue_tracks=queue_tracks,
        now=datetime.utcnow(),
    )
    if current_track_id is None and np.track_id is not None:
        current_track_id = np.track_id
        current_title = np.title
        started_at = np.started_at
        position_sec = np.position_sec

    for aired_id in advanced_track_ids:
        _mark_track_aired(db, station.id, aired_id)
    if advanced_track_ids:
        emit_event(
            db,
            service="worker",
            event_type="station_queue_refill_completed",
            message="Playback advanced via queue timeline",
            station_id=station.id,
            details={"advanced_track_ids": advanced_track_ids},
        )

    if prev_track_id and prev_track_id != current_track_id and prev_track_id not in advanced_track_ids:
        _mark_track_aired(db, station.id, prev_track_id)

    if current_track_id:
        current = db.query(Track).filter(Track.id == current_track_id, Track.station_id == station.id).first()
        if current:
            current.status = TrackStatus.queued
        else:
            missing_track_id = current_track_id
            playback_backend_db_drift_total.labels(station.slug).inc()
            emit_event(
                db,
                service="worker",
                event_type="stream_error",
                message="Backend reported track missing from DB; clearing playback state",
                severity=Severity.warning,
                station_id=station.id,
                error_code="backend_db_drift",
                details={"backend_track_id": missing_track_id},
            )
            current_track_id = None
            current_title = None
            started_at = None
            position_sec = 0

    if np.fallback_active and not state.fallback_active:
        emit_event(
            db,
            service="worker",
            event_type="track_reused",
            message="Playback fallback activated",
            severity=Severity.warning,
            station_id=station.id,
        )

    state.current_track_id = current_track_id
    state.current_title = current_title
    state.started_at = started_at
    state.position_sec = position_sec
    state.fallback_active = np.fallback_active
    state.manifest_path = health.manifest_path
    state.manifest_age_seconds = health.manifest_age_seconds
    state.updated_at = datetime.utcnow()
    db.add(state)
    db.commit()
    db.refresh(state)
    _write_playback_sidecars(db, station, state)
    return state


def _mark_track_aired(db: Session, station_id: int, track_id: int) -> None:
    prev = db.query(Track).filter(Track.id == track_id, Track.station_id == station_id).first()
    if not prev or prev.status not in [TrackStatus.queued, TrackStatus.ready]:
        return
    prev.status = TrackStatus.aired
    prev.aired_at = datetime.utcnow()
    db.add(
        TrackPlayEvent(
            track_id=prev.id,
            station_id=station_id,
            played_at=prev.aired_at,
            listeners_at_start=0,
            listeners_peak=0,
            completed=True,
            skip_rate=0.0,
        )
    )


def _load_queue_tracks(station_slug: str) -> list[dict[str, Any]]:
    station_dir = Path("/var/lib/ai-radio/playback/stations") / station_slug
    queue_path = station_dir / "queue.json"
    if not queue_path.exists():
        return []
    try:
        payload = json.loads(queue_path.read_text())
    except json.JSONDecodeError:
        return []
    items: list[dict[str, Any]] = []
    for item in payload.get("tracks", []):
        if not isinstance(item, dict):
            continue
        track_id = item.get("track_id")
        title = item.get("title")
        if not isinstance(track_id, int):
            continue
        items.append(
            {
                "track_id": track_id,
                "title": title if isinstance(title, str) else None,
                "duration_sec": int(item.get("duration_sec") or 200),
            }
        )
    return items


def _estimate_now_playing(
    state: StationPlaybackState,
    queue_tracks: list[dict[str, Any]],
    now: datetime,
) -> tuple[int | None, str | None, datetime | None, int | None, list[int]]:
    if not queue_tracks:
        return state.current_track_id, state.current_title, state.started_at, state.position_sec, []

    if state.current_track_id is None:
        first = queue_tracks[0]
        return int(first["track_id"]), first.get("title"), now, 0, []

    queue_ids = [int(t["track_id"]) for t in queue_tracks]
    if state.current_track_id not in queue_ids:
        # Queue exports can refresh mid-track; do not rotate now-playing early
        # when current track is absent from the latest queue snapshot.
        return state.current_track_id, state.current_title, state.started_at, state.position_sec, []

    index = queue_ids.index(int(state.current_track_id))
    started_at = state.started_at or now
    elapsed = max(0, int((now - started_at).total_seconds()))
    advanced: list[int] = []
    durations = [max(30, int(item.get("duration_sec") or 200)) for item in queue_tracks]
    total_duration = sum(durations)
    if total_duration > 0 and elapsed >= total_duration:
        # Liquidsoap continues progressing even when app heartbeats are absent.
        # Collapse long elapsed windows to one loop plus remainder to keep state bounded.
        advanced.extend(queue_ids)
        elapsed = elapsed % total_duration

    while queue_tracks:
        current = queue_tracks[index]
        duration = max(30, int(current.get("duration_sec") or 200))
        if elapsed < duration:
            break
        elapsed -= duration
        advanced.append(int(current["track_id"]))
        index = (index + 1) % len(queue_tracks)

    resolved = queue_tracks[index]
    resolved_started_at = now - timedelta(seconds=elapsed)
    return int(resolved["track_id"]), resolved.get("title"), resolved_started_at, elapsed, advanced


def _write_playback_sidecars(db: Session, station: Station, state: StationPlaybackState) -> None:
    station_dir = Path("/var/lib/ai-radio/playback/stations") / station.slug
    station_dir.mkdir(parents=True, exist_ok=True)
    now_path = station_dir / "now_playing.json"
    state_path = station_dir / "state.json"
    queue_path = station_dir / "queue.json"

    queue_size = None
    queue_generated_at = None
    if queue_path.exists():
        try:
            queue_payload = json.loads(queue_path.read_text())
            queue_size = len(queue_payload.get("tracks", []))
            queue_generated_at = queue_payload.get("generated_at")
        except json.JSONDecodeError:
            queue_size = None

    track: Track | None = None
    if state.current_track_id:
        track = db.query(Track).filter(Track.id == state.current_track_id).first()

    now_payload: dict[str, Any] = {
        "station_slug": station.slug,
        "station_name": station.name,
        "track_id": state.current_track_id,
        "title": state.current_title,
        "started_at": state.started_at.isoformat() if state.started_at else None,
        "position_sec": state.position_sec,
        "fallback_active": state.fallback_active,
        "generation_in_progress": bool(
            db.query(Track.id)
            .filter(Track.station_id == station.id, Track.status == TrackStatus.generating)
            .first()
        ),
        "updated_at": datetime.utcnow().isoformat(),
    }
    if track:
        now_payload.update(
            {
                "duration_sec": track.duration_sec,
                "audio_format": track.audio_format,
                "file_path": track.file_path,
            }
        )
    now_path.write_text(json.dumps(now_payload, indent=2))

    state_payload: dict[str, Any] = {
        "station_slug": station.slug,
        "station_name": station.name,
        "playback_backend": state.playback_backend,
        "manifest_path": state.manifest_path,
        "manifest_age_seconds": state.manifest_age_seconds,
        "fallback_active": state.fallback_active,
        "current_track_id": state.current_track_id,
        "current_title": state.current_title,
        "active_listeners": int(get_listener_counts([station.slug])[1].get(station.slug, 0)),
        "queue_size": queue_size,
        "queue_generated_at": queue_generated_at,
        "updated_at": datetime.utcnow().isoformat(),
    }
    state_path.write_text(json.dumps(state_payload, indent=2))
