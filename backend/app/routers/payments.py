"""Student fee payments - money that goes from a student to THEIR institute / teacher.

(The SaaS subscription institutes pay the platform is a separate flow - see
routers/billing.py. Both share the one Razorpay webhook URL defined at the bottom of
this file, since Razorpay allows a single webhook endpoint per account.)

How fee money reaches the right person: each institute (or independent teacher) has a
Razorpay Route "linked account" (Institute/Teacher.razorpay_account_id). Orders are
created with a `transfers` entry pointing at that account, so when the student pays,
Razorpay settles the fee straight to them minus the platform commission
(settings.fee_platform_commission_bps). Without a linked account, online payment is
simply unavailable and the teacher records cash/UPI payments by hand - money is never
silently routed to the platform's own account.

Every payment, partial payment, manual payment and refund is a row in the FeePayment
ledger, and a fee's paid/unpaid state is only ever changed through services/fee_ledger.py.
"""
import hashlib
import hmac
import logging
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import get_current_teacher, get_current_student
from ..database import get_db, settings
from ..ratelimit import rate_limit
from ..models import FeePayment, FeeRecord, Teacher, Student, Batch, Institute, WebhookEvent
from ..schemas import (
    CreateOrderRequest, FeeRecordOut, FeeRecordDetail, FeeCreate, FeeCreateResult,
    MyFee, MyFeesOut, VerifyFeePayment, PayoutStatus, PaymentOut, ReceiptOut, ManualPaymentRequest,
)
from ..scoping import owner_scope
from ..services import fee_ledger, fee_notices, invoices, upgrades
from ..services import subscriptions as subs
from ..services.fee_reminders import send_due_fee_reminders
from ..services.razorpay_client import get_razorpay_client, razorpay_configured, require_razorpay  # noqa: F401 - re-exported, older imports used payments.get_razorpay_client

router = APIRouter(prefix="/payments", tags=["payments"])
logger = logging.getLogger(__name__)

ONLINE_UNAVAILABLE_FOR_STUDENT = "Online payment isn't available for your institute yet. Please pay your teacher directly."


# ---------- helpers ----------
def _payment_out(p: FeePayment) -> PaymentOut:
    return PaymentOut(
        id=p.id, amount=p.amount_paise / 100.0, refunded_amount=(p.refunded_paise or 0) / 100.0,
        status=fee_ledger.display_status(p), mode=p.mode, paid_by=p.paid_by, paid_at=p.paid_at,
        receipt_no=fee_notices.receipt_no(p),
    )


def _payments_out(f: FeeRecord) -> list[PaymentOut]:
    return [_payment_out(p) for p in f.payments if p.status == "paid"]


def _detail(f: FeeRecord) -> FeeRecordDetail:
    s = f.student
    return FeeRecordDetail(
        id=f.id, student_id=f.student_id, student_name=s.name if s else "",
        batch_name=s.batch.name if s and s.batch else None,
        amount_due=f.amount_due, amount_paid=f.amount_paid or 0.0, is_paid=bool(f.is_paid),
        due_date=f.due_date, paid_at=f.paid_at, description=f.description,
        payment_mode=f.payment_mode, duplicate_payment=bool(f.duplicate_payment_id),
        allow_partial=bool(f.allow_partial), payments=_payments_out(f),
    )


def _my_fee(f: FeeRecord) -> MyFee:
    return MyFee(
        id=f.id, amount_due=f.amount_due, amount_paid=f.amount_paid or 0.0,
        is_paid=bool(f.is_paid), due_date=f.due_date, paid_at=f.paid_at,
        description=f.description, payment_mode=f.payment_mode,
        allow_partial=bool(f.allow_partial), payments=_payments_out(f),
    )


