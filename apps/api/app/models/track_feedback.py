from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TrackFeedback(Base):
    __tablename__ = "track_feedback"
    __table_args__ = (
        UniqueConstraint("station_id", "track_id", "session_id", name="uq_track_feedback_station_track_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("tracks.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    vote: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(40), default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
