from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.audio_asset import AudioAsset
from app.models.enums import TrackStatus
from app.models.ops_event import OpsEvent
from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.models.track import Track
from app.models.track_analysis import TrackAnalysis
from app.models.track_generation import TrackGeneration
from app.models.track_play_event import TrackPlayEvent
from app.models.track_promotion import TrackPromotion
from app.services.daypart import get_daypart_blend
from app.services.generator_health import check_generator_health
from app.services.listeners import get_listener_counts, get_listener_rollups, get_peak_listeners_today
from app.services.playback_backend import get_playback_backend
from app.services.storage import summarize_storage_usage, usage_bytes


def get_backend():
    return get_playback_backend()


def _hot_disk_usage() -> tuple[int | None, int | None, int | None]:
    try:
        disk = shutil.disk_usage(get_settings().hot_storage_root)
        return int(disk.total), int(disk.used), int(disk.free)
    except FileNotFoundError:
        return None, None, None


def _today_window_start_utc(now_utc: datetime | None = None) -> datetime:
    settings = get_settings()
    tz_name = settings.timezone or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = timezone.utc
    now = (now_utc or datetime.utcnow()).replace(tzinfo=timezone.utc)
    local_now = now.astimezone(tz)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def _generator_queue_status() -> dict[str, int | str | None]:
    settings = get_settings()
    health = check_generator_health(settings)
    status_url = str(health.get("generator_status_url", ""))
    if not bool(health.get("reachable")):
        return {
            "generator_queue_size": None,
            "generator_queue_health": "unavailable",
            "generator_queue_status_url": status_url,
        }
    try:
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            resp = client.get(status_url)
            resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return {
            "generator_queue_size": None,
            "generator_queue_health": "unavailable",
            "generator_queue_status_url": status_url,
        }

    queue_size = payload.get("queue_size")
    if not isinstance(queue_size, int):
        for key in ("size", "pending", "queue_length"):
            candidate = payload.get(key)
            if isinstance(candidate, int):
                queue_size = candidate
                break

    return {
        "generator_queue_size": int(queue_size) if isinstance(queue_size, int) else None,
        "generator_queue_health": "healthy",
        "generator_queue_status_url": status_url,
    }


