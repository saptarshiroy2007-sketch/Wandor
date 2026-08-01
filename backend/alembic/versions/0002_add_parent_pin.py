"""add parent_pin_hash to students

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28

Adds the column backing the new parent-facing read-only dashboard (parents.py /
GET /auth/parent-login). Nullable, same as students.hashed_password - null means
the parent view hasn't been activated for that student yet, same pattern as
student login itself.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("parent_pin_hash", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("students", "parent_pin_hash")
