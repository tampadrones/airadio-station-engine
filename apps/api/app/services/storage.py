from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.audio_asset import AudioAsset
from app.models.enums import StorageClass, TrackStatus
from app.models.track import Track
from app.services.ops_events import emit_event


def ensure_storage_roots() -> None:
    s = get_settings()
    roots = [
        s.hot_storage_root,
        s.warm_storage_root,
        s.cold_storage_root,
        s.temp_storage_root,
        s.failed_storage_root,
        s.hls_root,
        s.playback_root,
        str(Path(s.playback_root) / "stations"),
    ]
    for p in roots:
        Path(p).mkdir(parents=True, exist_ok=True)


def station_track_dir(station_slug: str) -> Path:
    s = get_settings()
    d = Path(s.hot_storage_root) / "stations" / station_slug / "tracks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def usage_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            total += fp.stat().st_size
    return total


def _is_asset_referenced(db: Session, audio_asset_id: int) -> bool:
    # FK safety: any row in tracks referencing this asset blocks asset delete.
    any_ref = db.query(Track.id).filter(Track.audio_asset_id == audio_asset_id).first()
    return any_ref is not None


def _is_file_path_referenced(db: Session, file_path: str, *, exclude_track_id: int | None = None) -> bool:
    """
    A filesystem path may be shared across multiple Track rows (for example via
    reuse/duplication bugs). Never delete the underlying file while any other
    non-deleted track still points at it.
    """
    fp = (file_path or "").strip()
    if not fp:
        return False
    q = db.query(Track.id).filter(
        Track.file_path == fp,
        Track.status != TrackStatus.deleted,
    )
    if exclude_track_id is not None:
        q = q.filter(Track.id != int(exclude_track_id))
    return q.first() is not None


def _generated_storage_cap_bytes() -> int:
    s = get_settings()
    return max(1, int(s.generated_storage_cap_gb)) * 1_000_000_000


def _managed_generated_bytes() -> int:
    s = get_settings()
    usage = summarize_storage_usage()
    total = int(usage["hot_bytes"] + usage["warm_bytes"] + usage["cold_bytes"] + usage["temp_bytes"] + usage["failed_bytes"])
    if bool(s.include_ace_step_export_in_cap):
        total += int(usage_bytes(Path(str(s.ace_step_export_dir or "").strip())))
    return total


def _prune_oldest_export_files(export_root: Path, overage_bytes: int) -> tuple[int, int]:
    if overage_bytes <= 0 or not export_root.exists():
        return (0, 0)
    candidates: list[tuple[float, Path, int]] = []
    for root, _, files in os.walk(export_root):
        for name in files:
            p = Path(root) / name
            try:
                st = p.stat()
            except Exception:
                continue
            candidates.append((float(st.st_mtime), p, int(st.st_size)))
    candidates.sort(key=lambda item: item[0])
    deleted = 0
    freed = 0
    for _, p, size in candidates:
        if freed >= overage_bytes:
            break
        try:
            p.unlink(missing_ok=True)
            deleted += 1
            freed += int(size)
        except Exception:
            continue
    return (deleted, freed)


def _mark_oldest_tracks_for_cap_cleanup(db: Session, overage_bytes: int, now: datetime) -> tuple[int, int]:
    if overage_bytes <= 0:
        return (0, 0)

    marked = 0
    detached_refs = 0
    reclaimed_estimate = 0
    def reclaimable_estimate_bytes(track: Track) -> int:
        fp = str(track.file_path or "")
        if fp:
            p = Path(fp)
            if p.exists():
                try:
                    return int(p.stat().st_size)
                except Exception:
                    pass
        # If an audio_asset is still attached, keep a conservative estimate fallback.
        if track.audio_asset_id is not None:
            return int(track.file_size_bytes or 0)
        # Detached rows with missing files are not reclaimable.
        return 0

    # Prioritize pruning aired/failed first; only then walk already-deleted rows.
    rows = (
        db.query(Track)
        .filter(Track.status.in_([TrackStatus.aired, TrackStatus.failed]))
        .order_by(Track.created_at.asc(), Track.id.asc())
        .all()
    )
    rows.extend(
        db.query(Track)
        .filter(Track.status == TrackStatus.deleted)
        .order_by(Track.created_at.asc(), Track.id.asc())
        .all()
    )
    for track in rows:
        if reclaimed_estimate >= overage_bytes:
            break
        reclaim_bytes = reclaimable_estimate_bytes(track)
        if reclaim_bytes <= 0 and track.audio_asset_id is None:
            continue
        if track.status != TrackStatus.deleted:
            track.status = TrackStatus.deleted
        if track.deleted_at is None:
            track.deleted_at = now
        if track.audio_asset_id is not None:
            track.audio_asset_id = None
            detached_refs += 1
        reclaimed_estimate += int(reclaim_bytes)
        marked += 1

    return (marked, detached_refs)


