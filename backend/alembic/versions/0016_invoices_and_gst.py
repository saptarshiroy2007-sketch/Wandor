"""Subscription invoices + per-financial-year invoice numbering

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-01

- invoices: one tax invoice per charge on a SaaS subscription. base + GST = total is a CHECK
  constraint. razorpay_payment_id is UNIQUE (idempotent issuing). invoice_number is UNIQUE.
- invoice_counters: last sequence number handed out per financial year (row-locked while a
  number is allocated, so numbers are consecutive with no gaps).

Pure additions - no existing table is altered and nothing is backfilled: charges made before
this migration have no invoice (see HANDOFF.md, Phase 4.1).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "invoice_counters",
        sa.Column("fy", sa.String(), primary_key=True),
        sa.Column("last_seq", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "invoices",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("invoice_number", sa.String(), nullable=False, unique=True),
        sa.Column("subscription_id", _uuid(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False, server_default="subscription"),
        sa.Column("plan", sa.String(), nullable=False),
        sa.Column("billing_cycle", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("base_paise", sa.Integer(), nullable=False),
        sa.Column("gst_rate_bps", sa.Integer(), nullable=False),
        sa.Column("gst_paise", sa.Integer(), nullable=False),
        sa.Column("total_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="INR"),
        sa.Column("razorpay_payment_id", sa.String(), nullable=True, unique=True),
        sa.Column("period_start", sa.DateTime(), nullable=True),
        sa.Column("period_end", sa.DateTime(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("total_paise = base_paise + gst_paise", name="ck_invoice_total"),
        sa.CheckConstraint("base_paise >= 0 AND gst_paise >= 0", name="ck_invoice_non_negative"),
    )
    op.create_index("ix_invoices_subscription_id", "invoices", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_invoices_subscription_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_table("invoice_counters")
