from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.services.stats import playback_stats


def test_playback_stats_exposed(monkeypatch, db_session):
    st = Station(slug='x', name='X', genre='Lo-Fi', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    db_session.add(StationPlaybackState(station_id=st.id, playback_backend='liquidsoap', current_title='A'))
    db_session.commit()

    class B:
        def get_health(self, station_slug):
            return type('H', (), {'alive': True, 'manifest_age_seconds': 5, 'queue_export_age_seconds': 3, 'drift_count': 0})()

        def get_now_playing(self, station_slug):
            return type('N', (), {'fallback_active': False, 'title': 'A'})()

    import app.services.stats as mod

    monkeypatch.setattr(mod, 'get_backend', lambda: B())
    out = playback_stats(db_session)
    assert len(out) == 1
    assert out[0]['backend_alive'] is True
    assert out[0]['replay_active'] is False
    assert out[0]['replay_reason'] == 'none'


def test_playback_stats_marks_replay_from_reused_title(monkeypatch, db_session):
    st = Station(slug='y', name='Y', genre='Rock', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    class B:
        def get_health(self, station_slug):
            return type('H', (), {'alive': True, 'manifest_age_seconds': 5, 'queue_export_age_seconds': 3, 'drift_count': 0})()

        def get_now_playing(self, station_slug):
            return type('N', (), {'fallback_active': False, 'title': 'Night Run (reused)'})()

    import app.services.stats as mod

    monkeypatch.setattr(mod, 'get_backend', lambda: B())
    out = playback_stats(db_session)
    assert len(out) == 1
    assert out[0]['replay_active'] is True
    assert out[0]['replay_reason'] == 'reused_title'