def _delete_detached_deleted_track_files(db: Session) -> tuple[int, int]:
    """Delete files for tombstoned tracks that no longer reference audio_assets."""
    rows = (
        db.query(Track)
        .filter(
            Track.status == TrackStatus.deleted,
            Track.audio_asset_id.is_(None),
            Track.file_path.is_not(None),
        )
        .all()
    )
    deleted_files = 0
    freed_bytes = 0
    for track in rows:
        p = Path(str(track.file_path or ""))
        if not p:
            continue
        # Safety: the same file_path might still be referenced by another ready/queued track.
        if _is_file_path_referenced(db, str(track.file_path or ""), exclude_track_id=track.id):
            track.file_path = None
            track.preview_path = None
            track.file_size_bytes = 0
            db.add(track)
            continue
        try:
            if p.exists():
                try:
                    freed_bytes += int(p.stat().st_size)
                except Exception:
                    pass
                p.unlink(missing_ok=True)
                deleted_files += 1
        except Exception:
            # Best-effort cleanup; leave DB record as-is on FS errors.
            continue
        track.file_path = None
        track.preview_path = None
        track.file_size_bytes = 0
        db.add(track)
    if deleted_files:
        db.commit()
    return deleted_files, freed_bytes


def cleanup_storage(db: Session) -> dict:
    s = get_settings()
    now = datetime.utcnow()
    deleted = 0
    detached_refs = 0
    cap_pruned = 0
    detached_deleted_files = 0
    detached_deleted_freed_bytes = 0
    export_files_pruned = 0
    export_files_freed_bytes = 0

    for track in (
        db.query(Track)
        .filter(Track.status.in_([TrackStatus.failed, TrackStatus.aired]))
        .filter(Track.deleted_at.is_(None))
        .all()
    ):
        age = now - track.created_at
        should_delete = False
        if track.status == TrackStatus.failed and age > timedelta(hours=1):
            should_delete = True
        if track.status == TrackStatus.aired and track.storage_class == StorageClass.hot and age > timedelta(hours=s.hot_retention_hours):
            should_delete = True
        if should_delete:
            track.deleted_at = now
            track.status = TrackStatus.deleted
            if track.audio_asset_id is not None:
                track.audio_asset_id = None
                detached_refs += 1
            deleted += 1

    db.commit()

    managed_total = _managed_generated_bytes()
    cap_bytes = _generated_storage_cap_bytes()
    if managed_total > cap_bytes:
        export_root = Path(str(s.ace_step_export_dir or "").strip())
        export_pruned, export_freed = _prune_oldest_export_files(export_root, managed_total - cap_bytes)
        if export_pruned:
            export_files_pruned += int(export_pruned)
            export_files_freed_bytes += int(export_freed)
            managed_total = _managed_generated_bytes()
        cap_pruned, detached_cap = _mark_oldest_tracks_for_cap_cleanup(
            db=db,
            overage_bytes=max(0, managed_total - cap_bytes),
            now=now,
        )
        if detached_cap:
            detached_refs += detached_cap
        if cap_pruned:
            emit_event(
                db,
                service="worker",
                event_type="storage_quota_warning",
                message="Generated storage cap exceeded; pruning oldest tracks",
                details={
                    "cap_bytes": int(cap_bytes),
                    "usage_bytes": int(managed_total),
                    "overage_bytes": int(max(0, managed_total - cap_bytes)),
                    "tracks_pruned": int(cap_pruned),
                    "export_files_pruned": int(export_files_pruned),
                    "export_files_freed_bytes": int(export_files_freed_bytes),
                },
            )
            db.commit()

    # Repair legacy deleted rows that still keep audio_asset FK references.
    detached_legacy = (
        db.query(Track)
        .filter(Track.deleted_at.is_not(None), Track.audio_asset_id.is_not(None))
        .update({Track.audio_asset_id: None}, synchronize_session=False)
    )
    if detached_legacy:
        detached_refs += int(detached_legacy)
        db.commit()

    detached_deleted_files, detached_deleted_freed_bytes = _delete_detached_deleted_track_files(db)

    # Delete unreferenced audio assets only after track tombstoning.
    assets = db.query(AudioAsset).all()
    for asset in assets:
        if _is_asset_referenced(db, asset.id):
            continue
        if asset.file_path and Path(asset.file_path).exists():
            Path(asset.file_path).unlink(missing_ok=True)
        db.delete(asset)

    db.commit()
    emit_event(
        db,
        service="worker",
        event_type="storage_cleanup_completed",
        message="Storage cleanup completed",
        details={
            "tracks_deleted": deleted,
            "tracks_pruned_for_cap": cap_pruned,
            "audio_asset_refs_detached": detached_refs,
            "detached_deleted_files_removed": detached_deleted_files,
            "detached_deleted_files_freed_bytes": int(detached_deleted_freed_bytes),
            "export_files_pruned": int(export_files_pruned),
            "export_files_freed_bytes": int(export_files_freed_bytes),
            "generated_storage_cap_bytes": int(cap_bytes),
        },
    )

    usage = summarize_storage_usage()
    usage["tracks_deleted"] = deleted
    usage["tracks_pruned_for_cap"] = cap_pruned
    usage["detached_deleted_files_removed"] = int(detached_deleted_files)
    usage["detached_deleted_files_freed_bytes"] = int(detached_deleted_freed_bytes)
    usage["export_files_pruned"] = int(export_files_pruned)
    usage["export_files_freed_bytes"] = int(export_files_freed_bytes)
    return usage


