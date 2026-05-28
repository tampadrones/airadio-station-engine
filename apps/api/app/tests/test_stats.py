from datetime import datetime, timedelta

import httpx

from app.models.ops_event import OpsEvent
from app.models.enums import TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.models.track_generation import TrackGeneration
from app.services import stats as stats_service
from app.services.stats import _today_window_start_utc, overview_stats, reset_failed_generations_today, station_health


def test_overview_stats(db_session):
    db_session.add(
        Station(
            slug='x',
            name='X',
            genre='Lo-Fi',
            personality='P',
            description='d',
            circadian_profile={},
            target_queue_depth=5,
            min_ready_tracks=3,
            hot_quota_gb=5,
            warm_quota_gb=20,
        )
    )
    db_session.commit()
    out = overview_stats(db_session)
    assert 'active_stations' in out


def test_tracks_generated_today_uses_calendar_day_window(db_session):
    st = Station(
        slug='day-window',
        name='Day Window',
        genre='Lo-Fi',
        personality='P',
        description='d',
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    now = datetime.utcnow()
    start_today_utc = _today_window_start_utc(now)

    t1 = Track(station_id=st.id, title='t1')
    t2 = Track(station_id=st.id, title='t2')
    db_session.add_all([t1, t2])
    db_session.commit()
    db_session.refresh(t1)
    db_session.refresh(t2)

    g_today = TrackGeneration(
        track_id=t1.id,
        prompt_text='p',
        generator_host='h',
        genre='Lo-Fi',
        personality='P',
        mood_state='baseline',
        daypart='evening',
        recent_context={},
        created_at=start_today_utc + timedelta(hours=1),
    )
    g_yesterday = TrackGeneration(
        track_id=t2.id,
        prompt_text='p',
        generator_host='h',
        genre='Lo-Fi',
        personality='P',
        mood_state='baseline',
        daypart='evening',
        recent_context={},
        created_at=start_today_utc - timedelta(minutes=1),
    )
    db_session.add_all([g_today, g_yesterday])
    db_session.commit()

    out = overview_stats(db_session)
    assert out["tracks_generated_today"] == 1


def test_reset_failed_generations_today_only_deletes_today(db_session):
    now = datetime.utcnow()
    start_today_utc = _today_window_start_utc(now)
    older = start_today_utc - timedelta(minutes=1)
    newer = start_today_utc + timedelta(minutes=1)

    db_session.add_all(
        [
            OpsEvent(service="worker", host="h", event_type="generation_failed", message="older", timestamp=older, details={}),
            OpsEvent(service="worker", host="h", event_type="generation_failed", message="newer", timestamp=newer, details={}),
            OpsEvent(service="worker", host="h", event_type="generation_started", message="other", timestamp=newer, details={}),
        ]
    )
    db_session.commit()

    result = reset_failed_generations_today(db_session)
    assert result["deleted"] == 1

    remaining_failed = db_session.query(OpsEvent).filter(OpsEvent.event_type == "generation_failed").count()
    assert remaining_failed == 1


def test_station_health_not_degraded_when_queue_is_healthy(monkeypatch, db_session):
    class DummyHealth:
        manifest_age_seconds = 5
        queue_export_age_seconds = 5
        drift_count = 0

    class DummyBackend:
        def get_health(self, station_slug):
            return DummyHealth()

    monkeypatch.setattr(stats_service, "get_backend", lambda: DummyBackend())

    st = Station(
        slug="queue-healthy",
        name="Queue Healthy",
        genre="Trap",
        personality="Host",
        description="d",
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    tracks = [
        Track(station_id=st.id, title=f"q{i}", status=TrackStatus.queued, duration_sec=200)
        for i in range(5)
    ]
    db_session.add_all(tracks)
    db_session.commit()

    rows = station_health(db_session)
    row = next(x for x in rows if x["station_id"] == st.id)
    assert row["ready_tracks"] == 0
    assert row["queue_depth"] == 5
    assert row["current_status"] == "healthy"


def test_generation_stats_includes_generator_queue_size(monkeypatch, db_session):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"queue_size": 4}))

    class FakeClient(httpx.Client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(stats_service.httpx, "Client", FakeClient)

    out = stats_service.generation_stats(db_session)
    assert out["generator_queue_size"] == 4
    assert out["generator_queue_health"] == "healthy"


def test_generation_stats_health_uses_live_generator_reachability(monkeypatch, db_session):
    now = datetime.utcnow()
    db_session.add(
        OpsEvent(
            service="worker",
            host="h",
            event_type="generation_failed",
            message="old endpoint refused",
            timestamp=now - timedelta(minutes=2),
            details={},
            error_code="connection_error",
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        stats_service,
        "check_generator_health",
        lambda _settings: {
            "reachable": True,
            "generator_base_url": "http://example:7860",
            "generator_status_url": "http://example:7860/gradio_api/queue/status",
        },
    )
    monkeypatch.setattr(
        stats_service,
        "_generator_queue_status",
        lambda: {"generator_queue_size": 0, "generator_queue_health": "healthy", "generator_queue_status_url": "x"},
    )

    out = stats_service.generation_stats(db_session)
    assert out["generator_host_health"] == "healthy"
    assert out["failed_generations"] == 1
    assert out["failed_generations_total"] >= 1
    assert out["failed_generations_window"] == "24h"
    assert out["current_generator_base_url"] == "http://example:7860"
