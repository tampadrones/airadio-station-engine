from __future__ import annotations

import asyncio
import math
import logging
from datetime import datetime

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import SessionLocal
from app.models.station import Station
from app.services.liquidsoap_config import write_liquidsoap_station_include
from app.services.ops_events import emit_event
from app.services.generation_maintenance import mark_stale_generating_tracks
from app.services.playback_reconcile import reconcile_station_playback
from app.services.playback_sync import sync_station_queue_export
from app.services.seed import ensure_seed_stations
from app.services.station_engine import StationEngine
from app.services.storage import cleanup_storage, ensure_storage_roots
from app.services.listeners import get_listener_counts

configure_logging("worker")
logger = logging.getLogger(__name__)


async def process_station_cycle(
    station_id: int,
    engine: StationEngine,
    *,
    station_current_listeners: int = 0,
    any_active_listeners: bool = False,
) -> None:
    db = SessionLocal()
    try:
        station = db.query(Station).filter(Station.id == station_id, Station.is_enabled.is_(True)).first()
        if not station:
            return
        # Keep playback state fresh even if generation takes multiple minutes.
        exported = sync_station_queue_export(db, station)
        reconcile_station_playback(db, station)
        if exported == 0:
            emit_event(
                db,
                service="worker",
                event_type="station_queue_low",
                message="No playable files exported to playback queue",
                station_id=station.id,
            )

        await engine.refill_station_if_needed(
            db,
            station,
            station_current_listeners=int(station_current_listeners),
            any_active_listeners=bool(any_active_listeners),
        )

        exported = sync_station_queue_export(db, station)
        reconcile_station_playback(db, station)
        if exported == 0:
            emit_event(
                db,
                service="worker",
                event_type="station_queue_low",
                message="No playable files exported to playback queue",
                station_id=station.id,
            )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("station cycle failure", extra={"event_type": "worker_error", "details": {"station_id": station_id, "error": str(exc)}})
    finally:
        db.close()


async def run() -> None:
    settings = get_settings()
    ensure_storage_roots()
    engine = StationEngine()
    station_tasks: dict[int, asyncio.Task[None]] = {}
    startup_stale_minutes = max(1, int(settings.generation_startup_stale_track_minutes))
    startup_repaired = False
    cleanup_interval_seconds = max(60, int(settings.storage_cleanup_interval_seconds))
    last_cleanup_at: datetime | None = None
    # Keep stale cleanup aligned to the real generation wall-clock timeout so
    # stuck jobs are cleared as soon as they exceed the intended ceiling.
    generation_timeout_minutes = int(math.ceil(engine._generation_call_timeout_seconds() / 60.0))
    derived_stale_minutes = max(1, generation_timeout_minutes)
    configured_stale_minutes = max(0, int(settings.generation_stale_track_minutes))
    if configured_stale_minutes <= 0:
        computed_stale_minutes = derived_stale_minutes
    else:
        computed_stale_minutes = configured_stale_minutes

    while True:
        db = SessionLocal()
        try:
            ensure_seed_stations(db)
            if not startup_repaired:
                startup_stale_count = mark_stale_generating_tracks(db, max_age_minutes=startup_stale_minutes)
                startup_repaired = True
                if startup_stale_count:
                    emit_event(
                        db,
                        service="worker",
                        event_type="stats_snapshot_written",
                        message=f"Startup stale generation repair: {startup_stale_count} (threshold={startup_stale_minutes}m)",
                    )
                    logger.info(
                        "startup_stale_generation_repair",
                        extra={
                            "event_type": "startup_stale_generation_repair",
                            "details": {"count": int(startup_stale_count), "threshold_minutes": int(startup_stale_minutes)},
                        },
                    )
            stale_count = mark_stale_generating_tracks(db, max_age_minutes=computed_stale_minutes)
            if stale_count:
                emit_event(
                    db,
                    service="worker",
                    event_type="stats_snapshot_written",
                    message=f"Stale generating tracks cleaned: {stale_count} (threshold={computed_stale_minutes}m)",
                )
            changed = write_liquidsoap_station_include(db)
            if changed:
                emit_event(db, service="worker", event_type="stats_snapshot_written", message="Liquidsoap station include updated")
            stations = db.query(Station.id, Station.slug).filter(Station.is_enabled.is_(True)).all()
            station_ids = [int(x[0]) for x in stations]
            station_slug_by_id = {int(sid): str(slug) for sid, slug in stations}

            # Snapshot listeners once per tick so we can prioritize generation for active listeners.
            slugs = [slug for slug in station_slug_by_id.values() if slug]
            total_listeners, by_station = get_listener_counts(slugs) if slugs else (0, {})
            any_active_listeners = total_listeners > 0

            now_utc = datetime.utcnow()
            should_cleanup = (
                last_cleanup_at is None
                or (now_utc - last_cleanup_at).total_seconds() >= float(cleanup_interval_seconds)
            )
            if should_cleanup:
                cleanup_storage(db)
                last_cleanup_at = now_utc

            if now_utc.hour == 0 and now_utc.minute < 2:
                emit_event(db, service="worker", event_type="stats_snapshot_written", message="Daily summary tick")

            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("worker setup failure", extra={"event_type": "worker_error", "details": {"error": str(exc)}})
            db.rollback()
            station_ids = []
        finally:
            db.close()

        # Clean up completed tasks and surface exceptions.
        done_ids = [sid for sid, task in station_tasks.items() if task.done()]
        for sid in done_ids:
            task = station_tasks.pop(sid)
            try:
                task.result()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "station task failed",
                    extra={"event_type": "worker_error", "details": {"station_id": sid, "error": str(exc)}},
                )

        if station_ids:
            active = set(station_ids)
            # Drop tasks for disabled/removed stations.
            for sid in [sid for sid in station_tasks if sid not in active]:
                task = station_tasks.pop(sid)
                task.cancel()
            # Stations with more listeners get scheduled first to reduce time-to-first-track under load.
            station_ids_sorted = sorted(
                station_ids,
                key=lambda sid: int(by_station.get(station_slug_by_id.get(int(sid), ""), 0)),
                reverse=True,
            )
            # Start a new cycle only if no cycle is currently running for that station.
            for sid in station_ids_sorted:
                if sid in station_tasks:
                    continue
                slug = station_slug_by_id.get(int(sid), "")
                station_tasks[sid] = asyncio.create_task(
                    process_station_cycle(
                        sid,
                        engine,
                        station_current_listeners=int(by_station.get(slug, 0)),
                        any_active_listeners=any_active_listeners,
                    )
                )

        await asyncio.sleep(settings.worker_tick_seconds)


if __name__ == "__main__":
    asyncio.run(run())
