from datetime import datetime
from pydantic import BaseModel, Field


class StationCreate(BaseModel):
    slug: str
    name: str
    genre: str
    personality: str
    description: str
    circadian_profile: dict = {}
    station_profile: dict = {}
    target_queue_depth: int = 5
    min_ready_tracks: int = 3
    hot_quota_gb: int = 5
    warm_quota_gb: int = 20


class StationCreateFromTaste(BaseModel):
    name: str
    genre: str
    personality: str = "Custom Host"
    description: str = "User-generated custom station."
    mood: str = "baseline"
    cohesion_spectrum: int = Field(default=80, ge=0, le=100)
    discovery_depth: int = Field(default=20, ge=0, le=100)
    lyrics_mode: str = "mixed"
    clean_lyrics_only: bool = True
    genre_mode: str = "single_genre"
    target_duration_sec: int = Field(default=320, ge=150, le=320)
    duration_jitter_sec: int = Field(default=12, ge=0, le=45)
    duration_min_sec: int = Field(default=320, ge=120, le=320)
    duration_max_sec: int = Field(default=320, ge=120, le=320)
    taste_hints: list[str] = Field(default_factory=list)
    topic_ideas: list[str] = Field(default_factory=list)


class StationOut(BaseModel):
    id: int
    slug: str
    name: str
    genre: str
    personality: str
    description: str
    is_enabled: bool
    station_profile: dict
    target_queue_depth: int
    min_ready_tracks: int
    created_at: datetime

    class Config:
        from_attributes = True


class StationReprofileRequest(BaseModel):
    station_slugs: list[str] | None = None
    include_disabled: bool = False
    dry_run: bool = False
    include_inferred_taste_hints: bool = True
    preset: str | None = "cohesive_radio"
    genre_mode: str | None = None
    cohesion_spectrum: int | None = Field(default=None, ge=0, le=100)
    discovery_depth: int | None = Field(default=None, ge=0, le=100)
    lyrics_mode: str | None = None
    mood_seed: str | None = None
    clean_lyrics_only: bool | None = None
    mood_volatility: int | None = Field(default=None, ge=0, le=100)
    energy_variability: int | None = Field(default=None, ge=0, le=100)
    vocal_ratio: int | None = Field(default=None, ge=0, le=100)
    target_duration_sec: int | None = Field(default=None, ge=150, le=320)
    duration_jitter_sec: int | None = Field(default=None, ge=0, le=45)
    duration_min_sec: int | None = Field(default=None, ge=120, le=320)
    duration_max_sec: int | None = Field(default=None, ge=120, le=320)
    ace_overrides: dict | None = None
    taste_hints: list[str] | None = None
    topic_ideas: list[str] | None = None


class StationReprofileItem(BaseModel):
    slug: str
    old_profile: dict
    new_profile: dict
    changed: bool


class StationReprofileResponse(BaseModel):
    updated_count: int
    dry_run: bool
    items: list[StationReprofileItem]


class StationUpdate(BaseModel):
    name: str | None = None
    genre: str | None = None
    personality: str | None = None
    description: str | None = None
    is_enabled: bool | None = None
    target_queue_depth: int | None = Field(default=None, ge=1, le=100)
    min_ready_tracks: int | None = Field(default=None, ge=0, le=50)
    station_profile: dict | None = None

    preset: str | None = None
    genre_mode: str | None = None
    cohesion_spectrum: int | None = Field(default=None, ge=0, le=100)
    discovery_depth: int | None = Field(default=None, ge=0, le=100)
    lyrics_mode: str | None = None
    mood_seed: str | None = None
    clean_lyrics_only: bool | None = None
    mood_volatility: int | None = Field(default=None, ge=0, le=100)
    energy_variability: int | None = Field(default=None, ge=0, le=100)
    vocal_ratio: int | None = Field(default=None, ge=0, le=100)
    target_duration_sec: int | None = Field(default=None, ge=150, le=320)
    duration_jitter_sec: int | None = Field(default=None, ge=0, le=45)
    duration_min_sec: int | None = Field(default=None, ge=120, le=320)
    duration_max_sec: int | None = Field(default=None, ge=120, le=320)
    ace_overrides: dict | None = None
    taste_hints: list[str] | None = None
    topic_ideas: list[str] | None = None
