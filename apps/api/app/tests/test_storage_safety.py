from datetime import datetime, timedelta
from pathlib import Path

from app.models.enums import StorageClass, TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.services.storage import cleanup_storage


def test_cleanup_keeps_shared_file_with_ready_ref(tmp_path: Path, db_session):
    st = Station(slug='safe', name='Safe', genre='Lo-Fi', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    f = tmp_path / 'shared.wav'
    f.write_bytes(b'x')

    aired = Track(
        station_id=st.id,
        title='aired',
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        file_path=str(f),
        created_at=datetime.utcnow() - timedelta(hours=72),
    )
    ready = Track(
        station_id=st.id,
        title='ready',
        status=TrackStatus.ready,
        storage_class=StorageClass.hot,
        file_path=str(f),
        created_at=datetime.utcnow(),
    )
    db_session.add_all([aired, ready])
    db_session.commit()

    cleanup_storage(db_session)
    assert f.exists()
