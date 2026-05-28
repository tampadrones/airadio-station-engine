from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrackAnalysis(Base):
    __tablename__ = "track_analysis"

    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), primary_key=True)
    bpm: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    key_signature: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    energy_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brightness_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    density_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    vocal_presence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    station_fit_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    qc_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    replay_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    similarity_fingerprint: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    embedding_ref: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
