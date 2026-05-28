from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Severity


class OpsEvent(Base):
    __tablename__ = "ops_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    service: Mapped[str] = mapped_column(String(80))
    host: Mapped[str] = mapped_column(String(255))
    station_id: Mapped[Optional[int]] = mapped_column(ForeignKey("stations.id"), nullable=True, index=True)
    track_id: Mapped[Optional[int]] = mapped_column(ForeignKey("tracks.id"), nullable=True, index=True)
    generation_job_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    severity: Mapped[Severity] = mapped_column(Enum(Severity), default=Severity.info, index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
