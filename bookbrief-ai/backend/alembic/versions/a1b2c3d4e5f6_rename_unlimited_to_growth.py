"""Rename plan tier 'unlimited' → 'growth' to match updated pricing spec.

Revision ID: a1b2c3d4e5f6
Revises: 3fa370204775
Create Date: 2026-05-05 00:00:00.000000

For SQLite: since native_enum=False, the column is a VARCHAR.
We simply UPDATE any rows with plan='unlimited' to plan='growth'.

For PostgreSQL with native_enum=False (VARCHAR CHECK constraint):
The CHECK constraint references the Alembic-managed enum type name but the
values are stored as plain strings, so the same UPDATE approach applies.
No ALTER TYPE is needed because we used native_enum=False everywhere.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "3fa370204775"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Migrate any existing subscriptions that used the old 'unlimited' value.
    # Safe to run on both SQLite and PostgreSQL (no DDL needed — native_enum=False).
    op.execute(
        sa.text("UPDATE subscriptions SET plan = 'growth' WHERE plan = 'unlimited'")
    )


def downgrade() -> None:
    # Restore 'unlimited' if rolling back.
    op.execute(
        sa.text("UPDATE subscriptions SET plan = 'unlimited' WHERE plan = 'growth'")
    )
