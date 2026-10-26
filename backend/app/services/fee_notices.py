"""WhatsApp/SMS notices about fees: "a new fee was added" and "payment received" receipts.

(The daily overdue reminder is separate - services/fee_reminders.py.)

Three rules:
1. Never in the request path. These run as FastAPI background tasks AFTER the response is
   sent and the transaction committed, in their own DB session. A slow or failing
   WhatsApp/SMS provider can never slow down or fail a payment, and an exception here is
   logged and swallowed.
2. Paid plans only. Every notice is a paid message, so they follow the same plan feature
   as reminders ("fee_reminders", see app/plans.py). Free-plan owners get none.
3. Sent to the student and, if set, the parent - same recipients as reminders.

WhatsApp only delivers these outside the 24h window through APPROVED TEMPLATES, so each
notice names one and passes its variables in order; the SMS fallback carries the full text:
  fee_created      {{1}} student  {{2}} amount  {{3}} due date  {{4}} description or "-"
  payment_receipt  {{1}} student  {{2}} amount  {{3}} receipt no  {{4}} balance note
Until those two templates exist in Meta Business Manager, WhatsApp rejects them and the
notice falls back to SMS.
"""
import logging

from ..database import SessionLocal
from ..models import FeePayment, FeeRecord, Student
from . import fee_ledger
from . import subscriptions as subs
from .notify import notify

logger = logging.getLogger(__name__)


def receipt_no(payment: FeePayment) -> str:
    """Human-friendly receipt number derived from the payment id (nothing extra stored)."""
    return "R-" + payment.id.replace("-", "")[:10].upper()


def _rupees(paise: int) -> str:
    return f"{paise / 100:,.2f}"


def _send(db, student: Student, text: str, template: str, params: list[str]) -> None:
    owner = subs.owner_for_student(student)
    if not owner or not subs.has_feature(db, owner, "fee_reminders"):
        return
    for phone in {student.phone, student.parent_phone}:
        if phone:
            notify(phone, text, template, params)


def notify_fee_created(fee_ids: list[str]) -> None:
    """Background task: tell each student/parent a new fee was added."""
    db = SessionLocal()
    try:
        for fee_id in fee_ids:
            try:
                fee = db.query(FeeRecord).filter(FeeRecord.id == fee_id).first()
                student = fee.student if fee else None
                if not student:
                    continue
                due = fee.due_date.strftime("%d %b %Y")
                desc = fee.description or "-"
                text = (
                    f"New fee for {student.name}: Rs.{_rupees(fee_ledger.due_paise(fee))} "
                    f"due {due}" + (f" ({fee.description})" if fee.description else "") + ". "
                    "You can pay or view it in the Wandor app."
                )
                _send(db, student, text, "fee_created",
                      [student.name, _rupees(fee_ledger.due_paise(fee)), due, desc])
            except Exception:
                logger.exception("fee-created notice failed for fee %s", fee_id)
    finally:
        db.close()


def notify_payment_received(payment_id: str) -> None:
    """Background task: receipt for one paid ledger row."""
    db = SessionLocal()
    try:
        payment = db.query(FeePayment).filter(FeePayment.id == payment_id).first()
        if not payment or payment.status != "paid":
            return
        fee = payment.fee_record
        student = fee.student if fee else None
        if not student:
            return
        left = fee_ledger.remaining_paise(fee)
        balance = "Fee fully paid." if left == 0 else f"Balance due: Rs.{_rupees(left)}."
        text = (
            f"Payment received: Rs.{_rupees(payment.amount_paise)} for {student.name}"
            + (f" ({fee.description})" if fee.description else "")
            + f". Receipt {receipt_no(payment)}. {balance}"
        )
        _send(db, student, text, "payment_receipt",
              [student.name, _rupees(payment.amount_paise), receipt_no(payment), balance])
    except Exception:
        logger.exception("receipt notice failed for payment %s", payment_id)
    finally:
        db.close()
