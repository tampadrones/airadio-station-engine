from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default="sqlite+pysqlite:///./airadio.db", alias="DATABASE_URL")
    async_database_url: str = Field(default="sqlite+aiosqlite:///./airadio.db", alias="ASYNC_DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    generator_base_url: str = Field(default="http://10.0.0.5:7860", alias="GENERATOR_BASE_URL")
    generator_predict_path: str = Field(default="/gradio_api/call/generation_wrapper", alias="GENERATOR_PREDICT_PATH")
    generator_timeout_seconds: int = Field(default=180, alias="GENERATOR_TIMEOUT_SECONDS")
    generator_safe_max_duration_sec: int = Field(default=180, alias="GENERATOR_SAFE_MAX_DURATION_SEC")
    generation_max_wall_clock_seconds: int = Field(default=300, alias="GENERATION_MAX_WALL_CLOCK_SECONDS")
    generator_max_retries: int = Field(default=3, alias="GENERATOR_MAX_RETRIES")
    generator_retry_backoff_seconds: int = Field(default=2, alias="GENERATOR_RETRY_BACKOFF_SECONDS")
    generator_max_concurrent_jobs: int = Field(default=5, alias="GENERATOR_MAX_CONCURRENT_JOBS")
    ace_step_export_enabled: bool = Field(default=False, alias="ACE_STEP_EXPORT_ENABLED")
    ace_step_export_dir: str = Field(default="", alias="ACE_STEP_EXPORT_DIR")
    prompt_refiner_base_urls: str = Field(default="", alias="PROMPT_REFINER_BASE_URLS")
    prompt_refiner_model: str = Field(default="", alias="PROMPT_REFINER_MODEL")
    prompt_refiner_timeout_seconds: int = Field(default=20, alias="PROMPT_REFINER_TIMEOUT_SECONDS")
    prompt_refiner_api_key: str = Field(default="", alias="PROMPT_REFINER_API_KEY")
    lyrics_refiner_base_urls: str = Field(default="", alias="LYRICS_REFINER_BASE_URLS")
    lyrics_refiner_model: str = Field(default="", alias="LYRICS_REFINER_MODEL")
    lyrics_refiner_timeout_seconds: int = Field(default=45, alias="LYRICS_REFINER_TIMEOUT_SECONDS")
    lyrics_refiner_api_key: str = Field(default="", alias="LYRICS_REFINER_API_KEY")
    lyrics_refiner_auth_email: str = Field(default="", alias="LYRICS_REFINER_AUTH_EMAIL")
    lyrics_refiner_auth_password: str = Field(default="", alias="LYRICS_REFINER_AUTH_PASSWORD")
    lyrics_refiner_temperature: float = Field(default=0.9, alias="LYRICS_REFINER_TEMPERATURE")
    prompt_force_ascii_english: bool = Field(default=True, alias="PROMPT_FORCE_ASCII_ENGLISH")
    station_min_fit_score: float = Field(default=0.55, alias="STATION_MIN_FIT_SCORE")
    station_min_qc_score: float = Field(default=0.45, alias="STATION_MIN_QC_SCORE")

    hot_storage_root: str = Field(default="/var/lib/ai-radio/hot", alias="HOT_STORAGE_ROOT")
    warm_storage_root: str = Field(default="/var/lib/ai-radio/warm", alias="WARM_STORAGE_ROOT")
    cold_storage_root: str = Field(default="/var/lib/ai-radio/cold", alias="COLD_STORAGE_ROOT")
    temp_storage_root: str = Field(default="/var/lib/ai-radio/temp", alias="TEMP_STORAGE_ROOT")
    failed_storage_root: str = Field(default="/var/lib/ai-radio/failed", alias="FAILED_STORAGE_ROOT")
    hls_root: str = Field(default="/var/lib/ai-radio/hls", alias="HLS_ROOT")
    hls_public_base_url: str = Field(default="http://localhost/hls", alias="HLS_PUBLIC_BASE_URL")
    playback_root: str = Field(default="/var/lib/ai-radio/playback", alias="PLAYBACK_ROOT")
    playback_backend: str = Field(default="liquidsoap", alias="PLAYBACK_BACKEND")
    liquidsoap_control_host: str = Field(default="liquidsoap", alias="LIQUIDSOAP_CONTROL_HOST")
    liquidsoap_control_port: int = Field(default=1234, alias="LIQUIDSOAP_CONTROL_PORT")
    liquidsoap_control_socket_path: str = Field(
        default="/var/lib/ai-radio/playback/liquidsoap.sock",
        alias="LIQUIDSOAP_CONTROL_SOCKET_PATH",
    )

    enable_structured_logging: bool = Field(default=True, alias="ENABLE_STRUCTURED_LOGGING")
    station_default_target_queue_depth: int = Field(default=5, alias="STATION_DEFAULT_TARGET_QUEUE_DEPTH")
    station_default_min_ready_tracks: int = Field(default=3, alias="STATION_DEFAULT_MIN_READY_TRACKS")
    station_hot_quota_gb: int = Field(default=5, alias="STATION_HOT_QUOTA_GB")
    station_warm_quota_gb: int = Field(default=20, alias="STATION_WARM_QUOTA_GB")
    station_cold_preview_quota_gb: int = Field(default=2, alias="STATION_COLD_PREVIEW_QUOTA_GB")
    station_refill_max_generations_per_cycle: int = Field(default=2, alias="STATION_REFILL_MAX_GENERATIONS_PER_CYCLE")
    station_idle_grace_minutes: int = Field(default=10, alias="STATION_IDLE_GRACE_MINUTES")
    station_idle_min_ready_tracks: int = Field(default=1, alias="STATION_IDLE_MIN_READY_TRACKS")
    station_activation_refill_minutes: int = Field(default=20, alias="STATION_ACTIVATION_REFILL_MINUTES")
    generated_storage_cap_gb: int = Field(default=10, alias="GENERATED_STORAGE_CAP_GB")
    include_ace_step_export_in_cap: bool = Field(default=True, alias="INCLUDE_ACE_STEP_EXPORT_IN_CAP")
    storage_cleanup_interval_seconds: int = Field(default=300, alias="STORAGE_CLEANUP_INTERVAL_SECONDS")
    generation_storage_format: str = Field(default="wav", alias="GENERATION_STORAGE_FORMAT")
    generation_mp3_bitrate_kbps: int = Field(default=192, alias="GENERATION_MP3_BITRATE_KBPS")
    generation_mp3_sample_rate: int = Field(default=44100, alias="GENERATION_MP3_SAMPLE_RATE")

    hot_retention_hours: int = Field(default=48, alias="HOT_RETENTION_HOURS")
    warm_retention_days: int = Field(default=120, alias="WARM_RETENTION_DAYS")
    preview_retention_days: int = Field(default=90, alias="PREVIEW_RETENTION_DAYS")

    worker_tick_seconds: int = Field(default=10, alias="WORKER_TICK_SECONDS")
    generation_stale_track_minutes: int = Field(default=5, alias="GENERATION_STALE_TRACK_MINUTES")
    generation_startup_stale_track_minutes: int = Field(default=5, alias="GENERATION_STARTUP_STALE_TRACK_MINUTES")
    timezone: str = Field(default="America/New_York", alias="TIMEZONE")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
