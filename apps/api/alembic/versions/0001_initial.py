"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-04-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("genre", sa.String(length=80), nullable=False),
        sa.Column("personality", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("circadian_profile", sa.JSON(), nullable=False),
        sa.Column("target_queue_depth", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("min_ready_tracks", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("hot_quota_gb", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("warm_quota_gb", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stations_slug", "stations", ["slug"], unique=True)

    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.Enum("pending", "generating", "ready", "queued", "aired", "failed", "deleted", name="trackstatus"), nullable=False),
        sa.Column("storage_class", sa.Enum("hot", "warm", "cold", "temp", "failed", name="storageclass"), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=True),
        sa.Column("audio_format", sa.String(length=20), nullable=True),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("file_path", sa.String(length=1024), nullable=True),
        sa.Column("preview_path", sa.String(length=1024), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("aired_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tracks_station_id", "tracks", ["station_id"])
    op.create_index("ix_tracks_status", "tracks", ["status"])

    op.create_table(
        "track_generation",
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), primary_key=True),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("negative_prompt_text", sa.Text(), nullable=True),
        sa.Column("generator_model", sa.String(length=120), nullable=True),
        sa.Column("generator_host", sa.String(length=255), nullable=False),
        sa.Column("generation_seconds", sa.Float(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("genre", sa.String(length=80), nullable=False),
        sa.Column("personality", sa.String(length=120), nullable=False),
        sa.Column("mood_state", sa.String(length=40), nullable=False),
        sa.Column("daypart", sa.String(length=40), nullable=False),
        sa.Column("recent_context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "track_analysis",
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), primary_key=True),
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("key_signature", sa.String(length=16), nullable=True),
        sa.Column("energy_score", sa.Float(), nullable=True),
        sa.Column("brightness_score", sa.Float(), nullable=True),
        sa.Column("density_score", sa.Float(), nullable=True),
        sa.Column("vocal_presence_score", sa.Float(), nullable=True),
        sa.Column("station_fit_score", sa.Float(), nullable=True),
        sa.Column("qc_score", sa.Float(), nullable=True),
        sa.Column("replay_score", sa.Float(), nullable=True),
        sa.Column("similarity_fingerprint", sa.String(length=256), nullable=True),
        sa.Column("embedding_ref", sa.String(length=256), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "track_play_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("played_at", sa.DateTime(), nullable=False),
        sa.Column("listeners_at_start", sa.Integer(), nullable=True),
        sa.Column("listeners_peak", sa.Integer(), nullable=True),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("skip_rate", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_track_play_events_track_id", "track_play_events", ["track_id"])
    op.create_index("ix_track_play_events_station_id", "track_play_events", ["station_id"])

    op.create_table(
        "track_promotion",
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), primary_key=True),
        sa.Column("promoted_to_library", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("signature_track", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "station_daily_summary",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column("tracks_generated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tracks_aired", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_queue_depth", sa.Float(), nullable=True),
        sa.Column("min_queue_depth", sa.Integer(), nullable=True),
        sa.Column("avg_generation_latency", sa.Float(), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_qc_score", sa.Float(), nullable=True),
        sa.Column("avg_fit_score", sa.Float(), nullable=True),
        sa.Column("unique_listeners", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("peak_listeners", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reuse_rate", sa.Float(), nullable=True),
        sa.Column("storage_used_hot", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_used_warm", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("promotions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_station_daily_summary_station_id", "station_daily_summary", ["station_id"])
    op.create_index("ix_station_daily_summary_summary_date", "station_daily_summary", ["summary_date"])

    op.create_table(
        "ops_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("service", sa.String(length=80), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.id"), nullable=True),
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=True),
        sa.Column("generation_job_id", sa.String(length=120), nullable=True),
        sa.Column("severity", sa.Enum("info", "warning", "error", name="severity"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    for idx in ["timestamp", "station_id", "track_id", "generation_job_id", "severity", "event_type"]:
        op.create_index(f"ix_ops_events_{idx}", "ops_events", [idx])


def downgrade() -> None:
    op.drop_table("ops_events")
    op.drop_table("station_daily_summary")
    op.drop_table("track_promotion")
    op.drop_table("track_play_events")
    op.drop_table("track_analysis")
    op.drop_table("track_generation")
    op.drop_table("tracks")
    op.drop_table("stations")
    op.execute("DROP TYPE IF EXISTS severity")
    op.execute("DROP TYPE IF EXISTS trackstatus")
    op.execute("DROP TYPE IF EXISTS storageclass")
