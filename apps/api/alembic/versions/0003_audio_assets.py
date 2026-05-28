"""audio assets normalization

Revision ID: 0003_audio_assets
Revises: 0002_playback_state
Create Date: 2026-04-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_audio_assets"
down_revision: Union[str, None] = "0002_playback_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audio_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("audio_format", sa.String(length=20), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_audio_assets_file_path", "audio_assets", ["file_path"], unique=True)

    op.add_column("tracks", sa.Column("audio_asset_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tracks_audio_asset_id", "tracks", "audio_assets", ["audio_asset_id"], ["id"])
    op.create_index("ix_tracks_audio_asset_id", "tracks", ["audio_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_tracks_audio_asset_id", table_name="tracks")
    op.drop_constraint("fk_tracks_audio_asset_id", "tracks", type_="foreignkey")
    op.drop_column("tracks", "audio_asset_id")
    op.drop_table("audio_assets")
