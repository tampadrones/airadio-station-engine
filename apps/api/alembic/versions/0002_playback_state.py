"""station playback state

Revision ID: 0002_playback_state
Revises: 0001_initial
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_playback_state"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "station_playback_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("playback_backend", sa.String(length=40), nullable=False, server_default="liquidsoap"),
        sa.Column("current_track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=True),
        sa.Column("current_title", sa.String(length=200), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("position_sec", sa.Integer(), nullable=True),
        sa.Column("fallback_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("manifest_path", sa.String(length=1024), nullable=True),
        sa.Column("manifest_age_seconds", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_station_playback_state_station_id", "station_playback_state", ["station_id"], unique=True)
    op.create_index("ix_station_playback_state_current_track_id", "station_playback_state", ["current_track_id"])


def downgrade() -> None:
    op.drop_table("station_playback_state")
