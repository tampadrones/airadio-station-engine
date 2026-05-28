from __future__ import annotations

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    genre: Mapped[str] = mapped_column(String(80))
    personality: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    circadian_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    station_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    target_queue_depth: Mapped[int] = mapped_column(Integer, default=5)
    min_ready_tracks: Mapped[int] = mapped_column(Integer, default=3)
    hot_quota_gb: Mapped[int] = mapped_column(Integer, default=5)
    warm_quota_gb: Mapped[int] = mapped_column(Integer, default=20)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
