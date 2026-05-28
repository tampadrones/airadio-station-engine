from datetime import datetime, timedelta
from pathlib import Path

from app.models.audio_asset import AudioAsset
from app.models.enums import StorageClass, TrackStatus
from app.models.station import Station
from app.models.track import Track
from app.services.storage import cleanup_storage


def test_storage_cleanup_deletes_old_failed(db_session, tmp_path: Path, monkeypatch):
    f = tmp_path / 'bad.wav'
    f.write_bytes(b'x')
    tr = Track(
        station_id=1,
        title='bad',
        status=TrackStatus.failed,
        storage_class=StorageClass.failed,
        file_path=str(f),
        created_at=datetime.utcnow() - timedelta(hours=2),
    )
    db_session.add(tr)
    db_session.commit()

    result = cleanup_storage(db_session)
    assert result['tracks_deleted'] >= 1


def test_storage_cleanup_detaches_fk_before_audio_asset_delete(db_session, tmp_path: Path):
    st = Station(slug='fk-safe', name='FK Safe', genre='Synthwave', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    f = tmp_path / 'old.wav'
    f.write_bytes(b'x')
    asset = AudioAsset(file_path=str(f))
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    tr = Track(
        station_id=st.id,
        title='old aired',
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        created_at=datetime.utcnow() - timedelta(days=7),
        audio_asset_id=asset.id,
    )
    db_session.add(tr)
    db_session.commit()
    db_session.refresh(tr)

    cleanup_storage(db_session)
    db_session.refresh(tr)

    assert tr.status == TrackStatus.deleted
    assert tr.audio_asset_id is None
    assert db_session.get(AudioAsset, asset.id) is None


def test_storage_cleanup_repairs_legacy_deleted_refs(db_session, tmp_path: Path):
    st = Station(slug='legacy-fk', name='Legacy FK', genre='Synthwave', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    f = tmp_path / 'legacy.wav'
    f.write_bytes(b'x')
    asset = AudioAsset(file_path=str(f))
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)

    tr = Track(
        station_id=st.id,
        title='legacy deleted',
        status=TrackStatus.deleted,
        storage_class=StorageClass.hot,
        created_at=datetime.utcnow() - timedelta(days=10),
        deleted_at=datetime.utcnow() - timedelta(days=9),
        audio_asset_id=asset.id,
    )
    db_session.add(tr)
    db_session.commit()
    db_session.refresh(tr)

    cleanup_storage(db_session)
    db_session.refresh(tr)

    assert tr.audio_asset_id is None
    assert db_session.get(AudioAsset, asset.id) is None


def test_storage_cleanup_prunes_oldest_tracks_when_cap_exceeded(db_session, tmp_path: Path, monkeypatch):
    st = Station(slug='cap-prune', name='Cap Prune', genre='Synthwave', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    old_file = tmp_path / 'old.wav'
    old_file.write_bytes(b'a' * 1200)
    old_asset = AudioAsset(file_path=str(old_file), file_size_bytes=1200, audio_format='wav')
    db_session.add(old_asset)
    db_session.commit()
    db_session.refresh(old_asset)

    new_file = tmp_path / 'new.wav'
    new_file.write_bytes(b'b' * 900)
    new_asset = AudioAsset(file_path=str(new_file), file_size_bytes=900, audio_format='wav')
    db_session.add(new_asset)
    db_session.commit()
    db_session.refresh(new_asset)

    old_track = Track(
        station_id=st.id,
        title='old aired',
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        created_at=datetime.utcnow() - timedelta(minutes=20),
        file_size_bytes=1200,
        audio_asset_id=old_asset.id,
    )
    new_track = Track(
        station_id=st.id,
        title='new aired',
        status=TrackStatus.aired,
        storage_class=StorageClass.hot,
        created_at=datetime.utcnow() - timedelta(minutes=5),
        file_size_bytes=900,
        audio_asset_id=new_asset.id,
    )
    db_session.add_all([old_track, new_track])
    db_session.commit()

    monkeypatch.setattr("app.services.storage._managed_generated_bytes", lambda: 2500)
    monkeypatch.setattr("app.services.storage._generated_storage_cap_bytes", lambda: 2000)

    result = cleanup_storage(db_session)
    db_session.refresh(old_track)
    db_session.refresh(new_track)

    assert result["tracks_pruned_for_cap"] == 1
    assert old_track.status == TrackStatus.deleted
    assert new_track.status == TrackStatus.aired


def test_storage_cleanup_removes_files_for_deleted_tracks_without_assets(db_session, tmp_path: Path):
    st = Station(slug='deleted-file-clean', name='Deleted File Clean', genre='Synthwave', personality='P', description='d', circadian_profile={})
    db_session.add(st)
    db_session.commit()
    db_session.refresh(st)

    leaked = tmp_path / 'leaked.wav'
    leaked.write_bytes(b'z' * 2048)
    tr = Track(
        station_id=st.id,
        title='deleted legacy',
        status=TrackStatus.deleted,
        storage_class=StorageClass.hot,
        created_at=datetime.utcnow() - timedelta(days=3),
        deleted_at=datetime.utcnow() - timedelta(days=2),
        audio_asset_id=None,
        file_path=str(leaked),
        file_size_bytes=2048,
    )
    db_session.add(tr)
    db_session.commit()
    db_session.refresh(tr)

    result = cleanup_storage(db_session)
    db_session.refresh(tr)

    assert not leaked.exists()
    assert tr.file_path is None
    assert int(tr.file_size_bytes or 0) == 0
    assert int(result.get("detached_deleted_files_removed", 0)) >= 1
