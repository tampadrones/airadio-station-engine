from datetime import datetime, timedelta

from app.models.enums import StorageClass, TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.models.station_playback_state import StationPlaybackState
from app.services.playback_sync import _dedupe_by_origin, _origin_track_id, sync_station_queue_export


def test_origin_track_id_from_reuse_filename():
    t = Track(id=77, file_path='/var/lib/ai-radio/hot/stations/x/tracks/reused_1126_123.wav')
    assert _origin_track_id(t) == 1126


def test_dedupe_by_origin_keeps_first_seen():
    a = Track(id=1, file_path='/tmp/reused_1126_a.wav')
    b = Track(id=2, file_path='/tmp/reused_1126_b.wav')
    c = Track(id=3, file_path='/tmp/track_3.wav')
    out = _dedupe_by_origin([a, b, c])
    assert [t.id for t in out] == [1, 3]


def test_sync_export_keeps_current_track_in_low_queue(monkeypatch, db_session, tmp_path):
    class DummyBackend:
        def __init__(self):
            self.last: list = []

        def sync_station_queue(self, station_slug, tracks):
            self.last = list(tracks)

    station = Station(slug="sync-keep-current", name="Sync Keep Current", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    current_path = tmp_path / "current.wav"
    current_path.write_bytes(b"x")
    aired_path = tmp_path / "aired.wav"
    aired_path.write_bytes(b"y")

    current = Track(
        station_id=station.id,
        title="current",
        status=TrackStatus.queued,
        storage_class=StorageClass.hot,
        duration_sec=200,
        file_path=str(current_path),
        created_at=datetime.utcnow() - timedelta(minutes=5),
    )
    aired = Track(
        station_id=station.id,
        title="aired",
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        duration_sec=200,
        file_path=str(aired_path),
        aired_at=datetime.utcnow() - timedelta(minutes=20),
        created_at=datetime.utcnow() - timedelta(minutes=30),
    )
    db_session.add_all([current, aired])
    db_session.commit()
    db_session.refresh(current)

    db_session.add(
        StationPlaybackState(
            station_id=station.id,
            playback_backend="liquidsoap",
            current_track_id=current.id,
            current_title=current.title,
        )
    )
    db_session.commit()

    backend = DummyBackend()
    import app.services.playback_sync as mod

    monkeypatch.setattr(mod, "get_playback_backend", lambda: backend)
    sync_station_queue_export(db_session, station)

    exported_ids = [int(t.track_id) for t in backend.last]
    assert current.id in exported_ids


def test_sync_export_injects_current_when_not_in_first_window(monkeypatch, db_session, tmp_path):
    class DummyBackend:
        def __init__(self):
            self.last: list = []

        def sync_station_queue(self, station_slug, tracks):
            self.last = list(tracks)

    station = Station(slug="sync-window", name="Sync Window", genre="Lo-Fi", personality="DJ", description="d", circadian_profile={})
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    base = datetime.utcnow() - timedelta(hours=1)
    queued_ids: list[int] = []
    for i in range(13):
        p = tmp_path / f"t{i}.wav"
        p.write_bytes(b"x")
        tr = Track(
            station_id=station.id,
            title=f"track-{i}",
            status=TrackStatus.queued,
            storage_class=StorageClass.hot,
            duration_sec=200,
            file_path=str(p),
            created_at=base + timedelta(seconds=i),
        )
        db_session.add(tr)
        db_session.flush()
        queued_ids.append(int(tr.id))
    db_session.commit()

    newest_id = queued_ids[-1]
    db_session.add(
        StationPlaybackState(
            station_id=station.id,
            playback_backend="liquidsoap",
            current_track_id=newest_id,
            current_title="current-newest",
        )
    )
    db_session.commit()

    backend = DummyBackend()
    import app.services.playback_sync as mod

    monkeypatch.setattr(mod, "get_playback_backend", lambda: backend)
    sync_station_queue_export(db_session, station)

    exported_ids = [int(t.track_id) for t in backend.last]
    assert newest_id in exported_ids
