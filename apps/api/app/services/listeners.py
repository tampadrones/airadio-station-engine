from __future__ import annotations

import time
from datetime import datetime, timezone
from functools import lru_cache

from redis import Redis

from observability.metrics import (
    listener_disconnects_total,
    listener_rebuffer_events_total,
    listener_skip_events_total,
    listener_stream_errors_total,
    listener_completion_rate,
    listener_sessions_started_total,
    listener_avg_session_seconds,
    listeners_current_by_station,
    listeners_current_total,
    station_current_listeners,
    station_peak_listeners_today,
)
from app.core.settings import get_settings

SESSION_TTL_SECONDS = 45
VALID_LISTENER_EVENTS = {"stream_error", "rebuffer", "skip", "completion"}


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _station_key(station_slug: str) -> str:
    return f"listeners:station:{station_slug}:sessions"


def _session_station_key(session_id: str) -> str:
    return f"listeners:session:{session_id}:station"


def _session_started_key(session_id: str) -> str:
    return f"listeners:session:{session_id}:started"


def _day_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _peak_total_key() -> str:
    return f"listeners:peak:total:{_day_key()}"


def _peak_station_key(station_slug: str) -> str:
    return f"listeners:peak:station:{station_slug}:{_day_key()}"


def _last_active_key(station_slug: str) -> str:
    return f"listeners:station:{station_slug}:last_active"


def _starts_hour_key() -> str:
    return f"listeners:starts:hour:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"


def _disconnects_hour_key() -> str:
    return f"listeners:disconnects:hour:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"


def _session_seconds_total_key() -> str:
    return f"listeners:session_seconds_total:{_day_key()}"


def _session_count_key() -> str:
    return f"listeners:session_count:{_day_key()}"


def _event_total_key(event_type: str) -> str:
    return f"listeners:event:{event_type}:{_day_key()}"


def _event_station_key(station_slug: str, event_type: str) -> str:
    return f"listeners:event:{event_type}:station:{station_slug}:{_day_key()}"


def _prune_station(redis: Redis, station_slug: str, now_ts: float) -> None:
    redis.zremrangebyscore(_station_key(station_slug), "-inf", now_ts - SESSION_TTL_SECONDS)


def _count_station(redis: Redis, station_slug: str, now_ts: float) -> int:
    _prune_station(redis, station_slug, now_ts)
    return int(redis.zcard(_station_key(station_slug)))


def get_listener_counts(station_slugs: list[str]) -> tuple[int, dict[str, int]]:
    redis = get_redis()
    now_ts = time.time()
    per_station: dict[str, int] = {}
    total = 0
    for slug in station_slugs:
        cnt = _count_station(redis, slug, now_ts)
        per_station[slug] = cnt
        total += cnt
        listeners_current_by_station.labels(slug).set(float(cnt))
        station_current_listeners.labels(slug).set(float(cnt))
        peak = int(redis.get(_peak_station_key(slug)) or 0)
        station_peak_listeners_today.labels(slug).set(float(peak))
    listeners_current_total.set(float(total))
    return total, per_station


def handle_heartbeat(station_slug: str, session_id: str, playing: bool) -> dict[str, int | str]:
    redis = get_redis()
    now_ts = time.time()
    now_int = int(now_ts)

    current_station = redis.get(_session_station_key(session_id))
    if current_station and current_station != station_slug:
        redis.zrem(_station_key(current_station), session_id)

    if playing:
        started_key = _session_started_key(session_id)
        first_seen = redis.set(started_key, str(now_int), nx=True, ex=24 * 60 * 60)
        if first_seen:
            listener_sessions_started_total.inc()
            redis.incr(_starts_hour_key())

        pipe = redis.pipeline()
        pipe.zadd(_station_key(station_slug), {session_id: now_ts})
        pipe.set(_session_station_key(session_id), station_slug, ex=2 * SESSION_TTL_SECONDS)
        pipe.set(_last_active_key(station_slug), str(now_int), ex=7 * 24 * 60 * 60)
        pipe.execute()
    else:
        station_for_session = current_station or station_slug
        redis.zrem(_station_key(station_for_session), session_id)
        redis.delete(_session_station_key(session_id))
        started_at = redis.get(_session_started_key(session_id))
        if started_at:
            try:
                dur = max(0, now_int - int(started_at))
                redis.incrby(_session_seconds_total_key(), dur)
                redis.incr(_session_count_key())
            except ValueError:
                pass
        redis.delete(_session_started_key(session_id))
        listener_disconnects_total.inc()
        redis.incr(_disconnects_hour_key())

    current = _count_station(redis, station_slug, now_ts)
    redis.set(_peak_station_key(station_slug), str(max(current, int(redis.get(_peak_station_key(station_slug)) or 0))))
    listeners_current_by_station.labels(station_slug).set(float(current))
    station_current_listeners.labels(station_slug).set(float(current))
    station_peak_listeners_today.labels(station_slug).set(float(int(redis.get(_peak_station_key(station_slug)) or 0)))

    return {"station_slug": station_slug, "current_listeners": current}


