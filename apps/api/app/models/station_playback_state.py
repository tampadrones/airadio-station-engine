from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StationPlaybackState(Base):
    __tablename__ = "station_playback_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True, unique=True)
    playback_backend: Mapped[str] = mapped_column(String(40), default="liquidsoap")
    current_track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tracks.id"), nullable=True, index=True)
    current_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    position_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fallback_active: Mapped[bool] = mapped_column(Boolean, default=False)
    manifest_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    manifest_age_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
