from __future__ import annotations

import pytest

from app.api import routes as routes_mod
from app.models.enums import StorageClass, TrackStatus
from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.models.track import Track
from playback.schemas import NowPlaying


def test_skip_current_exports_queue_then_sends_source_skip(monkeypatch, db_session, tmp_path):
    calls: list[tuple[str, str]] = []

    class DummyBackend:
        def skip_current(self, station_slug: str) -> None:
            calls.append(("skip", station_slug))

    station = Station(
        slug="skip-test",
        name="Skip Test",
        genre="Rock",
        personality="DJ",
        description="d",
        circadian_profile={},
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    audio = tmp_path / "current.wav"
    audio.write_bytes(b"x")
    track = Track(
        station_id=station.id,
        title="Current Track",
        status=TrackStatus.queued,
        storage_class=StorageClass.hot,
        duration_sec=210,
        file_path=str(audio),
    )
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)

    state = StationPlaybackState(
        station_id=station.id,
        playback_backend="liquidsoap",
        current_track_id=track.id,
        current_title=track.title,
    )
    db_session.add(state)
    db_session.commit()

    def sync_queue(db, st):
        calls.append(("sync", st.slug))
        return 1

    monkeypatch.setattr(routes_mod, "sync_station_queue_export", sync_queue)
    monkeypatch.setattr(routes_mod, "get_playback_backend", lambda: DummyBackend())
    monkeypatch.setattr(
        routes_mod,
        "force_liquidsoap_reload",
        lambda db: pytest.fail("normal skip path should not force Liquidsoap reload"),
    )

    result = routes_mod.station_skip_current("skip-test", db_session)

    assert result["ok"] is True
    assert result["mode"] == "source_skip"
    assert calls == [("sync", "skip-test"), ("skip", "skip-test")]

    db_session.refresh(track)
    db_session.refresh(state)
    assert track.status == TrackStatus.deleted
    assert track.deleted_at is not None
    assert state.current_track_id is None
    assert state.current_title is None


def test_skip_current_falls_back_to_reload_if_source_skip_fails(monkeypatch, db_session, tmp_path):
    calls: list[tuple[str, str]] = []

    class FailingBackend:
        def skip_current(self, station_slug: str) -> None:
            calls.append(("skip", station_slug))
            raise RuntimeError("control socket unavailable")

    station = Station(
        slug="skip-fallback",
        name="Skip Fallback",
        genre="Rock",
        personality="DJ",
        description="d",
        circadian_profile={},
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    audio = tmp_path / "current.wav"
    audio.write_bytes(b"x")
    track = Track(
        station_id=station.id,
        title="Current Track",
        status=TrackStatus.queued,
        storage_class=StorageClass.hot,
        duration_sec=210,
        file_path=str(audio),
    )
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)

    db_session.add(
        StationPlaybackState(
            station_id=station.id,
            playback_backend="liquidsoap",
            current_track_id=track.id,
            current_title=track.title,
        )
    )
    db_session.commit()

    monkeypatch.setattr(routes_mod, "sync_station_queue_export", lambda db, st: calls.append(("sync", st.slug)) or 1)
    monkeypatch.setattr(routes_mod, "get_playback_backend", lambda: FailingBackend())
    monkeypatch.setattr(routes_mod, "force_liquidsoap_reload", lambda db: calls.append(("reload", "skip-fallback")))

    result = routes_mod.station_skip_current("skip-fallback", db_session)

    assert result["ok"] is True
    assert result["mode"] == "queue_reload_fallback"
    assert calls == [("sync", "skip-fallback"), ("skip", "skip-fallback"), ("reload", "skip-fallback")]


def test_skip_current_uses_now_playing_when_db_state_is_empty(monkeypatch, db_session, tmp_path):
    calls: list[tuple[str, str]] = []

    class DummyBackend:
        def get_now_playing(self, station_slug: str) -> NowPlaying:
            return NowPlaying(
                station_slug=station_slug,
                track_id=track.id,
                title=track.title,
                started_at=None,
                position_sec=None,
                fallback_active=False,
            )

        def skip_current(self, station_slug: str) -> None:
            calls.append(("skip", station_slug))

    station = Station(
        slug="skip-stale-state",
        name="Skip Stale State",
        genre="Rock",
        personality="DJ",
        description="d",
        circadian_profile={},
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    audio = tmp_path / "current.wav"
    audio.write_bytes(b"x")
    track = Track(
        station_id=station.id,
        title="Current Track",
        status=TrackStatus.queued,
        storage_class=StorageClass.hot,
        duration_sec=210,
        file_path=str(audio),
    )
    db_session.add(track)
    db_session.commit()
    db_session.refresh(track)

    db_session.add(
        StationPlaybackState(
            station_id=station.id,
            playback_backend="liquidsoap",
            current_track_id=None,
            current_title=None,
        )
    )
    db_session.commit()

    monkeypatch.setattr(routes_mod, "sync_station_queue_export", lambda db, st: calls.append(("sync", st.slug)) or 1)
    monkeypatch.setattr(routes_mod, "get_playback_backend", lambda: DummyBackend())
    monkeypatch.setattr(
        routes_mod,
        "force_liquidsoap_reload",
        lambda db: pytest.fail("normal skip path should not force Liquidsoap reload"),
    )

    result = routes_mod.station_skip_current("skip-stale-state", db_session)

    assert result["ok"] is True
    assert result["track_id"] == track.id
    assert calls == [("sync", "skip-stale-state"), ("skip", "skip-stale-state")]


def test_skip_current_seeds_next_track_from_exported_queue(monkeypatch, db_session, tmp_path):
    class DummyBackend:
        def skip_current(self, station_slug: str) -> None:
            return None

    station = Station(
        slug="skip-next-track",
        name="Skip Next Track",
        genre="Rock",
        personality="DJ",
        description="d",
        circadian_profile={},
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    current_audio = tmp_path / "current.wav"
    current_audio.write_bytes(b"x")
    current = Track(
        station_id=station.id,
        title="Current Track",
        status=TrackStatus.queued,
        storage_class=StorageClass.hot,
        duration_sec=210,
        file_path=str(current_audio),
    )
    db_session.add(current)
    db_session.commit()
    db_session.refresh(current)

    state = StationPlaybackState(
        station_id=station.id,
        playback_backend="liquidsoap",
        current_track_id=current.id,
        current_title=current.title,
    )
    db_session.add(state)
    db_session.commit()

    monkeypatch.setattr(routes_mod, "sync_station_queue_export", lambda db, st: 1)
    monkeypatch.setattr(routes_mod, "_first_exported_queue_track", lambda backend, slug: (999, "Next Track"))
    monkeypatch.setattr(routes_mod, "get_playback_backend", lambda: DummyBackend())
    monkeypatch.setattr(
        routes_mod,
        "force_liquidsoap_reload",
        lambda db: pytest.fail("normal skip path should not force Liquidsoap reload"),
    )

    result = routes_mod.station_skip_current("skip-next-track", db_session)

    assert result["ok"] is True
    assert result["next_track"] == {"id": 999, "title": "Next Track", "duration_sec": None}
    db_session.refresh(state)
    assert state.current_track_id == 999
    assert state.current_title == "Next Track"
    assert state.position_sec == 0
    assert state.started_at is not None
