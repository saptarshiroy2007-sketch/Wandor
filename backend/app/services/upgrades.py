"""Upgrade now - move to a higher plan immediately and pay only for the rest of the period.

How it works (and why it is built this way):

* The customer pays the PRORATED DIFFERENCE for the rest of the current billing period through a
  one-off Razorpay Order, then moves to the higher plan at once. We deliberately do NOT use
  Razorpay's "update subscription" API to take the money: it refuses subscriptions whose payment
  mode is UPI ("Subscriptions cannot be updated when payment mode is UPI"), and an Order works
  for every payment method.
* Proration runs on the BASE price, GST is added on top afterwards (same rule as every invoice):
      base = (new_base - old_base) x (time left in the period / length of the period)
  in integer paise, rounded half-up once. The invoice is kind="proration".
* The Order is paid in the browser, so BOTH the browser's verify call and the payment webhook can
  apply it. Applying is idempotent (the PlanUpgrade row is locked and moves pending -> applied
  exactly once), so the two can race safely. The webhook is the source of truth.
* If money is taken but the upgrade can no longer be applied (the period renewed first, or the
  plan was already raised) the row becomes "refund_needed" and UPGRADE_NEEDS_REFUND is logged at
  ERROR level: an operator refunds that payment by hand. We never silently keep the money AND
  withhold the plan.
* Renewal price. Entitlement switches now, but Razorpay's subscription still has the old plan_id,
  so the next renewal would charge the old price. After the upgrade is committed we try
  `subscription.edit(plan_id=new, schedule_change_at="cycle_end")`. If Razorpay refuses (UPI) we
  fall back to cancelling the old subscription at the end of the period; the customer then
  subscribes again (POST /billing/subscribe starts the new subscription at the period end, so
  nobody is charged twice) - PlanUpgrade.renewal says which happened. Until that period ends,
  services/subscriptions.py::held_plan keeps the upgraded plan even though Razorpay still reports
  the old one.

Scope limits (deliberate): upgrades only (a higher plan, the SAME billing cycle); downgrades and
cycle changes stay on POST /billing/change-plan (effective at renewal).
"""
import calendar
import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import plans
from ..models import PlanUpgrade, Subscription
from . import invoices
from . import subscriptions as subs

logger = logging.getLogger(__name__)

MIN_ORDER_PAISE = 100  # Razorpay will not create an order below Rs 1


def _rank(plan: str) -> int:
    return plans.PLAN_ORDER.index(plan) if plan in plans.PLAN_ORDER else -1


# ---------- the maths ----------
def _add_months(dt: datetime, months: int) -> datetime:
    m = dt.month - 1 + months
    year, month = dt.year + m // 12, m % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def period_bounds(sub: Subscription) -> tuple[datetime, datetime]:
    """(start, end) of the billing period `sub` is in. We store only the end, and Razorpay's
    periods are whole calendar months/years, so the start is one cycle before it."""
    end = sub.current_period_end
    return _add_months(end, -(12 if sub.billing_cycle == "yearly" else 1)), end


def prorate_base(old_base: int, new_base: int, remaining_seconds: int, total_seconds: int) -> int:
    """Base paise to charge now: the price difference scaled by the share of the period left.
    Integer maths, rounded half-up once. A full period left charges the full difference."""
    if total_seconds <= 0:
        raise ValueError("period length must be positive")
    if new_base < old_base:
        raise ValueError("not an upgrade")
    remaining = max(0, min(remaining_seconds, total_seconds))
    return (2 * (new_base - old_base) * remaining + total_seconds) // (2 * total_seconds)


def _fail(status: int, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail=message)


