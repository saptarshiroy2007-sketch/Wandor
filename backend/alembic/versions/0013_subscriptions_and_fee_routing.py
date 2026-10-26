"""Subscriptions (SaaS billing), webhook idempotency, and Route payout accounts

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-29

- subscriptions: what an institute OR an independent teacher pays the platform.
  Exactly one of institute_id / teacher_id is set (CHECK constraint). No row = free plan.
- webhook_events: processed Razorpay event ids, so redelivered webhooks are no-ops.
- institutes.razorpay_account_id / teachers.razorpay_account_id: Razorpay Route linked
  account that student fee payments are transferred to.
- fee_records.description / payment_mode / created_at.

Pre-existing institutes/teachers get no subscription row and are therefore on the free
plan. The plan limits only block ADDING new students/teachers - anything already over a
limit is left alone.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def _uuid():
    # Same column type every earlier migration/model uses - plain UUID strings.
    return postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("institute_id", _uuid(), sa.ForeignKey("institutes.id"), nullable=True),
        sa.Column("teacher_id", _uuid(), sa.ForeignKey("teachers.id"), nullable=True),
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
        sa.Column("billing_cycle", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("razorpay_subscription_id", sa.String(), nullable=True, unique=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scheduled_plan", sa.String(), nullable=True),
        sa.Column("scheduled_cycle", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("(institute_id IS NULL) <> (teacher_id IS NULL)", name="ck_subscription_one_owner"),
        sa.UniqueConstraint("institute_id", name="uq_subscription_institute"),
        sa.UniqueConstraint("teacher_id", name="uq_subscription_teacher"),
    )

    op.create_table(
        "webhook_events",
        sa.Column("event_id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=True),
    )

    op.add_column("institutes", sa.Column("razorpay_account_id", sa.String(), nullable=True))
    op.add_column("teachers", sa.Column("razorpay_account_id", sa.String(), nullable=True))

    op.add_column("fee_records", sa.Column("description", sa.String(), nullable=True))
    op.add_column("fee_records", sa.Column("payment_mode", sa.String(), nullable=True))
    op.add_column("fee_records", sa.Column("created_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("fee_records", "created_at")
    op.drop_column("fee_records", "payment_mode")
    op.drop_column("fee_records", "description")
    op.drop_column("teachers", "razorpay_account_id")
    op.drop_column("institutes", "razorpay_account_id")
    op.drop_table("webhook_events")
    op.drop_table("subscriptions")
