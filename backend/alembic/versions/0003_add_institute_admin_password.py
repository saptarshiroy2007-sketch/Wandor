"""add hashed_password to institutes

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29

Adds the column backing the new institute-admin login/dashboard (routers/institute.py /
POST /auth/institute-login). Nullable, same pattern as students.hashed_password and
students.parent_pin_hash - null means the owner's login hasn't been activated yet.
See backend/scripts/set_institute_password.py to bootstrap the first password, since
there's no institute self-signup flow yet to set it through.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("institutes", sa.Column("hashed_password", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("institutes", "hashed_password")
