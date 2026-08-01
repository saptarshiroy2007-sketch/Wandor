"""add last_reminder_sent_at to fee_records

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31

Backs the new daily fee-reminder scheduler (app/services/fee_reminders.py). Nullable -
null means no reminder has ever been sent for this fee record. Set to the send
timestamp each time the job notifies for this record, so the job never spams the
same unpaid fee more than once per calendar day.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fee_records", sa.Column("last_reminder_sent_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column("fee_records", "last_reminder_sent_at")