def reset_failed_generations_today(db: Session) -> dict:
    now = datetime.utcnow()
    since = _today_window_start_utc(now)
    deleted = (
        db.query(OpsEvent)
        .filter(OpsEvent.timestamp >= since, OpsEvent.timestamp <= now, OpsEvent.event_type == "generation_failed")
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": int(deleted), "since_utc": since.isoformat(), "until_utc": now.isoformat()}


def overview_stats(db: Session) -> dict:
    now = datetime.utcnow()
    since = _today_window_start_utc(now)
    station_count = db.query(func.count(Station.id)).scalar() or 0
    enabled_stations = db.query(func.count(Station.id)).filter(Station.is_enabled.is_(True)).scalar() or 0
    active_jobs = db.query(func.count(Track.id)).filter(Track.status == TrackStatus.generating).scalar() or 0
    failed_today = (
        db.query(func.count(OpsEvent.id))
        .filter(OpsEvent.timestamp >= since, OpsEvent.event_type == "generation_failed")
        .scalar()
        or 0
    )
    generated_today = (
        db.query(func.count(TrackGeneration.track_id)).filter(TrackGeneration.created_at >= since).scalar() or 0
    )
    avg_latency = db.query(func.avg(TrackGeneration.generation_seconds)).scalar() or 0
    elapsed_hours = max((now - since).total_seconds() / 3600.0, 1.0)
    tracks_per_hour = generated_today / elapsed_hours
    storage = summarize_storage_usage()
    disk_total, disk_used, disk_free = _hot_disk_usage()

    playback_alive = 0
    states = db.query(StationPlaybackState).all()
    for st in states:
        if st.manifest_age_seconds is not None and st.manifest_age_seconds < 180:
            playback_alive += 1

    enabled_slugs = [s.slug for s in db.query(Station).filter(Station.is_enabled.is_(True)).all()]
    total_listeners, _ = get_listener_counts(enabled_slugs)

    return {
        "total_listeners": total_listeners,
        "active_stations": enabled_stations,
        "station_count": station_count,
        "active_generation_jobs": active_jobs,
        "failed_generations_today": failed_today,
        "hot_storage_usage": storage["hot_bytes"],
        "hot_storage_usage_gb": round(float(storage["hot_bytes"]) / 1_000_000_000, 2),
        "hot_storage_usage_mb": round(float(storage["hot_bytes"]) / 1_000_000, 2),
        "hot_storage_total_bytes": disk_total or 0,
        "hot_storage_total_gb": round(float(disk_total or 0) / 1_000_000_000, 2),
        "hot_storage_total_mb": round(float(disk_total or 0) / 1_000_000, 2),
        "hot_storage_free_bytes": disk_free or 0,
        "hot_storage_free_gb": round(float(disk_free or 0) / 1_000_000_000, 2),
        "hot_storage_free_mb": round(float(disk_free or 0) / 1_000_000, 2),
        "hot_storage_used_percent": round(((disk_used or 0) / (disk_total or 1)) * 100.0, 2) if disk_total else 0.0,
        "avg_generation_latency": round(float(avg_latency), 2),
        "tracks_generated_today": generated_today,
        "tracks_per_hour": round(tracks_per_hour, 2),
        "playback_backend_alive": playback_alive,
    }


def station_health(db: Session) -> list[dict]:
    rows = []
    backend = get_backend()
    settings = get_settings()
    daypart_now = get_daypart_blend(datetime.utcnow(), settings.timezone).daypart
    stations = db.query(Station).filter(Station.is_enabled.is_(True)).all()
    for station in stations:
        total_tracks = db.query(func.count(Track.id)).filter(Track.station_id == station.id).scalar() or 0
        ready = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.ready).scalar() or 0
        queue_depth = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status.in_([TrackStatus.ready, TrackStatus.queued])).scalar() or 0
        generating = db.query(func.count(Track.id)).filter(Track.station_id == station.id, Track.status == TrackStatus.generating).scalar() or 0
        buffer = db.query(func.coalesce(func.sum(Track.duration_sec), 0)).filter(Track.station_id == station.id, Track.status.in_([TrackStatus.ready, TrackStatus.queued])).scalar() or 0
        state = db.query(StationPlaybackState).filter(StationPlaybackState.station_id == station.id).first()
        last_success = (
            db.query(func.max(TrackGeneration.created_at))
            .join(Track, Track.id == TrackGeneration.track_id)
            .filter(Track.station_id == station.id)
            .scalar()
        )
        last_failed = (
            db.query(func.max(OpsEvent.timestamp))
            .filter(OpsEvent.station_id == station.id, OpsEvent.event_type == "generation_failed")
            .scalar()
        )
        generated_last_hour = (
            db.query(func.count(TrackGeneration.track_id))
            .join(Track, Track.id == TrackGeneration.track_id)
            .filter(Track.station_id == station.id, TrackGeneration.created_at >= datetime.utcnow() - timedelta(hours=1))
            .scalar()
            or 0
        )

        bootstrap_active = (total_tracks < station.target_queue_depth and queue_depth < station.target_queue_depth) or (
            queue_depth == 0 and generating > 0
        )
        status = "healthy"
        if bootstrap_active:
            status = "bootstrapping"
        elif queue_depth < station.target_queue_depth:
            status = "degraded"
        if queue_depth == 0 and generating == 0 and not bootstrap_active:
            status = "stalled"

        now_title = state.current_title if state else None
        latest_analysis = (
            db.query(TrackAnalysis)
            .join(Track, Track.id == TrackAnalysis.track_id)
            .filter(Track.station_id == station.id)
            .order_by(TrackAnalysis.created_at.desc())
            .first()
        )
        mood = "baseline"
        daypart = daypart_now
        if latest_analysis and isinstance(latest_analysis.tags, dict):
            mood = str(latest_analysis.tags.get("mood", mood))
            daypart = str(latest_analysis.tags.get("daypart", daypart))
        h = backend.get_health(station.slug)

        rows.append(
            {
                "station_id": station.id,
                "station_name": station.name,
                "current_status": status,
                "now_playing": now_title,
                "queue_depth": queue_depth,
                "target_queue_depth": station.target_queue_depth,
                "ready_tracks": ready,
                "generation_in_progress": generating > 0,
                "generation_jobs": int(generating),
                "buffer_seconds": int(buffer),
                "buffer_minutes_remaining": round(buffer / 60, 2),
                "daypart": daypart,
                "mood": mood,
                "personality": station.personality,
                "tracks_generated_last_hour": int(generated_last_hour),
                "last_successful_generation": last_success,
                "last_failed_generation": last_failed,
                "playback_backend": "liquidsoap",
                "manifest_age_seconds": h.manifest_age_seconds,
                "queue_export_age_seconds": h.queue_export_age_seconds,
                "fallback_active": state.fallback_active if state else False,
                "backend_db_drift_count": h.drift_count,
            }
        )
    return rows


