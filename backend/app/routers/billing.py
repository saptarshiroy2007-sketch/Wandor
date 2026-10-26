"""SaaS subscription endpoints - what institutes / independent teachers pay the platform.
(Student fee payments are a different money flow entirely - see routers/payments.py.)

Flow:
  1. GET  /billing/plans      - catalog for the pricing UI
  2. GET  /billing/me         - current plan, usage vs limits
  3. POST /billing/subscribe  - creates a Razorpay Subscription, returns what the browser
                                needs to open Razorpay Checkout
  4. (Checkout happens in the browser)
  5. POST /billing/verify     - checks Checkout's signature then pulls the subscription
                                from Razorpay so the UI updates instantly
  6. Razorpay webhooks (routers/payments.py's single /payments/webhook) keep it in sync
     from then on - renewals, failed charges, cancellations. The webhook, not the
     browser, is the source of truth.
  7. GET /billing/invoices[/{id}] - the invoices the webhook created for each successful charge.
  8. Upgrade now (prorated, immediate): POST /billing/upgrade/quote -> POST /billing/upgrade
     (creates a one-off Razorpay Order) -> Checkout in the browser -> POST /billing/upgrade/verify.
     The payment webhook applies it too; see services/upgrades.py for the rules.
"""
import calendar
import hashlib
import hmac
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import plans
from ..auth import BillingActor, get_billing_actor
from ..database import get_db, settings
from ..models import Invoice
from ..ratelimit import rate_limit
from ..schemas import (
    PlanOut, BillingStatus, SubscribeRequest, SubscribeResponse, VerifySubscription, InvoiceOut,
    UpgradeRequest, UpgradeQuote, UpgradeOrder, VerifyUpgrade, SellerOut,
)
from ..services import invoices
from ..services.access import access_for_owner
from ..services import upgrades
from ..services import subscriptions as subs
from ..services.razorpay_client import get_razorpay_client, require_razorpay

router = APIRouter(prefix="/billing", tags=["billing"])

PAID_PLANS = ("basic", "pro")
CYCLES = ("monthly", "yearly")


def _require_manager(actor: BillingActor, ask: str = "change the plan") -> None:
    if not actor.can_manage:
        raise HTTPException(
            status_code=403,
            detail=f"Billing is managed by your institute's admin. Ask them to {ask}.",
        )


def _validate_choice(plan: str, cycle: str) -> str:
    """Returns the configured Razorpay plan id, or raises."""
    if plan not in PAID_PLANS or cycle not in CYCLES:
        raise HTTPException(status_code=400, detail="Unknown plan or billing cycle")
    rz_plan_id = plans.razorpay_plan_id(plan, cycle)
    if not rz_plan_id:
        raise HTTPException(status_code=503, detail="This plan isn't available for purchase yet")
    return rz_plan_id


def _upgrade_renewal(db: Session, sub) -> Optional[str]:
    up = upgrades.applied_for_period(db, sub)
    return up.renewal if up else None


def _status_for(db: Session, actor: BillingActor) -> BillingStatus:
    sub = subs.get_subscription(db, actor.owner)
    plan = subs.effective_plan(sub)
    lim = plans.limits(plan)
    use = subs.usage(db, actor.owner)
    access = access_for_owner(db, actor.owner)
    # Report the raw lifecycle status only while it's actually what's granting access;
    # once entitlement has lapsed the owner is effectively on Free, and saying
    # "active" next to "Free" would be misleading.
    if plan == "free":
        status = "expired" if (sub is not None and sub.plan != "free") else "free"
    else:
        status = sub.status
    return BillingStatus(
        plan=plan, plan_label=lim["label"], status=status,
        billing_cycle=sub.billing_cycle if sub and plan != "free" else None,
        current_period_end=sub.current_period_end if sub and plan != "free" else None,
        cancel_at_period_end=bool(sub.cancel_at_period_end) if sub else False,
        scheduled_plan=sub.scheduled_plan if sub else None,
        scheduled_cycle=sub.scheduled_cycle if sub else None,
        students_used=use["students"], students_limit=lim["max_students"],
        teachers_used=use["teachers"], teachers_limit=lim["max_teachers"],
        online_fee_collection=bool(lim["online_fee_collection"]),
        fee_reminders=bool(lim.get("fee_reminders")),
        can_manage=actor.can_manage,
        owner_kind="institute" if actor.owner.institute_id else "teacher",
        upgrade_renewal=_upgrade_renewal(db, sub),
        access_state=access.state, access_reason=access.reason, ban_at=access.ban_at,
    )


