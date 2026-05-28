import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.models.track import Track
from app.models.enums import StorageClass, TrackStatus
from app.services.playback_reconcile import reconcile_station_playback


class DummyNow:
    def __init__(self, track_id=1, title="t1", fallback_active=False):
        self.station_slug = "test-st"
        self.track_id = track_id
        self.title = title
        self.started_at = datetime.now(timezone.utc)
        self.position_sec = 5
        self.fallback_active = fallback_active


class DummyHealth:
    def __init__(self):
        self.station_slug = "test-st"
        self.backend = "liquidsoap"
        self.alive = True
        self.manifest_path = "/tmp/index.m3u8"
        self.manifest_age_seconds = 10
        self.queue_export_age_seconds = 5
        self.fallback_active = False
        self.drift_count = 0


class DummyBackend:
    def __init__(self, track_id=1, title="t1", fallback=False):
        self._now = DummyNow(track_id=track_id, title=title, fallback_active=fallback)
        self._health = DummyHealth()

    def get_now_playing(self, station_slug):
        return self._now

    def get_health(self, station_slug):
        return self._health


def test_reconcile_updates_state(monkeypatch, db_session):
    st = Station(slug="test-st", name="Test", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    tr = Track(station_id=st.id, title="t1", status=TrackStatus.ready, storage_class=StorageClass.hot)
    db_session.add(tr)
    db_session.commit()

    import app.services.playback_reconcile as mod

    monkeypatch.setattr(mod, "get_backend", lambda: DummyBackend(track_id=tr.id, title="t1"))
    monkeypatch.setattr(mod, "get_listener_counts", lambda slugs: (1, {"test-st": 1}))
    state = reconcile_station_playback(db_session, st)
    assert state.current_track_id == tr.id
    assert state.current_title == "t1"


def test_reconcile_fallback_flag(monkeypatch, db_session):
    st = Station(slug="test-st", name="Test", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    import app.services.playback_reconcile as mod

    monkeypatch.setattr(mod, "get_backend", lambda: DummyBackend(track_id=None, title="fallback", fallback=True))
    monkeypatch.setattr(mod, "get_listener_counts", lambda slugs: (0, {"test-st": 0}))
    state = reconcile_station_playback(db_session, st)
    assert state.fallback_active is True

    got = db_session.query(StationPlaybackState).filter(StationPlaybackState.station_id == st.id).first()
    assert got is not None


def test_reconcile_does_not_advance_when_idle(monkeypatch, db_session):
    st = Station(slug="test-st-idle", name="Test", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    tr = Track(station_id=st.id, title="t1", status=TrackStatus.ready, storage_class=StorageClass.hot)
    db_session.add(tr)
    db_session.commit()
    db_session.refresh(tr)

    state = StationPlaybackState(
        station_id=st.id,
        playback_backend="liquidsoap",
        current_track_id=tr.id,
        current_title=tr.title,
        position_sec=42,
    )
    db_session.add(state)
    db_session.commit()

    import app.services.playback_reconcile as mod

    monkeypatch.setattr(mod, "get_backend", lambda: DummyBackend(track_id=tr.id, title=tr.title))
    monkeypatch.setattr(mod, "get_listener_counts", lambda slugs: (0, {"test-st-idle": 0}))
    updated = reconcile_station_playback(db_session, st)
    assert updated.current_track_id == tr.id
    assert updated.position_sec == 42


def test_reconcile_advances_queue_without_listener_heartbeats(monkeypatch, db_session):
    st = Station(slug="test-st", name="Test", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    tr1 = Track(station_id=st.id, title="t1", status=TrackStatus.queued, storage_class=StorageClass.hot, duration_sec=200)
    tr2 = Track(station_id=st.id, title="t2", status=TrackStatus.ready, storage_class=StorageClass.hot, duration_sec=200)
    db_session.add_all([tr1, tr2])
    db_session.commit()
    db_session.refresh(tr1)
    db_session.refresh(tr2)

    station_dir = Path("/var/lib/ai-radio/playback/stations/test-st")
    station_dir.mkdir(parents=True, exist_ok=True)
    (station_dir / "queue.json").write_text(
        json.dumps(
            {
                "station_slug": "test-st",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tracks": [
                    {"track_id": tr1.id, "title": tr1.title, "duration_sec": 200},
                    {"track_id": tr2.id, "title": tr2.title, "duration_sec": 200},
                ],
            }
        )
    )

    state = StationPlaybackState(
        station_id=st.id,
        playback_backend="liquidsoap",
        current_track_id=tr1.id,
        current_title=tr1.title,
        started_at=datetime.utcnow() - timedelta(seconds=250),
        position_sec=0,
    )
    db_session.add(state)
    db_session.commit()

    import app.services.playback_reconcile as mod

    monkeypatch.setattr(mod, "get_backend", lambda: DummyBackend(track_id=tr1.id, title=tr1.title))
    monkeypatch.setattr(mod, "get_listener_counts", lambda slugs: (0, {"test-st": 0}))
    updated = reconcile_station_playback(db_session, st)

    refreshed_tr1 = db_session.query(Track).filter(Track.id == tr1.id).first()
    assert refreshed_tr1 is not None
    assert refreshed_tr1.status == TrackStatus.aired
    assert updated.current_track_id == tr2.id
    assert int(updated.position_sec or 0) < 200


def test_reconcile_keeps_current_when_missing_from_queue_snapshot(db_session):
    from app.services.playback_reconcile import _estimate_now_playing

    st = Station(slug="test-st-missing", name="Test", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    state = StationPlaybackState(
        station_id=st.id,
        playback_backend="liquidsoap",
        current_track_id=999,
        current_title="Still playing",
        started_at=datetime.utcnow() - timedelta(seconds=30),
        position_sec=30,
    )

    track_id, title, started_at, position_sec, advanced = _estimate_now_playing(
        state=state,
        queue_tracks=[
            {"track_id": 111, "title": "up next", "duration_sec": 200},
            {"track_id": 112, "title": "after that", "duration_sec": 200},
        ],
        now=datetime.utcnow(),
    )

    assert track_id == 999
    assert title == "Still playing"
    assert started_at == state.started_at
    assert position_sec == 30
    assert advanced == []
