"""Flag fees that were paid twice

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-29

fee_records.duplicate_payment_id: set when a second, different Razorpay payment arrives
for a fee that's already paid (teacher recorded cash while the student's online order was
still open, or two orders raced). Surfaced to the teacher so the extra payment gets refunded.
"""
from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fee_records", sa.Column("duplicate_payment_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("fee_records", "duplicate_payment_id")