@router.get("/plans", response_model=list[PlanOut])
def list_plans():
    """Public - the pricing catalog (no auth needed to see prices). price_monthly/price_yearly
    are BASE prices excluding GST; the gst_* / total_* fields (paise) are what is actually charged."""
    out = []
    for key in plans.PLAN_ORDER:
        p = plans.PLANS[key]
        m, y = invoices.price_breakdown(key, "monthly"), invoices.price_breakdown(key, "yearly")
        out.append(PlanOut(
            key=key, label=p["label"],
            price_monthly=p["price_monthly"], price_yearly=p["price_yearly"],
            max_students=p["max_students"], max_teachers=p["max_teachers"],
            online_fee_collection=p["online_fee_collection"],
            fee_reminders=bool(p.get("fee_reminders")),
            monthly_available=key == "free" or bool(plans.razorpay_plan_id(key, "monthly")),
            yearly_available=key == "free" or bool(plans.razorpay_plan_id(key, "yearly")),
            gst_rate_percent=settings.gst_rate_bps / 100,
            gst_monthly_paise=m["gst_paise"], total_monthly_paise=m["total_paise"],
            gst_yearly_paise=y["gst_paise"], total_yearly_paise=y["total_paise"],
        ))
    return out


@router.get("/me", response_model=BillingStatus)
def my_billing(db: Session = Depends(get_db), actor: BillingActor = Depends(get_billing_actor)):
    return _status_for(db, actor)


def _invoice_out(inv: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=inv.id, invoice_number=inv.invoice_number, kind=inv.kind, plan=inv.plan,
        plan_label=plans.PLANS.get(inv.plan, {}).get("label", inv.plan),
        billing_cycle=inv.billing_cycle, description=inv.description,
        base_paise=inv.base_paise, gst_rate_percent=inv.gst_rate_bps / 100, gst_paise=inv.gst_paise,
        total_paise=inv.total_paise, currency=inv.currency,
        period_start=inv.period_start, period_end=inv.period_end, issued_at=inv.issued_at,
    )


@router.get("/seller", response_model=SellerOut)
def invoice_seller(actor: BillingActor = Depends(get_billing_actor)):
    """The seller's legal name / GSTIN / address for the printable invoice. Same audience as the
    invoices themselves: only whoever manages billing."""
    _require_manager(actor, "share the invoices")
    return SellerOut(legal_name=settings.seller_legal_name, gstin=settings.seller_gstin,
                     address=settings.seller_address.replace("\\n", "\n"))


@router.get("/invoices", response_model=list[InvoiceOut])
def list_invoices(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), actor: BillingActor = Depends(get_billing_actor)):
    """The caller's own subscription invoices, newest first. Invoices are created by the
    `subscription.charged` webhook (services/invoices.py), never by this API. Only whoever manages
    billing sees them - a team member of an institute doesn't. Scoped through the owner's single
    Subscription row, so nobody can reach another owner's invoices."""
    _require_manager(actor, "share the invoices")
    sub = subs.get_subscription(db, actor.owner)
    if sub is None:
        return []
    rows = (db.query(Invoice).filter(Invoice.subscription_id == sub.id)
            .order_by(Invoice.issued_at.desc(), Invoice.invoice_number.desc())
            .offset(offset).limit(limit).all())
    return [_invoice_out(r) for r in rows]


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: str, db: Session = Depends(get_db),
                actor: BillingActor = Depends(get_billing_actor)):
    _require_manager(actor, "share the invoice")
    try:
        uuid.UUID(invoice_id)  # PostgreSQL raises (-> a 500) on a non-UUID id; a bad id is just "not found"
    except ValueError:
        raise HTTPException(status_code=404, detail="Invoice not found")
    sub = subs.get_subscription(db, actor.owner)
    inv = (db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.subscription_id == sub.id).first()
           if sub is not None else None)
    if inv is None:  # someone else's invoice looks exactly like one that doesn't exist
        raise HTTPException(status_code=404, detail="Invoice not found")
    return _invoice_out(inv)