def _scoped_fee(db: Session, teacher: Teacher, fee_id: str) -> FeeRecord:
    fee = (
        db.query(FeeRecord).join(FeeRecord.student)
        .filter(FeeRecord.id == fee_id, owner_scope(Student, teacher))
        .first()
    )
    if not fee:
        raise HTTPException(status_code=404, detail="Fee record not found")
    return fee


def _payout_account_id(db: Session, owner: subs.Owner) -> Optional[str]:
    """Route linked account the owner's student fees settle to (None = not set up)."""
    if owner.institute_id:
        row = db.query(Institute.razorpay_account_id).filter(Institute.id == owner.institute_id).first()
    else:
        row = db.query(Teacher.razorpay_account_id).filter(Teacher.id == owner.teacher_id).first()
    return (row[0] if row else None) or None


def _payment_for_order(db: Session, order_id: Optional[str]) -> Optional[FeePayment]:
    """The ledger row for a Razorpay order (locked for update on Postgres so the browser
    verify call and the webhook can't both apply it at once). Every order we create has a
    row. For one that doesn't (made before the ledger existed), fall back to the order's
    `receipt`, which create_order always set to the fee id, and make the row now."""
    if not order_id:
        return None
    row = (
        db.query(FeePayment).filter(FeePayment.razorpay_order_id == order_id)
        .with_for_update().first()
    )
    if row:
        return row
    try:
        order = get_razorpay_client().order.fetch(order_id)
        fee_id = str(uuid.UUID(str(order.get("receipt"))))  # receipts of other orders may not be UUIDs
        paise = int(order["amount"])
    except Exception:
        return None
    fee = db.query(FeeRecord).filter(FeeRecord.id == fee_id).first()
    if fee is None:
        # e.g. the teacher deleted the fee while the student's order was still open
        logger.error("ORPHAN_FEE_PAYMENT order=%s receipt=%s - money taken, no fee record", order_id, fee_id)
        return None
    return fee_ledger.new_pending(db, fee, paise, order_id, None)


# ---------- Teacher: manage fees ----------
@router.get("/due", response_model=list[FeeRecordOut])
def list_due_fees(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Unpaid fees only, scoped to this teacher's own data (owner_scope handles both the
    institute-shared case and the independent-teacher-private case - see
    app/scoping.py). Kept for older callers; the fee tracker page uses /records."""
    return (
        db.query(FeeRecord).join(FeeRecord.student)
        .filter(owner_scope(Student, teacher))
        .filter(FeeRecord.is_paid == False)  # noqa: E712
        .all()
    )


@router.get("/records", response_model=List[FeeRecordDetail])
def list_fee_records(paid: Optional[bool] = None, db: Session = Depends(get_db),
                     teacher: Teacher = Depends(get_current_teacher)):
    """Every fee (paid and unpaid) with the student's name - newest due date first."""
    q = (
        db.query(FeeRecord).join(FeeRecord.student)
        .filter(owner_scope(Student, teacher))
    )
    if paid is not None:
        q = q.filter(FeeRecord.is_paid == paid)
    return [_detail(f) for f in q.order_by(FeeRecord.due_date.desc()).all()]


@router.post("/fees", response_model=FeeCreateResult)
def create_fees(payload: FeeCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db),
                teacher: Teacher = Depends(get_current_teacher)):
    """Creates one fee record per targeted student (explicit ids and/or a whole batch)."""
    if not payload.student_ids and not payload.batch_id:
        raise HTTPException(status_code=400, detail="Pick at least one student or a batch")

    students: dict[str, Student] = {}
    if payload.batch_id:
        batch = db.query(Batch).filter(Batch.id == payload.batch_id, owner_scope(Batch, teacher)).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        for s in db.query(Student).filter(owner_scope(Student, teacher), Student.batch_id == batch.id).all():
            students[s.id] = s
    if payload.student_ids:
        wanted = set(payload.student_ids)
        found = db.query(Student).filter(owner_scope(Student, teacher), Student.id.in_(wanted)).all()
        if len(found) != len(wanted):
            raise HTTPException(status_code=404, detail="One or more students weren't found")
        for s in found:
            students[s.id] = s

    if not students:
        raise HTTPException(status_code=400, detail="That batch has no students yet")

    created = []
    for s in students.values():
        fee = FeeRecord(
            student_id=s.id, amount_due=payload.amount, amount_paid=0.0,
            due_date=payload.due_date, description=(payload.description or None),
            allow_partial=payload.allow_partial,
        )
        db.add(fee)
        created.append(fee)
    db.flush()
    fee_ids = [f.id for f in created]
    db.commit()
    background_tasks.add_task(fee_notices.notify_fee_created, fee_ids)  # after commit; paid plans only
    return FeeCreateResult(created_count=len(students))