def playback_stats(db: Session) -> list[dict]:
    backend = get_backend()
    stations = db.query(Station).filter(Station.is_enabled.is_(True)).all()
    out: list[dict] = []
    for station in stations:
        state = db.query(StationPlaybackState).filter(StationPlaybackState.station_id == station.id).first()
        h = backend.get_health(station.slug)
        np = backend.get_now_playing(station.slug)
        resolved_title = np.title or (state.current_title if state else None)
        title_indicates_reuse = isinstance(resolved_title, str) and "(reused)" in resolved_title.lower()
        replay_active = bool(np.fallback_active or title_indicates_reuse)
        out.append(
            {
                "station_slug": station.slug,
                "backend_alive": h.alive,
                "manifest_age_seconds": h.manifest_age_seconds,
                "queue_export_age_seconds": h.queue_export_age_seconds,
                "fallback_active": np.fallback_active,
                "replay_active": replay_active,
                "replay_reason": "fallback_active" if np.fallback_active else ("reused_title" if title_indicates_reuse else "none"),
                "backend_db_drift_count": h.drift_count,
                "now_playing": resolved_title,
            }
        )
    return out


def generation_stats(db: Session) -> dict:
    since = datetime.utcnow() - timedelta(hours=24)
    latencies = [float(x[0]) for x in db.query(TrackGeneration.generation_seconds).filter(TrackGeneration.created_at >= since, TrackGeneration.generation_seconds.is_not(None)).all()]
    latencies.sort()

    def percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        idx = int(round((len(values) - 1) * p))
        idx = max(0, min(len(values) - 1, idx))
        return values[idx]

    failures_window = (
        db.query(OpsEvent.error_code)
        .filter(OpsEvent.event_type == "generation_failed", OpsEvent.timestamp >= since)
        .all()
    )
    by_reason: dict[str, int] = {}
    for (reason,) in failures_window:
        key = reason or "unknown"
        by_reason[key] = by_reason.get(key, 0) + 1

    success_count = db.query(func.count(TrackGeneration.track_id)).filter(TrackGeneration.created_at >= since).scalar() or 0
    fail_count_window = len(failures_window)
    fail_count_total = db.query(func.count(OpsEvent.id)).filter(OpsEvent.event_type == "generation_failed").scalar() or 0
    attempts = success_count + fail_count_window
    success_rate = (float(success_count) / float(attempts)) if attempts else 1.0

    retry_count = (
        db.query(func.count(OpsEvent.id))
        .filter(OpsEvent.event_type == "generation_retried", OpsEvent.timestamp >= since)
        .scalar()
        or 0
    )
    active_jobs = db.query(func.count(Track.id)).filter(Track.status == TrackStatus.generating).scalar() or 0
    queued_jobs = db.query(func.count(Track.id)).filter(Track.status == TrackStatus.pending).scalar() or 0

    avg_qc = db.query(func.avg(TrackAnalysis.qc_score)).filter(TrackAnalysis.created_at >= since).scalar() or 0.0
    avg_fit = db.query(func.avg(TrackAnalysis.station_fit_score)).filter(TrackAnalysis.created_at >= since).scalar() or 0.0

    health = check_generator_health(get_settings())
    host_health = "healthy" if bool(health.get("reachable")) else "unhealthy"
    generator_queue = _generator_queue_status()
    last_success = db.query(func.max(TrackGeneration.created_at)).scalar()
    last_failed = db.query(func.max(OpsEvent.timestamp)).filter(OpsEvent.event_type == "generation_failed").scalar()

    return {
        "average_generation_latency": round(float(sum(latencies) / len(latencies)), 2) if latencies else 0.0,
        "p50_latency": round(percentile(latencies, 0.50), 2),
        "p95_latency": round(percentile(latencies, 0.95), 2),
        "p99_latency": round(percentile(latencies, 0.99), 2),
        "active_generation_jobs": int(active_jobs),
        "queued_generation_jobs": int(queued_jobs),
        "success_rate": round(success_rate, 4),
        "failed_generations": int(fail_count_window),
        "failed_generations_window": "24h",
        "failed_generations_total": int(fail_count_total),
        "failed_generations_by_reason": by_reason,
        "retry_count": int(retry_count),
        "generator_host_health": host_health,
        "last_successful_generation_at": last_success.isoformat() if last_success else None,
        "last_failed_generation_at": last_failed.isoformat() if last_failed else None,
        "current_generator_base_url": str(health.get("generator_base_url", "")),
        "average_qc_score": round(float(avg_qc), 3),
        "average_station_fit_score": round(float(avg_fit), 3),
        **generator_queue,
    }