@router.post("/subscribe", response_model=SubscribeResponse,
             dependencies=[Depends(rate_limit("subscribe", "rate_limit_billing_per_min"))])
def subscribe(payload: SubscribeRequest, db: Session = Depends(get_db),
              actor: BillingActor = Depends(get_billing_actor)):
    _require_manager(actor)
    require_razorpay()
    rz_plan_id = _validate_choice(payload.plan, payload.cycle)

    sub = subs.get_subscription(db, actor.owner)
    now = datetime.utcnow()
    if sub and sub.razorpay_subscription_id:
        if sub.status == "trialing":
            raise HTTPException(
                status_code=409,
                detail="You've already subscribed - your plan starts when your free trial ends.",
            )
        if (sub.status == "active" and not sub.cancel_at_period_end
                and subs.effective_plan(sub) != "free"):
            raise HTTPException(
                status_code=409,
                detail="You already have an active subscription. Use 'Change plan' instead.",
            )
        # past_due / cancelled / expired fall through on purpose: a failed-payment
        # (halted) subscription can't be revived, so the customer has to be able to
        # start a fresh one. When it activates, the old one is cancelled (see verify).

    notes = {"plan": payload.plan, "cycle": payload.cycle}
    if actor.owner.institute_id:
        notes["institute_id"] = actor.owner.institute_id
    else:
        notes["teacher_id"] = actor.owner.teacher_id

    body = {
        "plan_id": rz_plan_id,
        "total_count": plans.TOTAL_COUNT[payload.cycle],
        "quantity": 1,
        "customer_notify": 1,
        "notes": notes,
    }
    # Someone still inside a period they've already got (a free trial, or a paid period
    # they cancelled) shouldn't be charged again until it ends: the customer authorises
    # the payment method now, and Razorpay makes the first charge at start_at.
    # (Razorpay wants start_at in the future - hence the 1-day floor.)
    already_covered = sub is not None and (
        sub.status in ("trialing", "cancelled")
        or (sub.status == "active" and sub.cancel_at_period_end)
    )  # (a lapsed 'cancelled' has a past period end, so the 1-day floor below excludes it)
    if already_covered and sub.current_period_end and sub.current_period_end > now + timedelta(days=1):
        body["start_at"] = calendar.timegm(sub.current_period_end.utctimetuple())

    try:
        rz = get_razorpay_client().subscription.create(body)
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't reach the payment provider. Please try again.")

    return SubscribeResponse(
        subscription_id=rz["id"], key_id=settings.razorpay_key_id,
        plan=payload.plan, cycle=payload.cycle, name=actor.name, contact=actor.contact,
    )


@router.post("/verify", response_model=BillingStatus,
             dependencies=[Depends(rate_limit("billing-verify", "rate_limit_verify_per_min"))])
