from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import StorageClass, TrackStatus


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audio_asset_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audio_assets.id"), nullable=True, index=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[TrackStatus] = mapped_column(Enum(TrackStatus), default=TrackStatus.pending, index=True)
    storage_class: Mapped[StorageClass] = mapped_column(Enum(StorageClass), default=StorageClass.temp)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    audio_format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    bitrate_kbps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    channels: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    preview_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    aired_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
