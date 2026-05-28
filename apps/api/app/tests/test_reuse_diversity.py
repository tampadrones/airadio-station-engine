from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.models.enums import StorageClass, TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.services.station_engine import StationEngine


def test_pick_reuse_candidate_avoids_recent_origin(db_session, tmp_path: Path):
    st = Station(
        slug="reuse-diversity",
        name="Reuse Diversity",
        genre="Synthwave",
        personality="Neon",
        description="x",
        circadian_profile={},
        station_profile={},
        target_queue_depth=4,
        min_ready_tracks=2,
    )
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    # Two reusable source tracks.
    src1_path = tmp_path / "track_1.wav"
    src2_path = tmp_path / "track_2.wav"
    src1_path.write_bytes(b"a")
    src2_path.write_bytes(b"b")

    src1 = Track(
        station_id=st.id,
        title="Source One",
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        file_path=str(src1_path),
        duration_sec=180,
        created_at=datetime.utcnow() - timedelta(hours=20),
        aired_at=datetime.utcnow() - timedelta(hours=20),
    )
    src2 = Track(
        station_id=st.id,
        title="Source Two",
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        file_path=str(src2_path),
        duration_sec=182,
        created_at=datetime.utcnow() - timedelta(hours=18),
        aired_at=datetime.utcnow() - timedelta(hours=18),
    )
    db_session.add_all([src1, src2])
    db_session.commit()
    db_session.refresh(src1)

    # Active queue already has a reused clone of src1, so src1 origin should be blocked.
    in_queue = tmp_path / f"reused_{src1.id}_active.wav"
    in_queue.write_bytes(b"qa")
    q = Track(
        station_id=st.id,
        title="Source One (reused)",
        status=TrackStatus.queued,
        storage_class=StorageClass.hot,
        file_path=str(in_queue),
        duration_sec=180,
        created_at=datetime.utcnow() - timedelta(minutes=10),
        aired_at=datetime.utcnow() - timedelta(minutes=10),
    )
    db_session.add(q)
    db_session.commit()

    engine = StationEngine()
    picked = engine._pick_reuse_candidate(db_session, st)
    assert picked is not None
    assert picked.id == src2.id