def verify_subscription(payload: VerifySubscription, db: Session = Depends(get_db),
                        actor: BillingActor = Depends(get_billing_actor)):
    """Called by the browser right after Checkout succeeds, purely so the UI reflects
    the purchase immediately instead of waiting on the webhook. Safe to race with the
    webhook: both go through the same idempotent apply function."""
    require_razorpay()
    _require_manager(actor)

    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{payload.razorpay_payment_id}|{payload.razorpay_subscription_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature check failed")

    try:
        entity = get_razorpay_client().subscription.fetch(payload.razorpay_subscription_id)
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't confirm the subscription yet. Refresh in a moment.")

    # The signature proves the payment is real, not that it's THIS owner's - check the
    # notes we attached at creation so nobody can claim someone else's subscription.
    notes = entity.get("notes") or {}
    if (notes.get("institute_id") or None) != actor.owner.institute_id or \
       (notes.get("teacher_id") or None) != actor.owner.teacher_id:
        raise HTTPException(status_code=403, detail="This subscription doesn't belong to your account")

    superseded: list = []
    subs.apply_razorpay_subscription(db, entity, superseded)
    db.commit()
    subs.cancel_superseded(get_razorpay_client(), superseded)
    return _status_for(db, actor)


@router.post("/cancel", response_model=BillingStatus)
def cancel_subscription(db: Session = Depends(get_db), actor: BillingActor = Depends(get_billing_actor)):
    """An active subscription is cancelled at the end of the paid period - they keep what
    they paid for. One that hasn't charged yet (subscribed during a trial) or that is
    failing (past_due) has no paid period to run out, so it's cancelled immediately -
    the trial itself carries on untouched."""
    _require_manager(actor)
    sub = subs.get_subscription(db, actor.owner)
    if not (sub and sub.razorpay_subscription_id and sub.status in ("active", "past_due", "trialing")):
        raise HTTPException(status_code=400, detail="There's no active subscription to cancel")
    if sub.cancel_at_period_end:
        return _status_for(db, actor)

    immediate = sub.status in ("trialing", "past_due")
    try:
        get_razorpay_client().subscription.cancel(
            sub.razorpay_subscription_id, {"cancel_at_cycle_end": 0 if immediate else 1})
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't reach the payment provider. Please try again.")

    if sub.status == "trialing":
        sub.razorpay_subscription_id = None  # trial keeps running; nothing is queued any more
    elif sub.status == "past_due":
        sub.status = "cancelled"
    else:
        sub.cancel_at_period_end = True
    sub.scheduled_plan = sub.scheduled_cycle = None
    db.commit()
    return _status_for(db, actor)


@router.post("/change-plan", response_model=BillingStatus,
             dependencies=[Depends(rate_limit("change-plan", "rate_limit_billing_per_min"))])
def change_plan(payload: SubscribeRequest, db: Session = Depends(get_db),
                actor: BillingActor = Depends(get_billing_actor)):
    """Switch plan/cycle on an existing paid subscription, effective from the next
    renewal (nobody is charged or downgraded mid-period)."""
    _require_manager(actor)
    rz_plan_id = _validate_choice(payload.plan, payload.cycle)

    sub = subs.get_subscription(db, actor.owner)
    if not (sub and sub.razorpay_subscription_id and sub.status == "active"
            and not sub.cancel_at_period_end):
        raise HTTPException(status_code=400, detail="You need an active subscription to change plan")
    if (sub.plan, sub.billing_cycle) == (payload.plan, payload.cycle):
        raise HTTPException(status_code=400, detail="You're already on this plan")

    try:
        get_razorpay_client().subscription.edit(sub.razorpay_subscription_id, {
            "plan_id": rz_plan_id, "schedule_change_at": "cycle_end", "customer_notify": 1,
        })
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't reach the payment provider. Please try again.")
    sub.scheduled_plan, sub.scheduled_cycle = payload.plan, payload.cycle
    db.commit()
    return _status_for(db, actor)


# ---------- Upgrade now (prorated) ----------
def _quote_out(q: dict) -> dict:
    return dict(
        from_plan=q["from_plan"], from_plan_label=plans.PLANS[q["from_plan"]]["label"],
        to_plan=q["to_plan"], to_plan_label=plans.PLANS[q["to_plan"]]["label"], cycle=q["cycle"],
        period_start=q["period_start"], period_end=q["period_end"],
        remaining_days=round(q["remaining_seconds"] / 86400, 2),
        credit_base_paise=q["credit_base_paise"], charge_base_paise=q["charge_base_paise"],
        base_paise=q["base_paise"], gst_rate_percent=settings.gst_rate_bps / 100,
        gst_paise=q["gst_paise"], total_paise=q["total_paise"],
    )


@router.post("/upgrade/quote", response_model=UpgradeQuote)
def upgrade_quote(payload: UpgradeRequest, db: Session = Depends(get_db),
                  actor: BillingActor = Depends(get_billing_actor)):
    """What upgrading to `plan` right now would cost for the rest of this billing period. Read
    only: nothing is created and nobody is charged."""
    _require_manager(actor)
    q = upgrades.quote(subs.get_subscription(db, actor.owner), payload.plan)
    return UpgradeQuote(**_quote_out(q))


@router.post("/upgrade", response_model=UpgradeOrder,
             dependencies=[Depends(rate_limit("upgrade", "rate_limit_billing_per_min"))])
def start_upgrade(payload: UpgradeRequest, db: Session = Depends(get_db),
                  actor: BillingActor = Depends(get_billing_actor)):
    """Starts an upgrade: creates the one-off Razorpay Order for the prorated amount. The browser
    opens Checkout with the returned order_id, then calls /billing/upgrade/verify. The plan does
    NOT change until the payment is confirmed. (A one-off order, not a subscription edit, so this
    works for UPI Autopay subscriptions too.)"""
    require_razorpay()
    _require_manager(actor, "upgrade the plan")
    sub = subs.get_subscription(db, actor.owner)
    q = upgrades.quote(sub, payload.plan)

    notes = {"kind": "plan_upgrade", "from_plan": q["from_plan"], "to_plan": q["to_plan"], "cycle": q["cycle"]}
    if actor.owner.institute_id:
        notes["institute_id"] = actor.owner.institute_id
    else:
        notes["teacher_id"] = actor.owner.teacher_id
    try:
        order = get_razorpay_client().order.create({
            "amount": q["total_paise"], "currency": "INR",
            "receipt": f"upg_{uuid.uuid4().hex[:24]}",  # never a bare UUID: the fee-payment webhook path must not mistake it for a fee id
            "notes": notes,
        })
    except Exception:
        raise HTTPException(status_code=502, detail="Couldn't start the payment. Please try again.")
    upgrades.create_pending(db, sub, q, order["id"])
    db.commit()
    return UpgradeOrder(**_quote_out(q), order_id=order["id"], key_id=settings.razorpay_key_id,
                        name=actor.name, contact=actor.contact)


@router.post("/upgrade/verify", response_model=BillingStatus,
             dependencies=[Depends(rate_limit("upgrade-verify", "rate_limit_verify_per_min"))])
def verify_upgrade(payload: VerifyUpgrade, db: Session = Depends(get_db),
                   actor: BillingActor = Depends(get_billing_actor)):
    """Called by the browser right after Checkout succeeds so the new plan shows immediately.
    Safe to race with the payment webhook: both apply the same row exactly once."""
    require_razorpay()
    _require_manager(actor, "upgrade the plan")
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature check failed")

    sub = subs.get_subscription(db, actor.owner)
    up = upgrades.find_by_order(db, payload.razorpay_order_id, lock=True)
    if up is None or sub is None or up.subscription_id != sub.id:
        # someone else's order looks exactly like one that doesn't exist
        raise HTTPException(status_code=404, detail="Upgrade not found")

    if up.status == "pending":
        # The signature proves Checkout succeeded; ask Razorpay what was actually paid so a
        # tampered browser can't claim a different order or amount.
        try:
            pay = get_razorpay_client().payment.fetch(payload.razorpay_payment_id)
        except Exception:
            raise HTTPException(status_code=502, detail="Couldn't confirm the payment yet. Refresh in a moment.")
        if pay.get("order_id") != up.razorpay_order_id:
            raise HTTPException(status_code=400, detail="This payment doesn't belong to this upgrade")
        if pay.get("status") != "captured":
            raise HTTPException(status_code=409, detail="Your payment isn't confirmed yet. Your plan "
                                                        "upgrades as soon as it is.")
        amount = pay.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise HTTPException(status_code=502, detail="Couldn't confirm the payment yet. Refresh in a moment.")
        outcome = upgrades.apply_paid(db, up, payload.razorpay_payment_id, amount,
                                      paid_at=invoices._utc(pay.get("created_at")))
    else:
        outcome = "refund_needed" if up.status == "refund_needed" else "already"
    uid, note = up.id, up.note
    db.commit()
    if outcome == "refund_needed":
        raise HTTPException(status_code=409, detail=f"We couldn't apply this upgrade ({note}). "
                                                    "Your payment will be refunded - contact support.")
    upgrades.switch_renewal(db, get_razorpay_client(), uid)  # no-op if already done
    return _status_for(db, actor)
