"""track feedback for listener preferences

Revision ID: 0005_track_feedback
Revises: 0004_station_profile
Create Date: 2026-04-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_track_feedback"
down_revision: Union[str, None] = "0004_station_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "track_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("station_id", sa.Integer(), sa.ForeignKey("stations.id"), nullable=False),
        sa.Column("track_id", sa.Integer(), sa.ForeignKey("tracks.id"), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("vote", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="web"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("vote IN (-1, 1)", name="ck_track_feedback_vote"),
        sa.UniqueConstraint("station_id", "track_id", "session_id", name="uq_track_feedback_station_track_session"),
    )
    op.create_index("ix_track_feedback_station_id", "track_feedback", ["station_id"])
    op.create_index("ix_track_feedback_track_id", "track_feedback", ["track_id"])
    op.create_index("ix_track_feedback_session_id", "track_feedback", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_track_feedback_session_id", table_name="track_feedback")
    op.drop_index("ix_track_feedback_track_id", table_name="track_feedback")
    op.drop_index("ix_track_feedback_station_id", table_name="track_feedback")
    op.drop_table("track_feedback")
