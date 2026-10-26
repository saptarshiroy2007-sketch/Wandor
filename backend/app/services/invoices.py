"""Invoices for SaaS subscription charges - GST maths, numbering, and issuing.

Rules this module protects:

1. Money is integer paise, never floats. GST is ADDED ON TOP of the base price (owner decision,
   Phase 4.0): total = base + GST. Rounding is half-up to the nearest paisa, done once, on the
   GST amount - never on the total - so base + GST always equals total exactly.
2. What was actually charged is the truth. An invoice for a real Razorpay payment is built from
   that payment's total (`total_paise=`) and the base/GST split is backed out of it, so an invoice
   can never disagree with the money that moved even if prices or the GST rate change later.
   (`base_paise=` is for amounts WE compute, e.g. a prorated upgrade in Phase 4.3, where
   proration runs on the base and GST is computed after.)
3. Invoice numbers are consecutive within a financial year (April-March, IST) with no gaps and no
   duplicates, as Indian GST invoice rules expect. Format: WND/2627/000001 (<= 16 chars).
   The number is allocated in the same transaction as the invoice, so a rollback hands it back.
4. Issuing is idempotent on razorpay_payment_id: Razorpay redelivers webhooks and the browser
   races them, so asking twice for the same payment returns the same invoice and burns no number.
5. Invoices are append-only. Never edit one; issue a correction instead.

issue_for_charge() (Phase 4.2) is what the `subscription.charged` webhook calls: it turns one
Razorpay charge into one invoice. The list API lives in routers/billing.py.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import plans
from ..database import settings
from ..models import Invoice, InvoiceCounter, Subscription

logger = logging.getLogger(__name__)

_IST = timedelta(hours=5, minutes=30)
MAX_INVOICE_NUMBER_LEN = 16  # GST rule: an invoice number is at most 16 characters


# ---------- GST maths ----------
def _rate(rate_bps: Optional[int]) -> int:
    r = settings.gst_rate_bps if rate_bps is None else rate_bps
    if r < 0:
        raise ValueError("GST rate cannot be negative")
    return r


def gst_on_top(base_paise: int, rate_bps: Optional[int] = None) -> tuple[int, int]:
    """(gst_paise, total_paise) when GST is added on top of a base price."""
    if base_paise < 0:
        raise ValueError("amount cannot be negative")
    r = _rate(rate_bps)
    gst = (base_paise * r + 5000) // 10000  # half-up, integers only
    return gst, base_paise + gst


def split_inclusive(total_paise: int, rate_bps: Optional[int] = None) -> tuple[int, int]:
    """(base_paise, gst_paise) backed out of an amount that already includes GST - the inverse
    of gst_on_top (exact for every whole-paisa base: checked in the tests)."""
    if total_paise < 0:
        raise ValueError("amount cannot be negative")
    d = 10000 + _rate(rate_bps)
    base = (total_paise * 10000 + d // 2) // d
    return base, total_paise - base


def price_breakdown(plan: str, cycle: str, rate_bps: Optional[int] = None) -> dict:
    """What a plan/cycle costs in paise: the catalog price is the BASE, GST goes on top.
    The Razorpay Plan for this plan/cycle must be created at `total_paise`."""
    base = int(plans.PLANS[plan][f"price_{cycle}"]) * 100
    gst, total = gst_on_top(base, rate_bps)
    return {"base_paise": base, "gst_paise": gst, "total_paise": total}


# ---------- Numbering ----------
def financial_year_label(when_utc: datetime) -> str:
    """Indian financial year (1 April - 31 March, decided in IST) as 4 digits: 1 Apr 2026 ->
    '2627'. IST matters: 18:30 UTC on 31 March is already 1 April in India."""
    ist = when_utc + _IST
    start = ist.year if ist.month >= 4 else ist.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def next_invoice_number(db: Session, issued_at: datetime) -> str:
    """Allocates the next number for issued_at's financial year. Takes a row lock on that year's
    counter, so concurrent issuers queue up instead of colliding; the lock and the increment
    live in the caller's transaction, so if the invoice insert fails and rolls back, the number
    is not consumed. Does NOT commit."""
    fy = financial_year_label(issued_at)
    q = db.query(InvoiceCounter).filter(InvoiceCounter.fy == fy)
    row = q.with_for_update().first()
    if row is None:
        try:
            with db.begin_nested():
                db.add(InvoiceCounter(fy=fy, last_seq=0))
                db.flush()
        except IntegrityError:
            pass  # a concurrent issuer created this year's counter first - lock theirs below
        row = q.with_for_update().first()
    row.last_seq += 1
    db.flush()
    number = f"{settings.invoice_prefix}/{fy}/{row.last_seq:06d}"
    if len(number) > MAX_INVOICE_NUMBER_LEN:
        raise ValueError(
            f"Invoice number {number!r} is longer than {MAX_INVOICE_NUMBER_LEN} characters - "
            "shorten INVOICE_PREFIX")
    return number


# ---------- Issuing ----------
def get_by_payment(db: Session, razorpay_payment_id: str) -> Optional[Invoice]:
    return db.query(Invoice).filter(Invoice.razorpay_payment_id == razorpay_payment_id).first()


def issue_invoice(
    db: Session, subscription: Subscription, *, plan: str, cycle: Optional[str],
    total_paise: Optional[int] = None, base_paise: Optional[int] = None,
    razorpay_payment_id: Optional[str] = None, kind: str = "subscription",
    description: Optional[str] = None, period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None, issued_at: Optional[datetime] = None,
    rate_bps: Optional[int] = None,
) -> Invoice:
    """Creates the invoice for one charge, or returns the existing one if this payment already
    has an invoice. Give exactly one of total_paise (a real charge: GST is backed out of it) or
    base_paise (an amount we computed: GST is added on top). Flushes, does NOT commit."""
    if (total_paise is None) == (base_paise is None):
        raise ValueError("give exactly one of total_paise or base_paise")

    if razorpay_payment_id:
        existing = get_by_payment(db, razorpay_payment_id)
        if existing is not None:
            return existing

    rate = _rate(rate_bps)
    if total_paise is not None:
        base, gst = split_inclusive(total_paise, rate)
        total = total_paise
    else:
        gst, total = gst_on_top(base_paise, rate)
        base = base_paise

    issued_at = issued_at or datetime.utcnow()
    label = plans.PLANS.get(plan, {}).get("label", plan)
    default_desc = f"{label} plan - {cycle} subscription" if cycle else f"{label} plan"
    try:
        # One savepoint around number + insert: if a concurrent issuer wins the unique
        # razorpay_payment_id, our number goes back to the counter and we return theirs.
        with db.begin_nested():
            invoice = Invoice(
                invoice_number=next_invoice_number(db, issued_at),
                subscription_id=subscription.id, kind=kind, plan=plan, billing_cycle=cycle,
                description=description or default_desc,
                base_paise=base, gst_rate_bps=rate, gst_paise=gst, total_paise=total,
                currency="INR", razorpay_payment_id=razorpay_payment_id or None,
                period_start=period_start, period_end=period_end, issued_at=issued_at,
            )
            db.add(invoice)
            db.flush()
    except IntegrityError:
        if razorpay_payment_id:
            existing = get_by_payment(db, razorpay_payment_id)
            if existing is not None:
                return existing
        raise
    return invoice


# ---------- From a Razorpay charge ----------
def _utc(ts) -> Optional[datetime]:
    """Razorpay unix seconds -> naive UTC datetime (how every datetime in this app is stored)."""
    try:
        return datetime.utcfromtimestamp(int(ts)) if ts else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _subscription_for(db: Session, snapshot: dict) -> Optional[Subscription]:
    """The Subscription row a charge belongs to: by Razorpay subscription id first, then by the
    owner we stamped into the subscription's notes at creation. The fallback matters: a customer
    who re-subscribed after a failed payment has a NEW id on the row, but a late charge on the OLD
    subscription is still real money and still needs an invoice."""
    rz_id = snapshot.get("id")
    sub = None
    if rz_id:
        sub = db.query(Subscription).filter(Subscription.razorpay_subscription_id == rz_id).first()
    if sub is None:
        notes = snapshot.get("notes") or {}
        institute_id, teacher_id = notes.get("institute_id") or None, notes.get("teacher_id") or None
        if bool(institute_id) != bool(teacher_id):  # exactly one owner, like Subscription itself
            q = db.query(Subscription)
            sub = (q.filter(Subscription.institute_id == institute_id).first() if institute_id
                   else q.filter(Subscription.teacher_id == teacher_id).first())
    return sub


def issue_for_charge(db: Session, snapshot: dict, payment: Optional[dict]) -> Optional[Invoice]:
    """One successful subscription charge -> one invoice. Called from the `subscription.charged`
    webhook with the payload's own subscription entity (`snapshot`: the state AT the charge, which
    is what says which plan was billed - not the later subscription.fetch) and payment entity.

    Returns None (and logs why) when there is nothing to invoice: no payment attempt in the event,
    a payment that isn't captured, a zero/odd amount, a non-INR charge, or a subscription that
    isn't ours. The invoice is built from the amount ACTUALLY charged (see module rule 2); if that
    differs from the catalog's base + GST, the invoice is still issued - it's the truth - but
    INVOICE_AMOUNT_MISMATCH is logged, which is how a Razorpay Plan created without GST shows up.
    Idempotent per payment. Flushes, does NOT commit; the webhook isolates failures around this."""
    payment = payment or {}
    pay_id = payment.get("id")
    sub_id = snapshot.get("id")
    if not pay_id:
        logger.warning("CHARGED_EVENT_WITHOUT_PAYMENT subscription=%s - no invoice", sub_id)
        return None
    status = payment.get("status")
    if status and status != "captured":
        logger.warning("CHARGE_NOT_CAPTURED payment=%s status=%s - no invoice", pay_id, status)
        return None
    amount = payment.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        logger.warning("CHARGE_BAD_AMOUNT payment=%s amount=%r - no invoice", pay_id, amount)
        return None
    if (payment.get("currency") or "INR") != "INR":
        logger.warning("CHARGE_NOT_INR payment=%s currency=%s - no invoice", pay_id, payment.get("currency"))
        return None

    # Sessions here run with autoflush OFF, so push what apply_razorpay_subscription just changed
    # (the first-ever charge sets razorpay_subscription_id) before querying. Belt and braces: the
    # owner-notes lookup below would find the row even without it.
    db.flush()
    sub = _subscription_for(db, snapshot)
    if sub is None:
        logger.error("INVOICE_NOT_ISSUED payment=%s subscription=%s - no matching subscription row", pay_id, sub_id)
        return None

    found = plans.plan_from_razorpay_plan_id(snapshot.get("plan_id") or "")
    plan, cycle = found if found else (sub.plan, sub.billing_cycle)

    if plan in plans.PAID_PLAN_KEYS and cycle in plans.CYCLE_KEYS:
        expected = price_breakdown(plan, cycle)["total_paise"]
        if expected != amount:
            logger.warning(
                "INVOICE_AMOUNT_MISMATCH payment=%s charged=%d catalog_total=%d plan=%s/%s - "
                "was the Razorpay Plan created at base + GST? Invoicing what was charged.",
                pay_id, amount, expected, plan, cycle)

    return issue_invoice(
        db, sub, plan=plan, cycle=cycle, total_paise=amount, razorpay_payment_id=pay_id,
        period_start=_utc(snapshot.get("current_start")), period_end=_utc(snapshot.get("current_end")),
        issued_at=_utc(payment.get("created_at")) or datetime.utcnow(),
    )
