"""add phone_verified to teachers and institutes (signup-time OTP verification)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-20

Backs POST /auth/teacher-signup/verify and /auth/institute-signup/verify - the OTP
recovery flow (migration 0009) proved you own a phone number when you'd LOST access
to your account; this proves it when you're CREATING one, so a self-signup can't
just type in someone else's number.

Only self-signup (POST /auth/teacher-signup, POST /auth/institute-signup) sets this
False. Every other path that creates a Teacher/Institute row - an institute admin
adding a teacher, an already-existing account - defaults True: server_default='1'
backfills every pre-existing row so nobody who signed up before this feature existed
gets locked out of login by it.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teachers", sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default="1"))
    op.add_column("institutes", sa.Column("phone_verified", sa.Boolean(), nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("institutes", "phone_verified")
    op.drop_column("teachers", "phone_verified")