def listener_stats(db: Session) -> dict:
    slugs = [s.slug for s in db.query(Station).filter(Station.is_enabled.is_(True)).all()]
    total, by_station = get_listener_counts(slugs)
    peak_today, peak_by_station = get_peak_listeners_today(slugs)
    rollups = get_listener_rollups()
    return {
        "current_listeners_total": int(total),
        "current_listeners_by_station": by_station,
        "peak_listeners_today": int(peak_today),
        "peak_listeners_by_station": peak_by_station,
        "average_session_length": rollups["average_session_length"],
        "starts_per_hour": int(rollups["starts_per_hour"]),
        "disconnects_per_hour": int(rollups["disconnects_per_hour"]),
        "stream_errors": int(rollups.get("stream_errors", 0)),
        "skip_rate": float(rollups.get("skip_rate", 0.0)),
        "completion_rate": float(rollups.get("completion_rate", 0.0)),
        "rebuffer_events": int(rollups.get("rebuffer_events", 0)),
    }


def storage_stats(db: Session) -> dict:
    settings = get_settings()
    storage = summarize_storage_usage()
    export_bytes = usage_bytes(Path(str(settings.ace_step_export_dir or "").strip()))
    include_export = bool(settings.include_ace_step_export_in_cap)
    now = datetime.utcnow()
    since = _today_window_start_utc(now)
    disk_total, disk_used, disk_free = _hot_disk_usage()
    managed_generated_bytes = int(storage["hot_bytes"] + storage["warm_bytes"] + storage["cold_bytes"] + storage["temp_bytes"] + storage["failed_bytes"])
    if include_export:
        managed_generated_bytes += int(export_bytes)
    generated_cap_bytes = max(1, int(settings.generated_storage_cap_gb)) * 1_000_000_000

    top_stations = (
        db.query(Station.slug, func.coalesce(func.sum(Track.file_size_bytes), 0))
        .join(Track, Track.station_id == Station.id)
        .filter(Track.deleted_at.is_(None))
        .group_by(Station.slug)
        .order_by(func.coalesce(func.sum(Track.file_size_bytes), 0).desc())
        .limit(5)
        .all()
    )
    top_storage = [{"station_slug": slug, "bytes": int(total or 0)} for slug, total in top_stations]

    orphaned_files = db.query(func.count(AudioAsset.id)).outerjoin(Track, Track.audio_asset_id == AudioAsset.id).filter(Track.id.is_(None)).scalar() or 0

    mismatch_count = 0
    check_tracks = db.query(Track.file_path).filter(Track.deleted_at.is_(None), Track.file_path.is_not(None)).limit(1500).all()
    for (file_path,) in check_tracks:
        if file_path and not Path(file_path).exists():
            mismatch_count += 1

    tracks_deleted_today = db.query(func.count(Track.id)).filter(Track.status == TrackStatus.deleted, Track.deleted_at >= since).scalar() or 0
    tracks_promoted_today = db.query(func.count(TrackPromotion.track_id)).filter(TrackPromotion.created_at >= since).scalar() or 0
    preview_clips_generated_today = db.query(func.count(Track.id)).filter(Track.preview_path.is_not(None), Track.created_at >= since).scalar() or 0

    growth_bytes_last_hour = db.query(func.coalesce(func.sum(Track.file_size_bytes), 0)).filter(Track.created_at >= now - timedelta(hours=1)).scalar() or 0
    projected = f"{(disk_free / growth_bytes_last_hour):.1f}h" if (growth_bytes_last_hour > 0 and disk_free is not None) else "unknown"

    return {
        "generated_storage_cap_gb": int(settings.generated_storage_cap_gb),
        "generated_storage_cap_bytes": int(generated_cap_bytes),
        "generated_storage_used_bytes": managed_generated_bytes,
        "generated_storage_used_gb": round(float(managed_generated_bytes) / 1_000_000_000, 2),
        "generated_storage_used_mb": round(float(managed_generated_bytes) / 1_000_000, 2),
        "generated_storage_over_cap": managed_generated_bytes > generated_cap_bytes,
        "generated_storage_overage_bytes": int(max(0, managed_generated_bytes - generated_cap_bytes)),
        "hot_storage_used": storage["hot_bytes"],
        "hot_storage_used_gb": round(float(storage["hot_bytes"]) / 1_000_000_000, 2),
        "hot_storage_used_mb": round(float(storage["hot_bytes"]) / 1_000_000, 2),
        "hot_storage_total_bytes": disk_total or 0,
        "hot_storage_total_gb": round(float(disk_total or 0) / 1_000_000_000, 2),
        "hot_storage_total_mb": round(float(disk_total or 0) / 1_000_000, 2),
        "hot_storage_free_bytes": disk_free or 0,
        "hot_storage_free_gb": round(float(disk_free or 0) / 1_000_000_000, 2),
        "hot_storage_free_mb": round(float(disk_free or 0) / 1_000_000, 2),
        "hot_storage_used_percent": round(((disk_used or 0) / (disk_total or 1)) * 100.0, 2) if disk_total else 0.0,
        "warm_storage_used": storage["warm_bytes"],
        "cold_storage_used": storage["cold_bytes"],
        "temp_usage": storage["temp_bytes"],
        "failed_job_storage_usage": storage["failed_bytes"],
        "ace_step_export_usage": int(export_bytes),
        "ace_step_export_usage_gb": round(float(export_bytes) / 1_000_000_000, 2),
        "ace_step_export_usage_mb": round(float(export_bytes) / 1_000_000, 2),
        "include_ace_step_export_in_cap": include_export,
        "tracks_pending_deletion": db.query(Track).filter(Track.status == TrackStatus.failed).count(),
        "tracks_promoted_today": int(tracks_promoted_today),
        "tracks_deleted_today": int(tracks_deleted_today),
        "preview_clips_generated_today": int(preview_clips_generated_today),
        "top_storage_consuming_stations": top_storage,
        "orphaned_files_count": int(orphaned_files),
        "db_file_mismatch_count": int(mismatch_count),
        "storage_growth_per_hour": int(growth_bytes_last_hour),
        "projected_time_to_full_disk": projected,
    }


