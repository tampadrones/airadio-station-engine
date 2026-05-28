"""station profile column

Revision ID: 0004_station_profile
Revises: 0003_audio_assets
Create Date: 2026-04-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_station_profile"
down_revision: Union[str, None] = "0003_audio_assets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stations",
        sa.Column("station_profile", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.alter_column("stations", "station_profile", server_default=None)


def downgrade() -> None:
    op.drop_column("stations", "station_profile")
