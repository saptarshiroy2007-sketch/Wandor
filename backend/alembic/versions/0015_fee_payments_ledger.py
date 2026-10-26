"""Fee payment ledger (partial payments, receipts, refunds)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-01

- fee_payments: one row per payment / payment attempt against a fee. FeeRecord.amount_paid
  and is_paid become a cache of this ledger (see services/fee_ledger.py).
- fee_records.allow_partial: whether payers may pay a fee in instalments. Existing fees
  default to FALSE (must be paid in full, exactly as before).

Backfill: every existing fee with money received gets ONE 'paid' ledger row for its
amount_paid, so the ledger and the cached totals agree from the first request after this
runs. mode/ids are copied from the fee. A fee already flagged duplicate_payment_id keeps
that flag but gets no ledger row for the extra payment (its amount was never recorded);
the flag clears itself when Razorpay reports that payment refunded.
"""
from datetime import datetime
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "fee_payments",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("fee_record_id", _uuid(), sa.ForeignKey("fee_records.id"), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("refunded_paise", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("razorpay_order_id", sa.String(), nullable=True),
        sa.Column("razorpay_payment_id", sa.String(), nullable=True, unique=True),
        sa.Column("paid_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_fee_payments_fee_record_id", "fee_payments", ["fee_record_id"])
    op.create_index("ix_fee_payments_razorpay_order_id", "fee_payments", ["razorpay_order_id"])

    op.add_column("fee_records", sa.Column("allow_partial", sa.Boolean(), nullable=False, server_default=sa.false()))

    # ---- backfill: one paid ledger row per fee that has received money ----
    conn = op.get_bind()
    fees = sa.table(
        "fee_records",
        sa.column("id"), sa.column("amount_paid"), sa.column("payment_mode"),
        sa.column("razorpay_order_id"), sa.column("razorpay_payment_id"),
        sa.column("paid_at"), sa.column("created_at"),
    )
    payments = sa.table(
        "fee_payments",
        sa.column("id"), sa.column("fee_record_id"), sa.column("amount_paise"),
        sa.column("refunded_paise"), sa.column("mode"), sa.column("status"),
        sa.column("razorpay_order_id"), sa.column("razorpay_payment_id"),
        sa.column("created_at"), sa.column("paid_at"),
    )
    rows = conn.execute(
        sa.select(
            fees.c.id, fees.c.amount_paid, fees.c.payment_mode, fees.c.razorpay_order_id,
            fees.c.razorpay_payment_id, fees.c.paid_at, fees.c.created_at,
        ).where(fees.c.amount_paid > 0)
    ).fetchall()
    now = datetime.utcnow()
    out = []
    for fee_id, amount_paid, mode, order_id, pay_id, paid_at, created_at in rows:
        online = (mode == "online") or (mode is None and pay_id is not None)
        out.append({
            "id": str(uuid.uuid4()),
            "fee_record_id": fee_id,
            "amount_paise": int(round(float(amount_paid) * 100)),
            "refunded_paise": 0,
            "mode": "online" if online else "manual",
            "status": "paid",
            "razorpay_order_id": order_id if online else None,
            "razorpay_payment_id": pay_id if online else None,
            "created_at": paid_at or created_at or now,
            "paid_at": paid_at or created_at or now,
        })
    if out:
        op.bulk_insert(payments, out)


def downgrade() -> None:
    op.drop_column("fee_records", "allow_partial")
    op.drop_index("ix_fee_payments_razorpay_order_id", table_name="fee_payments")
    op.drop_index("ix_fee_payments_fee_record_id", table_name="fee_payments")
    op.drop_table("fee_payments")