def quote(sub: Optional[Subscription], to_plan: str, now: Optional[datetime] = None) -> dict:
    """What upgrading to `to_plan` right now would cost, or an HTTPException saying why not.
    Pure: reads the row, calls nobody, writes nothing."""
    now = now or datetime.utcnow()
    if not (sub and sub.razorpay_subscription_id and sub.status == "active"
            and subs.effective_plan(sub, now) != "free"):
        raise _fail(400, "You need an active paid subscription to upgrade now")
    if sub.cancel_at_period_end:
        raise _fail(409, "Your subscription is set to end this period. Subscribe again to continue, "
                         "then upgrade.")
    if sub.scheduled_plan:
        raise _fail(409, "You already have a plan change scheduled for your next renewal. "
                         "Upgrading now isn't possible until it takes effect.")
    if to_plan not in plans.PAID_PLAN_KEYS:
        raise _fail(400, "Unknown plan")
    if _rank(to_plan) <= _rank(sub.plan):
        raise _fail(400, "Upgrade now is only for moving to a higher plan. To move to a lower plan, "
                         "use Change plan - it takes effect at your next renewal.")
    cycle = sub.billing_cycle
    if cycle not in plans.CYCLE_KEYS or sub.current_period_end is None:
        raise _fail(400, "Your billing period isn't known yet. Try again in a moment.")
    if not plans.razorpay_plan_id(to_plan, cycle):
        raise _fail(503, "This plan isn't available for purchase yet")

    start, end = period_bounds(sub)
    total_s = int((end - start).total_seconds())
    remaining_s = int((end - now).total_seconds())
    if remaining_s <= 0:
        raise _fail(409, "Your plan is renewing right now. Try again in a minute.")
    remaining_s = min(remaining_s, total_s)

    old_base = invoices.price_breakdown(sub.plan, cycle)["base_paise"]
    new_base = invoices.price_breakdown(to_plan, cycle)["base_paise"]
    base = prorate_base(old_base, new_base, remaining_s, total_s)
    gst, total = invoices.gst_on_top(base)
    if total < MIN_ORDER_PAISE:
        raise _fail(409, "Your plan renews in a few moments - it is too close to renewal to upgrade now. "
                         "Use Change plan to switch at renewal.")
    credit = (2 * old_base * remaining_s + total_s) // (2 * total_s)  # unused part of the old plan
    return {
        "from_plan": sub.plan, "to_plan": to_plan, "cycle": cycle,
        "period_start": start, "period_end": end,
        "remaining_seconds": remaining_s, "total_seconds": total_s,
        "credit_base_paise": credit, "charge_base_paise": credit + base,  # charge - credit == base
        "base_paise": base, "gst_paise": gst, "total_paise": total,
    }


# ---------- rows ----------
def find_by_order(db: Session, order_id: Optional[str], lock: bool = False) -> Optional[PlanUpgrade]:
    """The upgrade for a Razorpay order (row-locked when asked, so the browser's verify call and
    the webhook can't both apply it at once). None for any order that isn't an upgrade."""
    if not order_id:
        return None
    q = db.query(PlanUpgrade).filter(PlanUpgrade.razorpay_order_id == order_id)
    return (q.with_for_update() if lock else q).first()


def create_pending(db: Session, sub: Subscription, q: dict, order_id: str) -> PlanUpgrade:
    up = PlanUpgrade(
        subscription_id=sub.id, razorpay_order_id=order_id,
        from_plan=q["from_plan"], to_plan=q["to_plan"], billing_cycle=q["cycle"],
        base_paise=q["base_paise"], gst_paise=q["gst_paise"], total_paise=q["total_paise"],
        period_start=q["period_start"], period_end=q["period_end"], status="pending",
    )
    db.add(up)
    db.flush()
    return up


def applied_for_period(db: Session, sub: Optional[Subscription]) -> Optional[PlanUpgrade]:
    """The upgrade (if any) that is in force for the period `sub` is in right now."""
    if sub is None or sub.current_period_end is None:
        return None
    return (db.query(PlanUpgrade)
            .filter(PlanUpgrade.subscription_id == sub.id, PlanUpgrade.status == "applied",
                    PlanUpgrade.period_end == sub.current_period_end)
            .order_by(PlanUpgrade.applied_at.desc()).first())