def purge_tracks(
    db: Session,
    *,
    station_id: int | None = None,
    include_active: bool = False,
) -> dict[str, int]:
    removable_statuses = [TrackStatus.failed, TrackStatus.aired, TrackStatus.deleted]
    if include_active:
        removable_statuses.extend([TrackStatus.ready, TrackStatus.queued, TrackStatus.pending])

    q = db.query(Track).filter(Track.status.in_(removable_statuses))
    if station_id is not None:
        q = q.filter(Track.station_id == station_id)
    tracks = q.all()

    freed_bytes = 0
    deleted_tracks = 0
    detached_refs = 0
    for track in tracks:
        if track.file_size_bytes:
            freed_bytes += int(track.file_size_bytes)
        if track.file_path:
            Path(track.file_path).unlink(missing_ok=True)
        if track.preview_path:
            Path(track.preview_path).unlink(missing_ok=True)
        if track.audio_asset_id is not None:
            detached_refs += 1
        db.delete(track)
        deleted_tracks += 1

    db.flush()

    deleted_assets = 0
    assets = db.query(AudioAsset).all()
    for asset in assets:
        if _is_asset_referenced(db, asset.id):
            continue
        if asset.file_path:
            Path(asset.file_path).unlink(missing_ok=True)
        db.delete(asset)
        deleted_assets += 1

    db.commit()
    return {
        "tracks_deleted": int(deleted_tracks),
        "audio_assets_deleted": int(deleted_assets),
        "audio_asset_refs_detached": int(detached_refs),
        "freed_bytes_estimate": int(freed_bytes),
    }


def summarize_storage_usage() -> dict:
    s = get_settings()
    hot = usage_bytes(Path(s.hot_storage_root))
    warm = usage_bytes(Path(s.warm_storage_root))
    cold = usage_bytes(Path(s.cold_storage_root))
    temp = usage_bytes(Path(s.temp_storage_root))
    failed = usage_bytes(Path(s.failed_storage_root))
    return {
        "hot_bytes": hot,
        "warm_bytes": warm,
        "cold_bytes": cold,
        "temp_bytes": temp,
        "failed_bytes": failed,
        "tracks_deleted": 0,
    }


def move_to_failed(path: str) -> str:
    s = get_settings()
    src = Path(path)
    dst = Path(s.failed_storage_root) / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return str(dst)
