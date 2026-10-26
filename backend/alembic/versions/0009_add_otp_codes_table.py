"""add otp_codes table (password reset via WhatsApp/SMS OTP)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15

Backs POST /auth/password-reset/request and /confirm. There was previously NO
password recovery path at all in the app - a teacher, student, or institute admin
who forgot their password had no way back in except someone with direct DB access
resetting it by hand. This is the fix.

code_hash stores the OTP hashed (via the same hash_password() as real account
passwords) - the raw 6-digit code only ever exists in memory and in the outbound
WhatsApp/SMS message, never at rest in the DB.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("role", sa.String, nullable=False),
        sa.Column("phone", sa.String, nullable=False),
        sa.Column("institute_id", sa.String, nullable=True),
        sa.Column("code_hash", sa.String, nullable=False),
        sa.Column("purpose", sa.String, nullable=False, server_default="password_reset"),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("consumed_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_otp_codes_phone", "otp_codes", ["phone"])


def downgrade() -> None:
    op.drop_index("ix_otp_codes_phone", table_name="otp_codes")
    op.drop_table("otp_codes")