# ---------- applying a paid upgrade ----------
def apply_paid(db: Session, up: PlanUpgrade, payment_id: str, paid_paise: int,
               paid_at: Optional[datetime] = None, now: Optional[datetime] = None) -> str:
    """Apply an upgrade whose Razorpay payment has been captured. `up` must be row-locked by the
    caller (find_by_order(lock=True)). Returns "applied", "already" (it had been applied) or
    "refund_needed". Idempotent. Flushes, does NOT commit; makes no Razorpay call."""
    now = now or datetime.utcnow()
    if up.status == "applied":
        return "already"
    if up.status == "refund_needed":
        return "refund_needed"

    sub = (db.query(Subscription).filter(Subscription.id == up.subscription_id)
           .with_for_update().first())
    reason = None
    if sub is None:
        reason = "the subscription no longer exists"
    elif paid_paise != up.total_paise:
        reason = f"paid {paid_paise} paise but the order was for {up.total_paise}"
    elif (sub.status != "active" or sub.current_period_end != up.period_end
          or subs.effective_plan(sub, now) == "free"):
        reason = "the billing period changed before the payment arrived"
    elif _rank(sub.plan) >= _rank(up.to_plan):
        reason = "the plan was already at or above this level"
    if reason:
        up.status, up.note, up.razorpay_payment_id = "refund_needed", reason, payment_id
        db.flush()
        logger.error("UPGRADE_NEEDS_REFUND order=%s payment=%s - %s; refund this payment by hand",
                     up.razorpay_order_id, payment_id, reason)
        return "refund_needed"

    up.status, up.razorpay_payment_id, up.applied_at = "applied", payment_id, now
    sub.plan = up.to_plan  # the billing cycle is unchanged: upgrade-now never changes it
    sub.scheduled_plan = sub.scheduled_cycle = None
    subs._mirror_institute_plan(db, sub)
    db.flush()

    # The invoice must never be able to undo a payment we have already taken: a failure here is
    # logged with the payment id so the invoice can be issued by hand (see the 4.2 notes).
    from_label = plans.PLANS[up.from_plan]["label"]
    to_label = plans.PLANS[up.to_plan]["label"]
    try:
        with db.begin_nested():
            invoices.issue_invoice(
                db, sub, plan=up.to_plan, cycle=up.billing_cycle, total_paise=paid_paise,
                razorpay_payment_id=payment_id, kind="proration",
                description=(f"Upgrade from {from_label} to {to_label} ({up.billing_cycle}) - "
                             f"prorated to {up.period_end:%d %b %Y}"),
                period_start=now, period_end=up.period_end, issued_at=paid_at or now)
    except Exception:
        logger.exception("INVOICE_NOT_ISSUED payment=%s upgrade=%s - issue it by hand "
                         "(kind='proration', total_paise=%s)", payment_id, up.id, paid_paise)
    return "applied"


# ---------- the next renewal's price (talks to Razorpay: call AFTER the commit) ----------
def switch_renewal(db: Session, client, upgrade_id: str) -> None:
    """Make the NEXT renewal charge the new plan's price. Best effort and never raises: the
    upgrade is already paid for and committed, and a webhook calling this must still answer 200.
    Runs at most once per upgrade (the row is locked and `renewal` is set when done)."""
    try:
        up = (db.query(PlanUpgrade).filter(PlanUpgrade.id == upgrade_id).with_for_update().first())
        if up is None or up.status != "applied" or up.renewal is not None:
            return
        sub = db.query(Subscription).filter(Subscription.id == up.subscription_id).first()
        if sub is None or not sub.razorpay_subscription_id:
            return
        if sub.cancel_at_period_end:
            return  # already ending this period: there is no renewal to re-price
        rz_plan = plans.razorpay_plan_id(up.to_plan, up.billing_cycle)
        try:
            client.subscription.edit(sub.razorpay_subscription_id, {
                "plan_id": rz_plan, "schedule_change_at": "cycle_end", "customer_notify": 1})
            up.renewal = "scheduled"
        except Exception:
            # Typically a UPI subscription, which Razorpay will not edit. Fall back to ending the
            # old subscription at period end; the customer subscribes again to the new plan.
            try:
                client.subscription.cancel(sub.razorpay_subscription_id, {"cancel_at_cycle_end": 1})
                sub.cancel_at_period_end = True
                up.renewal = "reauthorise"
            except Exception:
                up.renewal = "failed"
                logger.error("UPGRADE_RENEWAL_NOT_SWITCHED subscription=%s upgrade=%s - it will renew at the "
                             "OLD plan's price; fix it in the Razorpay dashboard",
                             sub.razorpay_subscription_id, up.id)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("UPGRADE_RENEWAL_ERROR upgrade=%s", upgrade_id)