@router.post("/fees/{fee_id}/mark-paid", response_model=FeeRecordDetail)
def mark_fee_paid_manually(fee_id: str, background_tasks: BackgroundTasks,
                           payload: Optional[ManualPaymentRequest] = None,
                           db: Session = Depends(get_db),
                           teacher: Teacher = Depends(get_current_teacher)):
    """For money collected outside the app (cash, direct UPI, cheque). No body = the whole
    balance. `amount` records a part-payment - the teacher can always do this, whether or
    not the fee allows payers to pay in instalments online."""
    fee = _scoped_fee(db, teacher, fee_id)
    if fee.is_paid:
        raise HTTPException(status_code=400, detail="Already marked as paid")
    left = fee_ledger.remaining_paise(fee)
    paise = left if payload is None or payload.amount is None else int(round(payload.amount * 100))
    if paise <= 0 or paise > left:
        raise HTTPException(
            status_code=400,
            detail=f"Enter an amount between Rs.0.01 and the Rs.{left / 100:.2f} still owed.",
        )
    row = fee_ledger.record_manual(db, fee, paise)
    db.commit()
    background_tasks.add_task(fee_notices.notify_payment_received, row.id)
    return _detail(fee)


@router.delete("/fees/{fee_id}")
def delete_fee(fee_id: str, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Only fees nobody has paid anything on - received money is part of the ledger and
    stays (abandoned, unpaid checkout attempts go with the fee)."""
    fee = _scoped_fee(db, teacher, fee_id)
    if any(p.status == "paid" for p in fee.payments):
        raise HTTPException(status_code=400, detail="A fee with payments on it can't be deleted")
    db.delete(fee)
    db.commit()
    return {"deleted": True}


@router.get("/receipts/{payment_id}", response_model=ReceiptOut)
def teacher_receipt(payment_id: str, db: Session = Depends(get_db),
                    teacher: Teacher = Depends(get_current_teacher)):
    payment = (
        db.query(FeePayment).join(FeeRecord, FeeRecord.id == FeePayment.fee_record_id)
        .join(Student, Student.id == FeeRecord.student_id)
        .filter(FeePayment.id == payment_id, owner_scope(Student, teacher))
        .first()
    )
    return _receipt(db, payment)


@router.get("/payout-status", response_model=PayoutStatus)
def payout_status(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Can this teacher's students pay online yet? Both a linked payout account AND a
    plan that includes online fee collection are needed."""
    owner = subs.owner_for_teacher(teacher)
    configured = _payout_account_id(db, owner) is not None
    allowed = subs.has_feature(db, owner, "online_fee_collection")
    return PayoutStatus(configured=configured, online_fee_collection_allowed=allowed,
                        ready=configured and allowed)


@router.post("/send-reminders-now")
def trigger_fee_reminders(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Manual override for the daily cron job (services/fee_reminders.py) - scoped to
    the calling teacher's own data only, never a global sweep. institute_id for an
    institute-affiliated teacher (shared with teammates, as intended); teacher_id for
    an independent teacher (private to them - passing institute_id=None here used to
    mean "sweep every institute AND every independent teacher on the platform," which
    is exactly the bug this whole pass fixes). Runs synchronously; fine for typical
    coaching-centre fee-record volumes, but revisit as a background task if this ever
    needs to sweep thousands of records on demand."""
    subs.assert_feature(
        db, subs.owner_for_teacher(teacher), "fee_reminders",
        "Fee reminders aren't included in your current plan. Upgrade your plan in Billing to send them.",
    )
    if teacher.institute_id is not None:
        return send_due_fee_reminders(institute_id=teacher.institute_id)
    return send_due_fee_reminders(teacher_id=teacher.id)


# ---------- Receipts ----------
def _issuer_name(db: Session, student: Student) -> str:
    owner = subs.owner_for_student(student)
    if owner and owner.institute_id:
        row = db.query(Institute.name).filter(Institute.id == owner.institute_id).first()
    elif owner and owner.teacher_id:
        row = db.query(Teacher.name).filter(Teacher.id == owner.teacher_id).first()
    else:
        row = None
    return row[0] if row else ""


def _receipt(db: Session, payment: Optional[FeePayment]) -> ReceiptOut:
    """Receipt for a received payment. Callers pass a row already scoped to the person
    asking (teacher's own students / the student / the parent's child); None -> 404, and so
    does an unpaid (pending) attempt, which has no receipt."""
    if payment is None or payment.status != "paid":
        raise HTTPException(status_code=404, detail="Receipt not found")
    fee = payment.fee_record
    student = fee.student
    return ReceiptOut(
        receipt_no=fee_notices.receipt_no(payment), issued_to=student.name,
        issued_by=_issuer_name(db, student), fee_description=fee.description,
        fee_total=fee.amount_due, amount=payment.amount_paise / 100.0,
        refunded_amount=(payment.refunded_paise or 0) / 100.0,
        status=fee_ledger.display_status(payment), mode=payment.mode, paid_by=payment.paid_by,
        paid_at=payment.paid_at,
        razorpay_payment_id=payment.razorpay_payment_id if payment.mode == "online" else None,
        fee_balance=fee_ledger.remaining_paise(fee) / 100.0,
    )


def receipt_for_student(db: Session, student: Student, payment_id: str) -> ReceiptOut:
    payment = (
        db.query(FeePayment).join(FeeRecord, FeeRecord.id == FeePayment.fee_record_id)
        .filter(FeePayment.id == payment_id, FeeRecord.student_id == student.id)
        .first()
    )
    return _receipt(db, payment)


# ---------- Student AND parent: see + pay a student's fees ----------
# The logic lives in the helpers below and takes the Student the caller is scoped
# to. Student routes (here) and parent routes (routers/parents.py) both call them, so a
# parent paying is byte-for-byte the same flow as the child paying: same ownership
# check, same Route transfer, same ledger. The ONLY thing that decides
# whose fees can be touched is which Student the auth dependency resolved - a student
# token resolves to themselves, a parent token to their one linked child.
def my_fees_for(db: Session, student: Student) -> MyFeesOut:
    owner = subs.owner_for_student(student)
    online = bool(
        razorpay_configured()  # no API keys -> no Pay button (see services/razorpay_client.py)
        and owner and _payout_account_id(db, owner)
        and subs.has_feature(db, owner, "online_fee_collection")
    )
    rows = (
        db.query(FeeRecord).filter(FeeRecord.student_id == student.id)
        .order_by(FeeRecord.is_paid, FeeRecord.due_date).all()
    )
    return MyFeesOut(fees=[_my_fee(f) for f in rows], online_payment_available=online)


def _amount_to_charge(fee: FeeRecord, requested: Optional[float]) -> int:
    """How many paise this order should be for, enforcing the part-payment rules."""
    left = fee_ledger.remaining_paise(fee)
    if left <= 0:
        raise HTTPException(status_code=400, detail="Nothing left to pay on this fee")
    paise = left if requested is None else int(round(requested * 100))
    if paise == left:
        if paise < fee_ledger.MIN_ONLINE_PAISE:
            raise HTTPException(
                status_code=400,
                detail="The balance is under Rs.1, so it can't be paid online. Please pay your teacher directly.",
            )
        return paise
    if not fee.allow_partial:
        raise HTTPException(status_code=400, detail="This fee has to be paid in full.")
    if paise > left:
        raise HTTPException(status_code=400, detail=f"That is more than the Rs.{left / 100:.2f} still owed.")
    if paise < fee_ledger.MIN_ONLINE_PAISE:
        raise HTTPException(status_code=400, detail="The smallest online payment is Rs.1.")
    if left - paise < fee_ledger.MIN_ONLINE_PAISE:
        raise HTTPException(
            status_code=400,
            detail=f"That would leave under Rs.1 to pay. Pay the full Rs.{left / 100:.2f} instead.",
        )
    return paise


def create_order_for(db: Session, student: Student, payload: CreateOrderRequest, paid_by: str) -> dict:
    """Creates (or reuses) the Razorpay order for one of `student`'s fees, with the
    money routed to the student's own institute/teacher (see module docstring). The fee
    must belong to `student`, so nobody can generate/pay an order against someone
    else's fee record. `paid_by` is "student" or "parent"."""
    fee = db.query(FeeRecord).filter(
        FeeRecord.id == payload.fee_record_id, FeeRecord.student_id == student.id
    ).first()
    if not fee:
        raise HTTPException(status_code=404, detail="Fee record not found")
    if fee.is_paid:
        raise HTTPException(status_code=400, detail="Already paid")

    owner = subs.owner_for_student(student)
    account_id = _payout_account_id(db, owner) if owner else None
    if not razorpay_configured() or not account_id or not subs.has_feature(db, owner, "online_fee_collection"):
        raise HTTPException(status_code=409, detail=ONLINE_UNAVAILABLE_FOR_STUDENT)

    paise = _amount_to_charge(fee, payload.amount)
    bps = min(max(settings.fee_platform_commission_bps, 0), 5000)
    transfer_paise = paise - (paise * bps // 10000)

    client = get_razorpay_client()
    order_id = None
    # Reuse a still-open order for the SAME amount rather than minting a new one each
    # tap. Otherwise a payer who pays an older order after opening a newer one would be
    # charged twice for the same thing.
    for row in reversed(fee.payments):
        if row.status == "pending" and row.amount_paise == paise and row.razorpay_order_id:
            try:
                existing = client.order.fetch(row.razorpay_order_id)
                if existing.get("status") in ("created", "attempted") and existing.get("amount") == paise:
                    order_id = existing["id"]
            except Exception:
                order_id = None
            break

    if order_id is None:
        try:
            order = client.order.create({
                "amount": paise,  # paise
                "currency": "INR",
                "receipt": fee.id,
                "transfers": [{
                    "account": account_id,
                    "amount": transfer_paise,
                    "currency": "INR",
                    "notes": {"fee_record_id": fee.id},
                    "on_hold": 0,
                }],
            })
        except Exception:
            raise HTTPException(status_code=502, detail="Couldn't start the payment. Please try again.")
        order_id = order["id"]
        fee_ledger.new_pending(db, fee, paise, order_id, paid_by)
        db.commit()

    return {"order_id": order_id, "amount": paise / 100.0, "amount_paise": paise, "key_id": settings.razorpay_key_id}


def verify_payment_for(db: Session, student: Student, payload: VerifyFeePayment,
                       background: BackgroundTasks, paid_by: str) -> dict:
    """Called right after Checkout succeeds so the payer sees 'Paid' immediately; the
    webhook (below) is still the source of truth and lands on the same idempotent
    capture."""
    require_razorpay()  # an empty secret would still give a forgeable signature
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature check failed")

    payment = _payment_for_order(db, payload.razorpay_order_id)
    if not payment or payment.fee_record.student_id != student.id:
        raise HTTPException(status_code=404, detail="Fee record not found")
    payment.paid_by = paid_by  # whoever completed Checkout is who paid
    newly_paid = fee_ledger.capture(db, payment, payload.razorpay_payment_id)
    pid = payment.id
    db.commit()
    if newly_paid:
        background.add_task(fee_notices.notify_payment_received, pid)
    return {"status": "paid"}


@router.get("/my-fees", response_model=MyFeesOut)
def my_fees(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    return my_fees_for(db, student)


@router.post("/create-order", dependencies=[Depends(rate_limit("create-order", "rate_limit_payment_per_min"))])
def create_order(payload: CreateOrderRequest, db: Session = Depends(get_db),
                 student: Student = Depends(get_current_student)):
    """Student-facing. Requires a student token (see create_order_for)."""
    return create_order_for(db, student, payload, "student")


@router.post("/verify", dependencies=[Depends(rate_limit("verify", "rate_limit_verify_per_min"))])
def verify_fee_payment(payload: VerifyFeePayment, background_tasks: BackgroundTasks,
                       db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    return verify_payment_for(db, student, payload, background_tasks, "student")


@router.get("/my-receipts/{payment_id}", response_model=ReceiptOut)
def my_receipt(payment_id: str, db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    return receipt_for_student(db, student, payment_id)


def _apply_refund_event(db: Session, razorpay_payment_id: Optional[str]) -> None:
    """A refund finished at Razorpay. Take the payment's CUMULATIVE refunded amount from
    Razorpay itself rather than adding this event's amount, so a replayed event, or several
    partial refunds arriving in any order, all converge on the right total. If Razorpay
    can't be reached we answer 503 (nothing is committed, so Razorpay retries) instead of
    guessing."""
    if not razorpay_payment_id:
        return
    row = db.query(FeePayment).filter(FeePayment.razorpay_payment_id == razorpay_payment_id).with_for_update().first()
    if row is None:
        # Possibly the extra payment of a fee flagged as a duplicate BEFORE the ledger
        # existed (its amount was never recorded as a row): the refund resolves the flag.
        fee = db.query(FeeRecord).filter(FeeRecord.duplicate_payment_id == razorpay_payment_id).first()
        if fee:
            fee.duplicate_payment_id = None
        return
    try:
        total = int(get_razorpay_client().payment.fetch(razorpay_payment_id)["amount_refunded"])
    except Exception:
        raise HTTPException(status_code=503, detail="Couldn't confirm the refund with Razorpay; retry later")
    fee_ledger.apply_refund(db, row, total)


def _issue_charge_invoice(db: Session, snapshot: dict, payment: Optional[dict]) -> None:
    """Invoice a successful subscription charge - without EVER failing the webhook. Every Razorpay
    event (fees included) shares this one endpoint, and an endpoint that keeps erroring gets retried
    for a day and then disabled by Razorpay, so a bug in invoicing must not be able to take payment
    notifications down with it. The work runs in a savepoint: if it fails, only the invoice is
    rolled back, the subscription update still lands, and the error is logged with the payment id so
    the invoice can be issued by hand (services/invoices.py::issue_invoice, total_paise=amount)."""
    try:
        with db.begin_nested():
            invoices.issue_for_charge(db, snapshot, payment)
    except Exception:
        logger.exception("INVOICE_NOT_ISSUED payment=%s subscription=%s - issue it by hand",
                         (payment or {}).get("id"), (snapshot or {}).get("id"))


def _apply_upgrade_payment(db: Session, upgrade, payment: dict, applied: list) -> None:
    """The payment webhook's half of "upgrade now" (the browser's half is /billing/upgrade/verify).
    Only a captured payment counts. If the event carries no usable amount we ask Razorpay, and if
    that fails we answer 503 so Razorpay retries instead of us guessing about money."""
    pay_id = payment.get("id")
    status = payment.get("status")
    if not pay_id or (status and status != "captured"):
        return
    amount = payment.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int):
        try:
            amount = int(get_razorpay_client().payment.fetch(pay_id)["amount"])
        except Exception:
            raise HTTPException(status_code=503, detail="Couldn't confirm the payment with Razorpay; retry later")
    outcome = upgrades.apply_paid(db, upgrade, pay_id, amount, paid_at=invoices._utc(payment.get("created_at")))
    if outcome in ("applied", "already"):  # "already": a redelivery retries a renewal switch that was missed
        applied.append(upgrade.id)


# ---------- Razorpay webhook (fees AND subscriptions) ----------
@router.post("/webhook")
async def razorpay_webhook(request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """The single Razorpay webhook. Configure it in the dashboard with at least:
    payment.captured, order.paid, refund.processed, subscription.activated,
    subscription.charged, subscription.pending, subscription.halted,
    subscription.cancelled, subscription.completed. Verify the signature - never trust client-reported
    'I paid' without this, that's a free-features-forever exploit waiting to happen."""
    if not settings.razorpay_webhook_secret:
        # An empty secret would let anyone forge a valid signature (HMAC with an empty
        # key is computable by the attacker), so refuse outright until it's configured.
        raise HTTPException(status_code=503, detail="Webhook secret isn't configured")

    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(settings.razorpay_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event", "")
    event_id = request.headers.get("X-Razorpay-Event-Id")

    # Razorpay retries and can redeliver: acknowledge anything already processed.
    if event_id and db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first():
        return {"status": "duplicate"}

    body_payload = payload.get("payload") or {}
    subscription_superseded: list = []
    newly_paid: list[str] = []
    upgrades_applied: list[str] = []  # PlanUpgrade ids to finish (renewal price) after the commit

    if event.startswith("subscription."):
        entity = (body_payload.get("subscription") or {}).get("entity")
        if entity:
            snapshot = entity  # the state AT this event - what an invoice must describe
            # Prefer Razorpay's CURRENT view over the (possibly stale, possibly
            # out-of-order) snapshot in the payload; fall back to the payload if the
            # API call fails so a hiccup there never drops the event.
            try:
                entity = get_razorpay_client().subscription.fetch(entity["id"])
            except Exception:
                pass
            subscription_superseded = []
            subs.apply_razorpay_subscription(db, entity, subscription_superseded)
            if event == "subscription.charged":
                _issue_charge_invoice(db, snapshot, (body_payload.get("payment") or {}).get("entity"))

    elif event in ("payment.captured", "order.paid"):
        payment = (body_payload.get("payment") or {}).get("entity") or {}
        order_id = payment.get("order_id") or (body_payload.get("order") or {}).get("entity", {}).get("id")
        upgrade = upgrades.find_by_order(db, order_id, lock=True)
        if upgrade is not None:
            # A SaaS "upgrade now" payment, not a student fee (its order is ours, see billing.py).
            _apply_upgrade_payment(db, upgrade, payment, upgrades_applied)
        else:
            row = _payment_for_order(db, order_id)
            if row:
                pid = row.id
                if fee_ledger.capture(db, row, payment.get("id")):
                    newly_paid.append(pid)

    elif event == "refund.processed":
        refund = (body_payload.get("refund") or {}).get("entity") or {}
        _apply_refund_event(db, refund.get("payment_id"))

    if event_id:
        db.add(WebhookEvent(event_id=event_id, event_type=event))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # a concurrent delivery of the same event won the race
        return {"status": "duplicate"}
    subs.cancel_superseded(get_razorpay_client(), subscription_superseded)
    for uid in upgrades_applied:
        upgrades.switch_renewal(db, get_razorpay_client(), uid)  # best effort, never raises
    for pid in newly_paid:
        background_tasks.add_task(fee_notices.notify_payment_received, pid)  # receipt, once, after commit
    return {"status": "ok"}
