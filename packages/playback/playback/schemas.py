from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class PlaybackTrack:
    track_id: int
    title: str
    file_path: str
    duration_sec: int | None


@dataclass(slots=True)
class NowPlaying:
    station_slug: str
    track_id: int | None
    title: str | None
    started_at: datetime | None
    position_sec: int | None
    fallback_active: bool


@dataclass(slots=True)
class PlaybackHealth:
    station_slug: str
    backend: str
    alive: bool
    manifest_path: str | None
    manifest_age_seconds: int | None
    queue_export_age_seconds: int | None
    fallback_active: bool
    drift_count: int
