"""Add progress fields to summary_videos for video job UI.

Revision ID: b2c3d4e5f6a7
Revises: e7f8a9b0c1d2
Create Date: 2026-05-08

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "summary_videos",
        sa.Column("progress_phase", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "summary_videos",
        sa.Column("progress_detail", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("summary_videos", "progress_detail")
    op.drop_column("summary_videos", "progress_phase")
