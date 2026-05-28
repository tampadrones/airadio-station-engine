from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StationDailySummary(Base):
    __tablename__ = "station_daily_summary"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    summary_date: Mapped[date] = mapped_column(Date, index=True)
    tracks_generated: Mapped[int] = mapped_column(Integer, default=0)
    tracks_aired: Mapped[int] = mapped_column(Integer, default=0)
    avg_queue_depth: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_queue_depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_generation_latency: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    avg_qc_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg_fit_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unique_listeners: Mapped[int] = mapped_column(Integer, default=0)
    peak_listeners: Mapped[int] = mapped_column(Integer, default=0)
    reuse_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    storage_used_hot: Mapped[int] = mapped_column(Integer, default=0)
    storage_used_warm: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    promotions: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
