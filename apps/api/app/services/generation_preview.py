from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models.station import Station
from app.models.track import Track
from app.models.track_analysis import TrackAnalysis
from app.services.anti_repetition import anti_repetition_notes
from app.services.daypart import get_daypart_blend
from app.services.prompt_builder import build_negative_prompt, build_prompt
from app.services.prompt_preprocessor import preprocess_generation
from app.services.station_engine import StationEngine
from app.services.station_profile import normalize_station_profile


async def build_station_generation_preview(db: Session, station: Station, settings: Settings) -> dict[str, Any]:
    now = datetime.utcnow()
    blend = get_daypart_blend(now, settings.timezone)
    profile = normalize_station_profile(station.station_profile or {})
    mood = str(profile.get("mood_seed", "baseline"))

    recent = (
        db.query(Track, TrackAnalysis)
        .outerjoin(TrackAnalysis, Track.id == TrackAnalysis.track_id)
        .filter(Track.station_id == station.id)
        .order_by(Track.created_at.desc())
        .limit(3)
        .all()
    )

    recent_ctx: list[dict[str, Any]] = []
    for tr, analysis in recent:
        item: dict[str, Any] = {"title": tr.title}
        if analysis:
            item.update(
                {
                    "bpm": analysis.bpm,
                    "energy_score": analysis.energy_score,
                    "tags": list((analysis.tags or {}).keys()),
                }
            )
        recent_ctx.append(item)

    anti = anti_repetition_notes(
        recent_ctx,
        cohesion_spectrum=int(profile.get("cohesion_spectrum", 80)),
        discovery_depth=int(profile.get("discovery_depth", 20)),
    )

    base_prompt = build_prompt(
        genre=station.genre,
        personality=station.personality,
        daypart=blend.daypart,
        daypart_bias=blend.prompt_bias,
        mood=mood,
        recent_tracks=recent_ctx,
        anti_repetition_notes=anti,
        station_profile=profile,
    )
    base_negative_prompt = build_negative_prompt(genre=station.genre, station_profile=profile)

    preprocessed = await preprocess_generation(
        settings=settings,
        station_name=station.name,
        station_description=station.description,
        genre=station.genre,
        personality=station.personality,
        daypart=blend.daypart,
        mood=mood,
        station_profile=profile,
        base_prompt=base_prompt,
        negative_prompt=base_negative_prompt,
        recent_tracks=recent_ctx,
    )
    song_topic = str((preprocessed.diagnostics or {}).get("song_topic", "")).strip() or mood
    engine = StationEngine()
    target_duration_sec = engine._resolve_target_duration_sec(
        genre=station.genre,
        daypart=blend.daypart,
        mood=mood,
        station_profile=profile,
        lyrics_present=bool(preprocessed.lyrics),
        topic=song_topic,
    )
    ace_params = engine._build_ace_params(
        genre=station.genre,
        daypart=blend.daypart,
        mood=mood,
        station_profile=profile,
        lyrics_present=bool(preprocessed.lyrics),
        topic=song_topic,
        duration_sec=target_duration_sec,
    )

    payload = {
        "prompt": preprocessed.prompt,
        "negative_prompt": preprocessed.negative_prompt,
        "lyrics": preprocessed.lyrics or "",
        "music_caption": preprocessed.music_caption,
        "technical_parameters": preprocessed.technical_parameters or {},
        "duration_sec": int(target_duration_sec),
        "task_type": "lyrics2music" if preprocessed.lyrics else "text2music",
        "ace_params": ace_params,
    }

    return {
        "station_slug": station.slug,
        "generated_at": now.isoformat(),
        "daypart": blend.daypart,
        "mood": mood,
        "preprocessor": {
            "source": preprocessed.source,
            "diagnostics": preprocessed.diagnostics,
        },
        "base": {
            "prompt": base_prompt,
            "negative_prompt": base_negative_prompt,
        },
        "final": {
            "prompt": preprocessed.prompt,
            "music_caption": preprocessed.music_caption,
            "technical_parameters": preprocessed.technical_parameters or {},
            "negative_prompt": preprocessed.negative_prompt,
            "lyrics": preprocessed.lyrics,
        },
        "generator_payload": payload,
    }
