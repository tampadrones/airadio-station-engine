from __future__ import annotations

from abc import ABC, abstractmethod

from .schemas import NowPlaying, PlaybackHealth, PlaybackTrack


class PlaybackBackend(ABC):
    @abstractmethod
    def sync_station_queue(self, station_slug: str, tracks: list[PlaybackTrack]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_now_playing(self, station_slug: str) -> NowPlaying:
        raise NotImplementedError

    @abstractmethod
    def get_stream_url(self, station_slug: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_health(self, station_slug: str) -> PlaybackHealth:
        raise NotImplementedError

    @abstractmethod
    def skip_current(self, station_slug: str) -> None:
        raise NotImplementedError
