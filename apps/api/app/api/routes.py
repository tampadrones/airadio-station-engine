from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
import re
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.ops_event import OpsEvent
from app.models.station import Station
from app.models.station_playback_state import StationPlaybackState
from app.models.track import Track
from app.models.track_feedback import TrackFeedback
from app.models.track_generation import TrackGeneration
from app.models.track_promotion import TrackPromotion
from app.models.enums import TrackStatus
from app.schemas.station import (
    StationCreate,
    StationCreateFromTaste,
    StationOut,
    StationReprofileItem,
    StationReprofileRequest,
    StationReprofileResponse,
    StationUpdate,
)
from app.schemas.ops import OpsEventOut
from app.core.settings import get_settings
from app.services.ops_events import emit_event
from app.services.listeners import get_listener_counts, handle_heartbeat, handle_listener_event
from app.services.playback_backend import get_playback_backend
from app.services.liquidsoap_config import force_liquidsoap_reload, write_liquidsoap_station_include
from app.services.station_profile import normalize_station_profile, reprofile_station_profile, slugify_station_name
from app.services.stats import generation_stats, listener_stats, overview_stats, playback_stats, reset_failed_generations_today, reuse_stats, station_health, storage_stats
from app.services.generator_health import check_generator_health
from app.services.generation_preview import build_station_generation_preview
from app.services.station_engine import StationEngine
from app.services.playback_sync import sync_station_queue_export
from app.services.storage import purge_tracks

router = APIRouter()


