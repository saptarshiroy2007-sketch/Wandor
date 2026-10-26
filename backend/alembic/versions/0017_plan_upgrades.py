"""Upgrade-now with proration: one row per upgrade attempt

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-02

- plan_upgrades: the prorated one-off payment (a Razorpay Order) that moves an owner to a higher
  plan immediately. razorpay_order_id and razorpay_payment_id are UNIQUE, which is what makes
  applying an upgrade idempotent. total = base + GST is a CHECK constraint, like invoices.

Pure addition - no existing table is altered and nothing is backfilled.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "plan_upgrades",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("subscription_id", _uuid(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("razorpay_order_id", sa.String(), nullable=False, unique=True),
        sa.Column("razorpay_payment_id", sa.String(), nullable=True, unique=True),
        sa.Column("from_plan", sa.String(), nullable=False),
        sa.Column("to_plan", sa.String(), nullable=False),
        sa.Column("billing_cycle", sa.String(), nullable=False),
        sa.Column("base_paise", sa.Integer(), nullable=False),
        sa.Column("gst_paise", sa.Integer(), nullable=False),
        sa.Column("total_paise", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("renewal", sa.String(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("total_paise = base_paise + gst_paise", name="ck_plan_upgrade_total"),
        sa.CheckConstraint("base_paise >= 0 AND gst_paise >= 0", name="ck_plan_upgrade_non_negative"),
    )
    op.create_index("ix_plan_upgrades_subscription_id", "plan_upgrades", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_upgrades_subscription_id", table_name="plan_upgrades")
    op.drop_table("plan_upgrades")
