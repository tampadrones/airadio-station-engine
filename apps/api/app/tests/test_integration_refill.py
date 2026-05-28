from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from app.models.station import Station
from app.models.enums import TrackStatus
from app.models.track import Track
from app.services.station_engine import StationEngine


class DummyResult:
    def __init__(self, ok: bool, audio_url: str | None = None, reason=None):
        self.ok = ok
        self.audio_url = audio_url
        self.failure_reason = reason
        self.error_message = "failed"
        self.seed = 1


@pytest.mark.asyncio
async def test_refill_failure_then_reuse(monkeypatch, db_session, tmp_path: Path):
    # Keep this test deterministic even when listener-idle gating rules evolve.
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (True, "forced_for_test"))

    st = Station(
        slug="test-st",
        name="Test",
        genre="Lo-Fi",
        personality="Dustline Dan",
        description="x",
        circadian_profile={},
        target_queue_depth=2,
        min_ready_tracks=1,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    old = Track(
        station_id=st.id,
        title="old",
        status=TrackStatus.aired,
        file_path=str(tmp_path / "old.wav"),
        duration_sec=200,
        audio_format="wav",
    )
    db_session.add(old)
    db_session.commit()

    data = np.zeros(44100 * 4, dtype=np.float32)
    sf.write(old.file_path, data, 44100)

    engine = StationEngine()

    class DummyClient:
        async def generate(self, req):
            return DummyResult(False, None, reason=type("R", (), {"value": "timeout"})())

    engine.client = DummyClient()

    result = await engine.refill_station_if_needed(db_session, st)
    assert result["failed"] >= 1

    ready = db_session.query(Track).filter(Track.station_id == st.id, Track.status == TrackStatus.ready).count()
    assert ready >= 1


@pytest.mark.asyncio
async def test_refill_respects_idle_gate_when_station_queue_below_floor(monkeypatch, db_session):
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (False, "idle_no_listeners"))

    st = Station(
        slug="idle-floor",
        name="Idle Floor",
        genre="Synthwave",
        personality="Neon",
        description="x",
        circadian_profile={},
        target_queue_depth=2,
        min_ready_tracks=1,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    engine = StationEngine()
    calls = {"n": 0}

    async def fake_generate(db, station):
        calls["n"] += 1
        return True

    monkeypatch.setattr(engine, "_generate_one_track", fake_generate)

    out = await engine.refill_station_if_needed(db_session, st)
    assert calls["n"] == 0
    assert out["skipped"] is True
    assert out["reason"] == "idle_no_listeners"


@pytest.mark.asyncio
async def test_idle_bootstrap_caps_refill_to_idle_floor(monkeypatch, db_session):
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (True, "bootstrap_min_ready"))

    st = Station(
        slug="idle-cap",
        name="Idle Cap",
        genre="Synthwave",
        personality="Neon",
        description="x",
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    existing = Track(station_id=st.id, title="existing", status=TrackStatus.queued, duration_sec=200)
    db_session.add(existing)
    db_session.commit()

    engine = StationEngine()
    engine.settings.station_idle_min_ready_tracks = 2
    calls = {"n": 0}

    async def fake_generate(db, station):
        calls["n"] += 1
        db.add(Track(station_id=station.id, title=f"generated-{calls['n']}", status=TrackStatus.ready, duration_sec=200))
        db.commit()
        return True

    monkeypatch.setattr(engine, "_generate_one_track", fake_generate)

    out = await engine.refill_station_if_needed(db_session, st)
    assert out["generated"] == 1
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_idle_bootstrap_skips_when_idle_buffer_is_already_healthy(monkeypatch, db_session):
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (True, "bootstrap_min_ready"))

    st = Station(
        slug="idle-healthy",
        name="Idle Healthy",
        genre="Synthwave",
        personality="Neon",
        description="x",
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    db_session.add_all(
        [
            Track(station_id=st.id, title="q1", status=TrackStatus.queued, duration_sec=200),
            Track(station_id=st.id, title="q2", status=TrackStatus.queued, duration_sec=200),
        ]
    )
    db_session.commit()

    engine = StationEngine()
    engine.settings.station_idle_min_ready_tracks = 2
    calls = {"n": 0}

    async def fake_generate(db, station):
        calls["n"] += 1
        return True

    monkeypatch.setattr(engine, "_generate_one_track", fake_generate)

    out = await engine.refill_station_if_needed(db_session, st)
    assert out["skipped"] is True
    assert out["reason"] == "idle_buffer_healthy"
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_recently_enabled_station_refills_to_target_without_listeners(monkeypatch, db_session):
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (False, "idle_no_listeners"))

    st = Station(
        slug="edm",
        name="EDM",
        genre="EDM",
        personality="Pulse",
        description="x",
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
        is_enabled=True,
        created_at=datetime.utcnow() - timedelta(minutes=5),
        updated_at=datetime.utcnow(),
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    db_session.add(Track(station_id=st.id, title="seed", status=TrackStatus.ready, duration_sec=200))
    db_session.commit()

    engine = StationEngine()
    engine.settings.station_activation_refill_minutes = 20
    calls = {"n": 0}

    async def fake_generate(db, station):
        calls["n"] += 1
        db.add(Track(station_id=station.id, title=f"generated-{calls['n']}", status=TrackStatus.ready, duration_sec=200))
        db.commit()
        return True

    monkeypatch.setattr(engine, "_generate_one_track", fake_generate)

    out = await engine.refill_station_if_needed(db_session, st, station_current_listeners=0, any_active_listeners=False)
    assert out["generated"] == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_recent_activation_refill_is_suppressed_when_other_stations_have_listeners(monkeypatch, db_session):
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (False, "idle_no_listeners"))

    st = Station(
        slug="edm-b",
        name="EDM B",
        genre="EDM",
        personality="Pulse",
        description="x",
        circadian_profile={},
        target_queue_depth=5,
        min_ready_tracks=3,
        hot_quota_gb=5,
        warm_quota_gb=20,
        is_enabled=True,
        created_at=datetime.utcnow() - timedelta(minutes=5),
        updated_at=datetime.utcnow(),
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    db_session.add(Track(station_id=st.id, title="seed", status=TrackStatus.ready, duration_sec=200))
    db_session.commit()

    engine = StationEngine()
    engine.settings.station_activation_refill_minutes = 20
    calls = {"n": 0}

    async def fake_generate(db, station):
        calls["n"] += 1
        return True

    monkeypatch.setattr(engine, "_generate_one_track", fake_generate)

    out = await engine.refill_station_if_needed(db_session, st, station_current_listeners=0, any_active_listeners=True)
    assert out["skipped"] is True
    assert out["reason"] == "activation_suppressed_active_elsewhere"
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_refill_generator_wallclock_timeout(monkeypatch, db_session):
    monkeypatch.setattr("app.services.station_engine.should_generate_for_station", lambda *args, **kwargs: (True, "forced_for_test"))

    st = Station(
        slug="timeout-st",
        name="Timeout",
        genre="Synthwave",
        personality="Neon",
        description="x",
        circadian_profile={},
        target_queue_depth=2,
        min_ready_tracks=1,
        hot_quota_gb=5,
        warm_quota_gb=20,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    engine = StationEngine()

    class HangingClient:
        async def generate(self, req):
            await asyncio.sleep(1.0)
            return DummyResult(True, "http://example.invalid/audio.wav")

    engine.client = HangingClient()
    monkeypatch.setattr(engine, "_generation_call_timeout_seconds", lambda: 0.01)

    out = await engine.refill_station_if_needed(db_session, st)
    assert out["failed"] >= 1
    generating = db_session.query(Track).filter(Track.station_id == st.id, Track.status == TrackStatus.generating).count()
    assert generating == 0