def _safe_track_filename(station_slug: str, track_id: int, title: str, ext: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", (title or "").strip()).strip("-")
    if not base:
        base = f"track-{track_id}"
    return f"{station_slug}-{track_id}-{base[:80]}{ext}"


def _first_exported_queue_track(backend, station_slug: str) -> tuple[int | None, str | None]:
    playback_root = getattr(backend, "playback_root", None)
    if playback_root is None:
        return None, None
    queue_path = Path(playback_root) / station_slug / "queue.json"
    if not queue_path.exists():
        return None, None
    try:
        payload = json.loads(queue_path.read_text())
    except json.JSONDecodeError:
        return None, None
    tracks = payload.get("tracks")
    if not isinstance(tracks, list) or not tracks:
        return None, None
    first = tracks[0]
    if not isinstance(first, dict):
        return None, None
    track_id = first.get("track_id")
    title = first.get("title")
    if not isinstance(track_id, int):
        return None, None
    return track_id, title if isinstance(title, str) else None


def _track_payload(track: Track | None, *, track_id: int | None = None, title: str | None = None) -> dict | None:
    if track:
        return {
            "id": int(track.id),
            "title": track.title,
            "duration_sec": track.duration_sec,
        }
    if track_id is None and title is None:
        return None
    return {
        "id": track_id,
        "title": title,
        "duration_sec": None,
    }


def _feedback_stats_for_tracks(
    db: Session,
    *,
    station_id: int,
    track_ids: list[int],
    session_id: str | None = None,
) -> dict[int, dict[str, int | str | None]]:
    if not track_ids:
        return {}
    rows = (
        db.query(
            TrackFeedback.track_id,
            func.coalesce(func.sum(case((TrackFeedback.vote == 1, 1), else_=0)), 0).label("likes"),
            func.coalesce(func.sum(case((TrackFeedback.vote == -1, 1), else_=0)), 0).label("dislikes"),
        )
        .filter(
            TrackFeedback.station_id == station_id,
            TrackFeedback.track_id.in_(track_ids),
        )
        .group_by(TrackFeedback.track_id)
        .all()
    )
    out: dict[int, dict[str, int | str | None]] = {
        int(track_id): {
            "likes": int(likes or 0),
            "dislikes": int(dislikes or 0),
            "score": int((likes or 0) - (dislikes or 0)),
            "user_vote": None,
        }
        for track_id, likes, dislikes in rows
    }
    for track_id in track_ids:
        out.setdefault(int(track_id), {"likes": 0, "dislikes": 0, "score": 0, "user_vote": None})

    if session_id:
        mine = (
            db.query(TrackFeedback.track_id, TrackFeedback.vote)
            .filter(
                TrackFeedback.station_id == station_id,
                TrackFeedback.track_id.in_(track_ids),
                TrackFeedback.session_id == session_id,
            )
            .all()
        )
        for tid, vote in mine:
            out[int(tid)]["user_vote"] = "up" if int(vote) > 0 else "down"
    return out


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.head("/health")
def health_head() -> Response:
    return Response(status_code=200)


@router.get("/health/generator")
def generator_health() -> dict:
    return check_generator_health(get_settings())


@router.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/stations", response_model=list[StationOut])
def list_stations(db: Session = Depends(get_db)):
    return db.query(Station).order_by(Station.name.asc()).all()


@router.post("/stations", response_model=StationOut)
def create_station(payload: StationCreate, db: Session = Depends(get_db)):
    body = payload.model_dump()
    body["station_profile"] = normalize_station_profile(body.get("station_profile"))
    st = Station(**body)
    db.add(st)
    db.commit()
    db.refresh(st)
    get_playback_backend().sync_station_queue(st.slug, [])
    write_liquidsoap_station_include(db)
    return st


@router.post("/stations/create-from-taste", response_model=StationOut)
def create_station_from_taste(payload: StationCreateFromTaste, db: Session = Depends(get_db)):
    base_slug = slugify_station_name(payload.name)
    slug = base_slug
    idx = 2
    while db.query(Station).filter(Station.slug == slug).first():
        slug = f"{base_slug}-{idx}"
        idx += 1

    profile = normalize_station_profile(
        {
            "preset": "cohesive_radio",
            "genre_mode": payload.genre_mode,
            "cohesion_spectrum": payload.cohesion_spectrum,
            "discovery_depth": payload.discovery_depth,
            "lyrics_mode": payload.lyrics_mode,
            "mood_seed": payload.mood,
            "clean_lyrics_only": payload.clean_lyrics_only,
            "target_duration_sec": payload.target_duration_sec,
            "duration_jitter_sec": payload.duration_jitter_sec,
            "duration_min_sec": payload.duration_min_sec,
            "duration_max_sec": payload.duration_max_sec,
            "taste_hints": payload.taste_hints,
            "topic_ideas": payload.topic_ideas,
        }
    )
    st = Station(
        slug=slug,
        name=payload.name,
        genre=payload.genre,
        personality=payload.personality,
        description=payload.description,
        circadian_profile={"late_night": 0.8, "morning": 0.8, "midday": 0.9, "evening": 0.9},
        station_profile=profile,
    )
    db.add(st)
    db.commit()
    db.refresh(st)
    get_playback_backend().sync_station_queue(st.slug, [])
    write_liquidsoap_station_include(db)
    return st


@router.patch("/stations/{slug}", response_model=StationOut)
def update_station(slug: str, payload: StationUpdate, db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")

    body = payload.model_dump(exclude_unset=True)
    profile_overrides = {
        "preset": body.pop("preset", None),
        "genre_mode": body.pop("genre_mode", None),
        "cohesion_spectrum": body.pop("cohesion_spectrum", None),
        "discovery_depth": body.pop("discovery_depth", None),
        "lyrics_mode": body.pop("lyrics_mode", None),
        "mood_seed": body.pop("mood_seed", None),
        "clean_lyrics_only": body.pop("clean_lyrics_only", None),
        "mood_volatility": body.pop("mood_volatility", None),
        "energy_variability": body.pop("energy_variability", None),
        "vocal_ratio": body.pop("vocal_ratio", None),
        "target_duration_sec": body.pop("target_duration_sec", None),
        "duration_jitter_sec": body.pop("duration_jitter_sec", None),
        "duration_min_sec": body.pop("duration_min_sec", None),
        "duration_max_sec": body.pop("duration_max_sec", None),
        "ace_overrides": body.pop("ace_overrides", None),
        "taste_hints": body.pop("taste_hints", None),
        "topic_ideas": body.pop("topic_ideas", None),
    }
    profile_overrides = {k: v for k, v in profile_overrides.items() if v is not None}

    if "station_profile" in body or profile_overrides:
        profile = body.pop("station_profile", None)
        if profile is None:
            profile = dict(st.station_profile or {})
        if not isinstance(profile, dict):
            raise HTTPException(status_code=400, detail="station_profile must be a JSON object")
        profile.update(profile_overrides)
        st.station_profile = normalize_station_profile(profile)

    for key in ["name", "genre", "personality", "description", "is_enabled", "target_queue_depth", "min_ready_tracks"]:
        if key in body:
            setattr(st, key, body[key])

    db.add(st)
    db.commit()
    db.refresh(st)

    if not st.is_enabled:
        get_playback_backend().sync_station_queue(st.slug, [])
    write_liquidsoap_station_include(db)
    emit_event(db, service="api", event_type="stats_snapshot_written", message=f"Station updated: {st.slug}")
    return st


@router.post("/stations/reprofile", response_model=StationReprofileResponse)
def reprofile_stations(payload: StationReprofileRequest, db: Session = Depends(get_db)):
    overrides = {
        "preset": payload.preset,
        "genre_mode": payload.genre_mode,
        "cohesion_spectrum": payload.cohesion_spectrum,
        "discovery_depth": payload.discovery_depth,
        "lyrics_mode": payload.lyrics_mode,
        "mood_seed": payload.mood_seed,
        "clean_lyrics_only": payload.clean_lyrics_only,
        "mood_volatility": payload.mood_volatility,
        "energy_variability": payload.energy_variability,
        "vocal_ratio": payload.vocal_ratio,
        "target_duration_sec": payload.target_duration_sec,
        "duration_jitter_sec": payload.duration_jitter_sec,
        "duration_min_sec": payload.duration_min_sec,
        "duration_max_sec": payload.duration_max_sec,
        "ace_overrides": payload.ace_overrides,
        "taste_hints": payload.taste_hints,
        "topic_ideas": payload.topic_ideas,
    }
    overrides = {k: v for k, v in overrides.items() if v is not None}

    q = db.query(Station)
    if not payload.include_disabled:
        q = q.filter(Station.is_enabled.is_(True))
    if payload.station_slugs:
        q = q.filter(Station.slug.in_(payload.station_slugs))
    stations = q.order_by(Station.name.asc()).all()

    items: list[StationReprofileItem] = []
    updated_count = 0

    for station in stations:
        old_profile = normalize_station_profile(station.station_profile or {})
        new_profile = reprofile_station_profile(
            current_profile=old_profile,
            genre=station.genre,
            personality=station.personality,
            description=station.description or "",
            overrides=overrides,
            include_inferred_taste_hints=payload.include_inferred_taste_hints,
        )
        changed = old_profile != new_profile
        if changed and not payload.dry_run:
            station.station_profile = new_profile
            db.add(station)
            updated_count += 1

        items.append(
            StationReprofileItem(
                slug=station.slug,
                old_profile=old_profile,
                new_profile=new_profile,
                changed=changed,
            )
        )

    if not payload.dry_run and updated_count > 0:
        db.commit()
        emit_event(
            db,
            service="api",
            event_type="station_reprofiled",
            message=f"Reprofiled {updated_count} station(s)",
            details={"updated_count": updated_count, "station_slugs": [x.slug for x in items if x.changed]},
        )

    return StationReprofileResponse(updated_count=updated_count, dry_run=payload.dry_run, items=items)


@router.get("/stations/{slug}")
def station_detail(slug: str, session_id: str | None = Query(default=None, max_length=128), db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")
    generation_jobs = db.query(Track).filter(Track.station_id == st.id, Track.status == TrackStatus.generating).count()
    tracks = (
        db.query(Track)
        .filter(Track.station_id == st.id, Track.status.in_([TrackStatus.ready, TrackStatus.queued, TrackStatus.aired]))
        .order_by(Track.created_at.desc())
        .limit(15)
        .all()
    )
    backend = get_playback_backend()
    feedback = _feedback_stats_for_tracks(db, station_id=st.id, track_ids=[int(t.id) for t in tracks], session_id=session_id)
    return {
        "station": StationOut.model_validate(st),
        "recent_tracks": [
            {
                "id": t.id,
                "title": t.title,
                "status": t.status.value,
                "duration_sec": t.duration_sec,
                "created_at": t.created_at,
                "aired_at": t.aired_at,
                "download_url": f"/api/stations/{slug}/tracks/{t.id}/download" if t.file_path else None,
                "feedback": feedback.get(int(t.id), {"likes": 0, "dislikes": 0, "score": 0, "user_vote": None}),
            }
            for t in tracks
        ],
        "stream_url": backend.get_stream_url(slug),
        "generation_in_progress": generation_jobs > 0,
        "generation_jobs": generation_jobs,
    }


@router.get("/stations/{slug}/tracks/{track_id}/download")
def station_track_download(slug: str, track_id: int, db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")

    track = (
        db.query(Track)
        .filter(
            Track.id == track_id,
            Track.station_id == st.id,
            Track.status.in_([TrackStatus.ready, TrackStatus.queued, TrackStatus.aired]),
        )
        .first()
    )
    if not track or not track.file_path:
        raise HTTPException(status_code=404, detail="Track not found")

    file_path = Path(track.file_path)
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Track file missing")

    ext = file_path.suffix or ".wav"
    filename = _safe_track_filename(st.slug, track.id, track.title, ext)
    media_type = "audio/wav" if ext.lower() == ".wav" else "application/octet-stream"
    return FileResponse(path=str(file_path), media_type=media_type, filename=filename)


@router.get("/stations/{slug}/now-playing")
def now_playing(slug: str, session_id: str | None = Query(default=None, max_length=128), db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")
    generation_jobs = db.query(Track).filter(Track.station_id == st.id, Track.status == TrackStatus.generating).count()
    state = db.query(StationPlaybackState).filter(StationPlaybackState.station_id == st.id).first()
    backend = get_playback_backend()
    np = backend.get_now_playing(slug)
    track_payload = None
    if state and state.current_track_id:
        track = db.query(Track).filter(Track.id == state.current_track_id).first()
        if track:
            feedback = _feedback_stats_for_tracks(db, station_id=st.id, track_ids=[int(track.id)], session_id=session_id).get(
                int(track.id),
                {"likes": 0, "dislikes": 0, "score": 0, "user_vote": None},
            )
            track_payload = {
                "id": track.id,
                "title": track.title,
                "duration_sec": track.duration_sec,
                "feedback": feedback,
            }
    if not track_payload and np.title:
        track_payload = {
            "id": np.track_id,
            "title": np.title,
            "duration_sec": None,
            "feedback": {"likes": 0, "dislikes": 0, "score": 0, "user_vote": None},
        }

    _, by_station = get_listener_counts([slug])
    return {
        "station_slug": slug,
        "track": track_payload,
        "listeners": int(by_station.get(slug, 0)),
        "fallback_active": bool(state.fallback_active if state else np.fallback_active),
        "generation_in_progress": generation_jobs > 0,
        "generation_jobs": generation_jobs,
    }


@router.post("/stations/{slug}/skip-current")
def station_skip_current(slug: str, db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")

    backend = get_playback_backend()
    state = db.query(StationPlaybackState).filter(StationPlaybackState.station_id == st.id).first()
    current_track_id = int(state.current_track_id) if state and state.current_track_id else None
    if current_track_id is None:
        now_playing = backend.get_now_playing(st.slug)
        current_track_id = int(now_playing.track_id) if now_playing.track_id else None
    if current_track_id is None:
        raise HTTPException(status_code=409, detail="No current track to skip")

    track = db.query(Track).filter(Track.id == current_track_id, Track.station_id == st.id).first()
    if not track:
        raise HTTPException(status_code=409, detail="Current track record is missing")
    skipped_track_id = int(track.id)

    track.status = TrackStatus.deleted
    track.deleted_at = datetime.utcnow()
    if state:
        state.current_track_id = None
        state.current_title = None
        state.started_at = None
        state.position_sec = None
    db.add(track)
    if state:
        db.add(state)
    db.commit()
    sync_station_queue_export(db, st)
    next_track_id, next_track_title = _first_exported_queue_track(backend, st.slug)
    next_track = None
    if next_track_id is not None:
        if not state:
            state = StationPlaybackState(station_id=st.id, playback_backend="liquidsoap")
        state.current_track_id = next_track_id
        state.current_title = next_track_title
        state.started_at = datetime.utcnow()
        state.position_sec = 0
        next_track = (
            db.query(Track)
            .filter(Track.id == next_track_id, Track.station_id == st.id)
            .first()
        )
        db.add(state)
        db.commit()
    skip_mode = "source_skip"
    try:
        backend.skip_current(st.slug)
    except Exception:
        # Keep the station recoverable if the Liquidsoap control socket is not
        # reachable, but prefer source.skip because it advances without a full
        # config reload.
        force_liquidsoap_reload(db)
        skip_mode = "queue_reload_fallback"
    emit_event(
        db,
        service="api",
        event_type="track_skipped",
        message=f"Current track skipped: {slug}",
        station_id=st.id,
        track_id=skipped_track_id,
        details={"mode": skip_mode, "title": track.title},
    )
    return {
        "ok": True,
        "station_slug": slug,
        "track_id": skipped_track_id,
        "mode": skip_mode,
        "next_track": _track_payload(next_track, track_id=next_track_id, title=next_track_title),
    }


@router.get("/stations/{slug}/generation-preview")
async def station_generation_preview(slug: str, db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")
    return await build_station_generation_preview(db=db, station=st, settings=get_settings())


class TrackFeedbackIn(BaseModel):
    session_id: str
    vote: str
    source: str = "web"


@router.post("/stations/{slug}/tracks/{track_id}/feedback")
def station_track_feedback(slug: str, track_id: int, payload: TrackFeedbackIn, db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")
    session_id = payload.session_id.strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    if len(session_id) > 128:
        raise HTTPException(status_code=400, detail="session_id too long (max 128)")

    vote_raw = payload.vote.strip().lower()
    if vote_raw not in {"up", "down"}:
        raise HTTPException(status_code=400, detail="vote must be 'up' or 'down'")
    vote = 1 if vote_raw == "up" else -1

    track = (
        db.query(Track)
        .filter(
            Track.id == track_id,
            Track.station_id == st.id,
            Track.status.in_([TrackStatus.ready, TrackStatus.queued, TrackStatus.aired]),
        )
        .first()
    )
    if not track:
        raise HTTPException(status_code=404, detail="Track not found")

    row = (
        db.query(TrackFeedback)
        .filter(
            TrackFeedback.station_id == st.id,
            TrackFeedback.track_id == track.id,
            TrackFeedback.session_id == session_id,
        )
        .first()
    )
    if row:
        row.vote = vote
        row.source = (payload.source or "web").strip()[:40] or "web"
        row.updated_at = datetime.utcnow()
    else:
        db.add(
            TrackFeedback(
                station_id=st.id,
                track_id=track.id,
                session_id=session_id,
                vote=vote,
                source=(payload.source or "web").strip()[:40] or "web",
            )
        )
    db.commit()

    feedback = _feedback_stats_for_tracks(db, station_id=st.id, track_ids=[int(track.id)], session_id=session_id).get(
        int(track.id),
        {"likes": 0, "dislikes": 0, "score": 0, "user_vote": None},
    )
    likes = int(feedback.get("likes", 0))
    dislikes = int(feedback.get("dislikes", 0))

    promo = db.query(TrackPromotion).filter(TrackPromotion.track_id == track.id).first()
    if vote > 0:
        if not promo:
            promo = TrackPromotion(track_id=track.id)
            db.add(promo)
        promo.promoted_to_library = True
        promo.signature_track = likes >= 3 and likes > dislikes
        promo.reason = "listener_like"
        promo.promoted_at = datetime.utcnow()
        db.commit()
    elif promo and dislikes >= likes:
        promo.signature_track = False
        promo.reason = "listener_dislike"
        db.commit()

    emit_event(
        db,
        service="api",
        event_type="track_feedback_received",
        message=f"Track feedback recorded ({vote_raw})",
        station_id=st.id,
        track_id=track.id,
        details={"session_id": session_id[:64], "vote": vote_raw, "likes": likes, "dislikes": dislikes},
    )
    return {"ok": True, "station_slug": slug, "track_id": track.id, "feedback": feedback}


@router.get("/stations/{slug}/generation-payload/latest")
def station_latest_generation_payload(slug: str, db: Session = Depends(get_db)):
    st = db.query(Station).filter(Station.slug == slug).first()
    if not st:
        raise HTTPException(status_code=404, detail="Station not found")

    row = (
        db.query(TrackGeneration, Track)
        .join(Track, Track.id == TrackGeneration.track_id)
        .filter(Track.station_id == st.id)
        .order_by(TrackGeneration.created_at.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No generation payload available yet")

    gen, tr = row
    ctx = gen.recent_context if isinstance(gen.recent_context, dict) else {}
    pre = ctx.get("preprocessor", {}) if isinstance(ctx, dict) else {}
    diagnostics = pre.get("diagnostics", {}) if isinstance(pre, dict) else {}
    payload = diagnostics.get("ace_payload_snapshot") if isinstance(diagnostics, dict) else None

    return {
        "station_slug": slug,
        "track_id": tr.id,
        "track_title": tr.title,
        "generated_at": gen.created_at,
        "generator_host": gen.generator_host,
        "prompt_text": gen.prompt_text,
        "negative_prompt_text": gen.negative_prompt_text,
        "preprocessor_source": pre.get("source") if isinstance(pre, dict) else None,
        "lyrics_present": bool(pre.get("lyrics_present")) if isinstance(pre, dict) else False,
        "payload": payload,
    }


class TitleBackfillRequest(BaseModel):
    station_slugs: list[str] | None = None
    include_disabled: bool = False
    limit_per_station: int = 0


@router.post("/stations/backfill-titles")
def backfill_station_titles(payload: TitleBackfillRequest, db: Session = Depends(get_db)):
    q = db.query(Station)
    if not payload.include_disabled:
        q = q.filter(Station.is_enabled.is_(True))
    if payload.station_slugs:
        q = q.filter(Station.slug.in_(payload.station_slugs))
    stations = q.order_by(Station.name.asc()).all()
    if not stations:
        return {"ok": True, "stations": [], "total_scanned": 0, "total_updated": 0}

    engine = StationEngine()
    items = []
    total_scanned = 0
    total_updated = 0
    limit = max(0, int(payload.limit_per_station))
    for st in stations:
        result = engine.backfill_titles_for_station(db=db, station=st, limit=limit)
        total_scanned += int(result["scanned"])
        total_updated += int(result["updated"])
        items.append({"slug": st.slug, "name": st.name, **result})

    emit_event(
        db,
        service="api",
        event_type="station_titles_backfilled",
        message=f"Backfilled {total_updated} title(s) across {len(items)} station(s)",
        details={"stations": [x["slug"] for x in items], "total_scanned": total_scanned, "total_updated": total_updated},
    )
    return {"ok": True, "stations": items, "total_scanned": total_scanned, "total_updated": total_updated}


class StoragePurgeRequest(BaseModel):
    station_slug: str | None = None
    include_active: bool = False


@router.post("/admin/storage/purge")
def admin_storage_purge(payload: StoragePurgeRequest, db: Session = Depends(get_db)):
    station_id = None
    station_slug = payload.station_slug
    if station_slug:
        st = db.query(Station).filter(Station.slug == station_slug).first()
        if not st:
            raise HTTPException(status_code=404, detail="Station not found")
        station_id = st.id

    result = purge_tracks(db, station_id=station_id, include_active=bool(payload.include_active))
    emit_event(
        db,
        service="api",
        event_type="storage_cleanup_completed",
        message="Admin storage purge completed",
        station_id=station_id,
        details={"station_slug": station_slug, "include_active": bool(payload.include_active), **result},
    )
    return {"ok": True, "station_slug": station_slug, "include_active": bool(payload.include_active), **result}


class ListenerHeartbeatIn(BaseModel):
    station_slug: str
    session_id: str
    playing: bool


@router.post("/listeners/heartbeat")
def listeners_heartbeat(payload: ListenerHeartbeatIn):
    return handle_heartbeat(payload.station_slug, payload.session_id, payload.playing)


class ListenerEventIn(BaseModel):
    station_slug: str
    session_id: str
    event_type: str


@router.post("/listeners/event")
def listeners_event(payload: ListenerEventIn):
    return handle_listener_event(payload.station_slug, payload.session_id, payload.event_type)


@router.get("/stats/overview")
def stats_overview(db: Session = Depends(get_db)):
    return overview_stats(db)


@router.get("/stats/stations")
def stats_stations(db: Session = Depends(get_db)):
    return station_health(db)


@router.get("/stats/playback")
def stats_playback(db: Session = Depends(get_db)):
    return playback_stats(db)


@router.get("/stats/generation")
def stats_generation(db: Session = Depends(get_db)):
    return generation_stats(db)


@router.get("/stats/storage")
def stats_storage(db: Session = Depends(get_db)):
    return storage_stats(db)


@router.get("/stats/listeners")
def stats_listeners(db: Session = Depends(get_db)):
    return listener_stats(db)


@router.get("/stats/reuse")
def stats_reuse(db: Session = Depends(get_db)):
    return reuse_stats(db)


@router.post("/stats/generation/reset-failed-today")
def stats_generation_reset_failed_today(db: Session = Depends(get_db)):
    result = reset_failed_generations_today(db)
    emit_event(
        db,
        service="api",
        event_type="stats_snapshot_written",
        message=f"Failed generation events reset for today: {result['deleted']}",
        details=result,
    )
    return {"ok": True, **result}


@router.get("/logs", response_model=list[OpsEventOut])
def logs(
    station_id: int | None = None,
    severity: str | None = None,
    service: str | None = None,
    event_type: str | None = None,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(OpsEvent).filter(OpsEvent.timestamp >= datetime.utcnow() - timedelta(hours=hours))
    if station_id is not None:
        q = q.filter(OpsEvent.station_id == station_id)
    if severity:
        q = q.filter(OpsEvent.severity == severity)
    if service:
        q = q.filter(OpsEvent.service == service)
    if event_type:
        q = q.filter(OpsEvent.event_type == event_type)
    return q.order_by(OpsEvent.timestamp.desc()).limit(limit).all()


@router.post("/logs/snapshot")
def snapshot(db: Session = Depends(get_db)):
    emit_event(db, service="api", event_type="stats_snapshot_written", message="Manual snapshot trigger")
    return {"ok": True}
