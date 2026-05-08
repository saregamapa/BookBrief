"""Add audio_tts_jobs for multi-worker TTS polling.

Revision ID: d3e4f5a6b7c8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-08

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audio_tts_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("audio_blob", sa.LargeBinary(), nullable=True),
        sa.Column("media_type", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_audio_tts_jobs_job_id"),
    )
    op.create_index(op.f("ix_audio_tts_jobs_job_id"), "audio_tts_jobs", ["job_id"], unique=False)
    op.create_index(op.f("ix_audio_tts_jobs_user_id"), "audio_tts_jobs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audio_tts_jobs_user_id"), table_name="audio_tts_jobs")
    op.drop_index(op.f("ix_audio_tts_jobs_job_id"), table_name="audio_tts_jobs")
    op.drop_table("audio_tts_jobs")