def should_generate_for_station(
    station_slug: str,
    ready_tracks: int,
    idle_grace_minutes: int = 10,
    idle_min_ready_tracks: int = 1,
    *,
    station_current_listeners: int | None = None,
    any_active_listeners: bool | None = None,
) -> tuple[bool, str]:
    """
    Policy:
    - If this station has active listeners, allow generation.
    - If this station has no listeners, only allow minimal bootstrap when it is below
      `idle_min_ready_tracks`, but suppress bootstrap if *any* station is currently
      being listened to (prioritize active listeners system-wide).
    """
    try:
        if station_current_listeners is None:
            redis = get_redis()
            now_ts = time.time()
            current = _count_station(redis, station_slug, now_ts)
        else:
            current = int(station_current_listeners)

        if current > 0:
            return True, "active_listeners"

        bootstrap_needed = ready_tracks < max(1, int(idle_min_ready_tracks))
        if not bootstrap_needed:
            return False, "idle_no_listeners"

        if any_active_listeners is True:
            return False, "bootstrap_suppressed_active_elsewhere"

        # Allow minimal bootstrap so stations don't get stuck empty after restart.
        return True, "bootstrap_min_ready"
    except Exception:
        # Fails closed: generation should only run for active listeners.
        return False, "listener_state_unavailable"


def get_peak_listeners_today(station_slugs: list[str]) -> tuple[int, dict[str, int]]:
    redis = get_redis()
    per_station = {slug: int(redis.get(_peak_station_key(slug)) or 0) for slug in station_slugs}
    return max(per_station.values(), default=0), per_station


def get_listener_rollups() -> dict[str, float | int]:
    redis = get_redis()
    starts = int(redis.get(_starts_hour_key()) or 0)
    disconnects = int(redis.get(_disconnects_hour_key()) or 0)
    total_seconds = int(redis.get(_session_seconds_total_key()) or 0)
    total_sessions = int(redis.get(_session_count_key()) or 0)
    stream_errors = int(redis.get(_event_total_key("stream_error")) or 0)
    skip_events = int(redis.get(_event_total_key("skip")) or 0)
    completion_events = int(redis.get(_event_total_key("completion")) or 0)
    rebuffer_events = int(redis.get(_event_total_key("rebuffer")) or 0)
    avg_session = float(total_seconds / total_sessions) if total_sessions > 0 else 0.0
    completion_den = completion_events + skip_events
    completion_pct = float(completion_events / completion_den) if completion_den > 0 else 0.0
    skip_rate = float(skip_events / completion_den) if completion_den > 0 else 0.0
    listener_avg_session_seconds.set(avg_session)
    listener_completion_rate.set(completion_pct)
    return {
        "starts_per_hour": starts,
        "disconnects_per_hour": disconnects,
        "average_session_length": round(avg_session, 2),
        "stream_errors": stream_errors,
        "skip_events": skip_events,
        "skip_rate": round(skip_rate, 4),
        "completion_rate": round(completion_pct, 4),
        "rebuffer_events": rebuffer_events,
    }


def handle_listener_event(station_slug: str, session_id: str, event_type: str) -> dict[str, int | str]:
    if event_type not in VALID_LISTENER_EVENTS:
        return {"station_slug": station_slug, "event_type": "ignored", "count": 0}

    redis = get_redis()
    redis.incr(_event_total_key(event_type))
    redis.incr(_event_station_key(station_slug, event_type))

    if event_type == "stream_error":
        listener_stream_errors_total.inc()
    elif event_type == "rebuffer":
        listener_rebuffer_events_total.inc()
    elif event_type == "skip":
        listener_skip_events_total.inc()

    return {
        "station_slug": station_slug,
        "session_id": session_id,
        "event_type": event_type,
        "count": int(redis.get(_event_total_key(event_type)) or 0),
    }
