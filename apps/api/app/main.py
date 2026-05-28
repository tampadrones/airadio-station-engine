from __future__ import annotations

import logging
from fastapi import FastAPI

from app.api.routes import router
from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import SessionLocal
from app.services.seed import ensure_seed_stations
from app.services.storage import ensure_storage_roots

configure_logging("api")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Radio API", version="0.1.0")
app.include_router(router, prefix="/api")


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    logger.info(
        "generator_config_active",
        extra={
            "event_type": "generator_config_active",
            "generator_base_url": settings.generator_base_url.rstrip("/"),
            "generator_predict_path": settings.generator_predict_path,
            "generator_timeout_seconds": int(settings.generator_timeout_seconds),
            "generator_max_retries": int(settings.generator_max_retries),
            "generator_retry_backoff_seconds": int(settings.generator_retry_backoff_seconds),
        },
    )
    ensure_storage_roots()
    db = SessionLocal()
    try:
        ensure_seed_stations(db)
    finally:
        db.close()
    logger.info("startup complete", extra={"event_type": "startup"})
