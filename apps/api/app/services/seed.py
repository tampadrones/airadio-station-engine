from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.settings import get_settings
from app.models.station import Station
from app.services.station_profile import normalize_station_profile


DEFAULT_STATIONS = [
    {
        "slug": "synthwave-fm",
        "name": "Synthwave FM",
        "genre": "Synthwave",
        "personality": "Velvet Static",
        "description": "Neon dusk cruiselanes and cinematic retro pulse.",
        "circadian_profile": {"late_night": 0.8, "morning": 0.5, "midday": 0.6, "evening": 1.0},
    },
    {
        "slug": "trap-afterhours",
        "name": "Trap Afterhours",
        "genre": "Trap",
        "personality": "Riot Bloom",
        "description": "Dark kinetic rhythm, hooks, and bass pressure.",
        "circadian_profile": {"late_night": 1.0, "morning": 0.4, "midday": 0.7, "evening": 0.9},
    },
    {
        "slug": "lofi-desk",
        "name": "Lo-Fi Desk",
        "genre": "Lo-Fi",
        "personality": "Dustline Dan",
        "description": "Warm tape texture and productive focus drift.",
        "circadian_profile": {"late_night": 0.9, "morning": 0.8, "midday": 0.9, "evening": 0.7},
    },
]


def ensure_seed_stations(db: Session) -> None:
    s = get_settings()
    for item in DEFAULT_STATIONS:
        exists = db.query(Station).filter(Station.slug == item["slug"]).first()
        if exists:
            if not exists.station_profile:
                exists.station_profile = normalize_station_profile({"preset": "cohesive_radio"})
                db.add(exists)
            continue
        db.add(
            Station(
                slug=item["slug"],
                name=item["name"],
                genre=item["genre"],
                personality=item["personality"],
                description=item["description"],
                circadian_profile=item["circadian_profile"],
                station_profile=normalize_station_profile({"preset": "cohesive_radio"}),
                target_queue_depth=s.station_default_target_queue_depth,
                min_ready_tracks=s.station_default_min_ready_tracks,
                hot_quota_gb=s.station_hot_quota_gb,
                warm_quota_gb=s.station_warm_quota_gb,
            )
        )
    db.commit()