def reuse_stats(db: Session) -> dict:
    since = datetime.utcnow() - timedelta(hours=24)
    plays = (
        db.query(Track.title)
        .join(TrackPlayEvent, TrackPlayEvent.track_id == Track.id)
        .filter(TrackPlayEvent.played_at >= since)
        .all()
    )
    total = len(plays)
    reused = sum(1 for (title,) in plays if isinstance(title, str) and "(reused)" in title.lower())
    new_plays = total - reused
    plays_new_percent = round((new_plays / total) * 100, 2) if total else 0.0
    plays_reused_percent = round((reused / total) * 100, 2) if total else 0.0

    by_station_rows = (
        db.query(Station.slug, func.count(TrackPlayEvent.id))
        .join(TrackPlayEvent, TrackPlayEvent.station_id == Station.id)
        .filter(TrackPlayEvent.played_at >= since)
        .group_by(Station.slug)
        .all()
    )
    repeat_rate = {slug: 0.0 for slug, _ in by_station_rows}

    top_reused = (
        db.query(Track.id, Track.title, func.count(TrackPlayEvent.id))
        .join(TrackPlayEvent, TrackPlayEvent.track_id == Track.id)
        .filter(TrackPlayEvent.played_at >= since, Track.title.ilike("%(reused)%"))
        .group_by(Track.id, Track.title)
        .order_by(func.count(TrackPlayEvent.id).desc())
        .limit(10)
        .all()
    )

    return {
        "plays_new_percent": plays_new_percent,
        "plays_reused_percent": plays_reused_percent,
        "repeat_reuse_rate_by_station": repeat_rate,
        "average_cooldown_before_replay": 0,
        "top_reused_tracks": [{"track_id": int(tid), "title": title, "plays": int(cnt)} for tid, title, cnt in top_reused],
        "most_skipped_reused_tracks": [],
    }
