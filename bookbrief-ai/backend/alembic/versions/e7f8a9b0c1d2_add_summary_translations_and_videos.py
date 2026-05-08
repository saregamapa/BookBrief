"""Add summary_translations and summary_videos tables.

Revision ID: e7f8a9b0c1d2
Revises: c3d4e5f6a7b8
Create Date: 2026-05-07

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "summary_translations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("summary_id", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=32), nullable=False),
        sa.Column("translated_markdown", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["summary_id"], ["book_summaries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_id", "locale", name="uq_summary_translation_locale"),
    )
    op.create_index(
        op.f("ix_summary_translations_summary_id"),
        "summary_translations",
        ["summary_id"],
        unique=False,
    )

    op.create_table(
        "summary_videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("summary_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="videojobstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("video_url", sa.Text(), nullable=True),
        sa.Column("subtitle_vtt", sa.Text(), nullable=True),
        sa.Column("poster_url", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["summary_id"], ["book_summaries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_id", name="uq_summary_videos_summary_id"),
    )


def downgrade() -> None:
    op.drop_table("summary_videos")
    op.drop_index(op.f("ix_summary_translations_summary_id"), table_name="summary_translations")
    op.drop_table("summary_translations")
