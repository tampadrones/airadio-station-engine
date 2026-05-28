from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrackGeneration(Base):
    __tablename__ = "track_generation"

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), primary_key=True)
    prompt_text: Mapped[str] = mapped_column(Text)
    negative_prompt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generator_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    generator_host: Mapped[str] = mapped_column(String(255))
    generation_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    genre: Mapped[str] = mapped_column(String(80))
    personality: Mapped[str] = mapped_column(String(120))
    mood_state: Mapped[str] = mapped_column(String(40))
    daypart: Mapped[str] = mapped_column(String(40))
    recent_context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
