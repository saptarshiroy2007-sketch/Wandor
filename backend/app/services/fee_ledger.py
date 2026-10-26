"""The fee money ledger - the ONE place a fee's paid/unpaid state is allowed to change.

Every fee has a list of FeePayment rows (models.py). FeeRecord.amount_paid, is_paid,
paid_at are a cache recomputed from that list by recompute(); nothing else may set them.
That is what lets partial payments, manual payments, refunds, duplicates and the
browser-verify + webhook double-report all stay consistent:

- capture()   a Razorpay payment succeeded. Idempotent - the browser verify call and the
              webhook both land here, in either order, for the same payment.
- record_manual()  the teacher received cash/UPI/etc. and recorded it.
- apply_refund()   Razorpay reports how much of a payment has been refunded.

Money is integer paise. A fee is paid when net received >= amount due. Net received
ABOVE the amount due means money was taken that is not owed (two orders both paid, an
online payment after cash was recorded, ...): the fee's duplicate_payment_id flag is set
so the teacher sees it needs refunding, and clears itself once refunds bring the net back
down to what is owed.
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..models import FeePayment, FeeRecord

logger = logging.getLogger(__name__)

# Razorpay will not take an order below one rupee.
MIN_ONLINE_PAISE = 100


def due_paise(fee: FeeRecord) -> int:
    return int(round(fee.amount_due * 100))


def net_paid_paise(fee: FeeRecord) -> int:
    """Money actually held for this fee: paid payments minus whatever was refunded."""
    return sum(p.amount_paise - (p.refunded_paise or 0) for p in fee.payments if p.status == "paid")


def remaining_paise(fee: FeeRecord) -> int:
    return max(0, due_paise(fee) - net_paid_paise(fee))


def recompute(fee: FeeRecord) -> None:
    """Refresh the cached totals from the ledger. Call after any payment row changes."""
    net = net_paid_paise(fee)
    was_paid = bool(fee.is_paid)
    fee.amount_paid = net / 100.0
    fee.is_paid = net >= due_paise(fee)
    if fee.is_paid and not was_paid:
        fee.paid_at = datetime.utcnow()
    elif not fee.is_paid:
        fee.paid_at = None  # a refund can put a fee back to unpaid
    if net <= due_paise(fee):
        fee.duplicate_payment_id = None  # nothing left over that needs refunding


def new_pending(db: Session, fee: FeeRecord, amount_paise: int, order_id: str, paid_by: Optional[str]) -> FeePayment:
    """Ledger row for a Razorpay order that has been created but not paid yet."""
    row = FeePayment(
        fee_record_id=fee.id, amount_paise=amount_paise, mode="online", status="pending",
        razorpay_order_id=order_id, paid_by=paid_by,
    )
    db.add(row)
    fee.payments.append(row)
    fee.razorpay_order_id = order_id  # newest order, kept for older code paths
    db.flush()
    return row


def capture(db: Session, payment: FeePayment, razorpay_payment_id: Optional[str]) -> bool:
    """Apply a successful online payment. Returns True only the FIRST time (the caller
    uses that to send the receipt exactly once); a repeat report of the same payment is a
    harmless no-op."""
    if payment.status == "paid":
        return False
    fee = payment.fee_record
    before_net = net_paid_paise(fee)
    was_paid = bool(fee.is_paid)

    payment.status = "paid"
    payment.paid_at = datetime.utcnow()
    if razorpay_payment_id:
        payment.razorpay_payment_id = razorpay_payment_id
    db.flush()
    recompute(fee)

    if not was_paid:
        fee.payment_mode = "online"
        if razorpay_payment_id:
            fee.razorpay_payment_id = razorpay_payment_id
    if before_net + payment.amount_paise > due_paise(fee):
        # More money taken than is owed. Never swallowed silently - it needs a refund.
        if razorpay_payment_id:
            fee.duplicate_payment_id = razorpay_payment_id
        logger.error("DUPLICATE_FEE_PAYMENT fee=%s payment=%s - needs a refund", fee.id, razorpay_payment_id)
    return True


def record_manual(db: Session, fee: FeeRecord, amount_paise: int) -> FeePayment:
    """The teacher received `amount_paise` outside the app. Callers validate the amount."""
    row = FeePayment(
        fee_record_id=fee.id, amount_paise=amount_paise, mode="manual", status="paid",
        paid_by="teacher", paid_at=datetime.utcnow(),
    )
    db.add(row)
    fee.payments.append(row)
    db.flush()
    recompute(fee)
    fee.payment_mode = "manual"
    return row


def apply_refund(db: Session, payment: FeePayment, refunded_total_paise: int) -> None:
    """Set how much of this payment has been refunded in total (Razorpay's cumulative
    figure, so replays and several partial refunds all converge on the same answer)."""
    payment.refunded_paise = max(0, min(int(refunded_total_paise), payment.amount_paise))
    db.flush()
    recompute(payment.fee_record)


def display_status(payment: FeePayment) -> str:
    if (payment.refunded_paise or 0) >= payment.amount_paise > 0:
        return "refunded"
    if (payment.refunded_paise or 0) > 0:
        return "partially_refunded"
    return payment.status
