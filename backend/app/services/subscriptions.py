"""SaaS subscription logic - what an institute / independent teacher pays the platform.

Three rules that everything here protects:

1. The payer is an *Owner*: an institute (pays for its whole team) OR an independent
   teacher (no Institute row exists for them). An institute-affiliated teacher is never
   their own payer - their entitlements are their institute's.
2. What plan someone is entitled to is decided in exactly one place -
   effective_plan(). Nothing else reads Subscription.plan directly for gating.
3. Being over a limit never breaks existing data. Limits only block ADDING more
   students/teachers, so a downgrade or a lapsed subscription can't lock anyone out
   of what they already have.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import plans
from ..database import settings
from ..models import Subscription, Student, Teacher, Institute, PlanUpgrade

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Owner:
    institute_id: Optional[str] = None
    teacher_id: Optional[str] = None


def owner_for_teacher(teacher: Teacher) -> Owner:
    if teacher.institute_id is not None:
        return Owner(institute_id=teacher.institute_id)
    return Owner(teacher_id=teacher.id)


def owner_for_institute(institute: Institute) -> Owner:
    return Owner(institute_id=institute.id)


def owner_for_student(student: Student) -> Optional[Owner]:
    if student.institute_id is not None:
        return Owner(institute_id=student.institute_id)
    if student.teacher_id is not None:
        return Owner(teacher_id=student.teacher_id)
    return None


# ---------- Rows ----------
def get_subscription(db: Session, owner: Owner) -> Optional[Subscription]:
    q = db.query(Subscription)
    if owner.institute_id is not None:
        return q.filter(Subscription.institute_id == owner.institute_id).first()
    return q.filter(Subscription.teacher_id == owner.teacher_id).first()


def get_or_create_subscription(db: Session, owner: Owner) -> Subscription:
    sub = get_subscription(db, owner)
    if sub is None:
        sub = Subscription(
            institute_id=owner.institute_id, teacher_id=owner.teacher_id,
            plan="free", status="active",
        )
        db.add(sub)
        db.flush()
    return sub


def start_trial(db: Session, owner: Owner) -> None:
    """Called once, when a new institute/independent teacher finishes phone
    verification. Always leaves the owner with a Subscription row (the platform admin
    panel and the access lifecycle work on rows): a trial when trials are on, else a
    free/active row. No-op if the owner already has a row (so a repeat call can never
    restart a trial)."""
    if get_subscription(db, owner) is not None:
        return
    if settings.trial_days <= 0:
        sub = Subscription(institute_id=owner.institute_id, teacher_id=owner.teacher_id,
                           plan="free", status="active")
    else:
        sub = Subscription(
            institute_id=owner.institute_id, teacher_id=owner.teacher_id,
            plan=plans.TRIAL_PLAN, status="trialing",
            current_period_end=datetime.utcnow() + timedelta(days=settings.trial_days),
        )
    db.add(sub)
    db.flush()
    _mirror_institute_plan(db, sub)


# ---------- Entitlement ----------
def effective_plan(sub: Optional[Subscription], now: Optional[datetime] = None) -> str:
    """The plan this owner may use RIGHT NOW. Falls back to 'free' whenever a paid
    plan isn't currently backed by a live trial/payment (and a brief grace window
    after a failed renewal, so a card hiccup doesn't instantly lock a coaching centre
    out of features mid-month)."""
    if sub is None or sub.plan == "free":
        return "free"
    now = now or datetime.utcnow()
    end = sub.current_period_end
    grace = timedelta(days=settings.billing_grace_days)

    if sub.status == "trialing":
        entitled = end is not None and end > now
    elif sub.status == "active":
        # Tolerate a late/missed renewal webhook for the grace window, not forever.
        entitled = end is None or now <= end + grace
    elif sub.status == "past_due":
        entitled = end is not None and now <= end + grace
    elif sub.status == "cancelled":
        # Cancelled at cycle end: they paid for this period, so honour it.
        entitled = end is not None and end > now
    else:  # pending / expired
        entitled = False
    return sub.plan if entitled else "free"


def plan_for_owner(db: Session, owner: Owner) -> str:
    sub = get_subscription(db, owner)
    from . import access  # local import: access.py imports this module
    if access.access_for_subscription(sub).state == "grace":
        # Limited grace switches off attendance/tests/analytics only; fee collection and
        # reminders stay on, so keep the paid plan (or the trial plan) here.
        return sub.plan if sub is not None and sub.plan in plans.PAID_PLAN_KEYS else plans.TRIAL_PLAN
    return effective_plan(sub)


# ---------- Usage + limits ----------
def usage(db: Session, owner: Owner) -> dict:
    if owner.institute_id is not None:
        students = db.query(Student).filter(Student.institute_id == owner.institute_id).count()
        teachers = db.query(Teacher).filter(Teacher.institute_id == owner.institute_id).count()
    else:
        students = db.query(Student).filter(
            Student.institute_id.is_(None), Student.teacher_id == owner.teacher_id
        ).count()
        teachers = 1
    return {"students": students, "teachers": teachers}


def _plan_error(message: str) -> HTTPException:
    # 402 Payment Required + a plain-string detail: every existing page renders
    # err.response.data.detail as text, so this needs to stay a string.
    return HTTPException(status_code=402, detail=message)


def student_capacity(db: Session, owner: Owner) -> Optional[int]:
    """How many more students can be added; None = unlimited."""
    limit = plans.limits(plan_for_owner(db, owner))["max_students"]
    if limit is None:
        return None
    return max(0, limit - usage(db, owner)["students"])


def assert_can_add_students(db: Session, owner: Owner, count: int = 1) -> None:
    room = student_capacity(db, owner)
    if room is not None and count > room:
        p = plans.limits(plan_for_owner(db, owner))
        raise _plan_error(
            f"Your {p['label']} plan allows up to {p['max_students']} students. "
            "Upgrade your plan in Billing to add more."
        )


def assert_can_add_teacher(db: Session, owner: Owner) -> None:
    p = plans.limits(plan_for_owner(db, owner))
    limit = p["max_teachers"]
    if limit is not None and usage(db, owner)["teachers"] >= limit:
        raise _plan_error(
            f"Your {p['label']} plan allows up to {limit} teacher{'s' if limit != 1 else ''}. "
            "Upgrade your plan in Billing to add more."
        )


def has_feature(db: Session, owner: Owner, feature: str) -> bool:
    return bool(plans.limits(plan_for_owner(db, owner)).get(feature))


def assert_feature(db: Session, owner: Owner, feature: str, message: str) -> None:
    if not has_feature(db, owner, feature):
        raise _plan_error(message)


# ---------- Razorpay -> our rows ----------
# Razorpay's subscription statuses mapped onto ours. 'created'/'authenticated' both
# mean "customer hasn't been charged yet".
_RZ_STATUS = {
    "created": "pending", "authenticated": "pending",
    "active": "active",
    "pending": "past_due", "halted": "past_due", "paused": "past_due",
    "cancelled": "cancelled",
    "completed": "expired", "expired": "expired",
}


def apply_razorpay_subscription(db: Session, entity: dict,
                                superseded: Optional[list] = None) -> Optional[Subscription]:
    """Idempotently syncs our Subscription row from a Razorpay subscription entity
    (from a webhook payload OR a direct subscription.fetch()). Same entity applied
    twice gives the same row, which is what makes webhook redelivery + the instant
    /billing/verify sync safe to run together.

    Ownership comes from the `notes` we attach at creation (institute_id / teacher_id),
    not from anything the browser sends. Does NOT commit - caller does.

    `superseded`: if a NEW subscription takes over a row that was still running an
    older one (customer re-subscribed after a failed payment), the old Razorpay id is
    appended here so the caller can cancel it after committing - otherwise the old one
    keeps billing the customer in parallel."""
    rz_id = entity.get("id")
    if not rz_id:
        return None
    rz_status = entity.get("status", "")
    mapped = _RZ_STATUS.get(rz_status)
    if mapped is None:
        return None

    sub = db.query(Subscription).filter(Subscription.razorpay_subscription_id == rz_id).first()
    if sub is None:
        notes = entity.get("notes") or {}
        institute_id = notes.get("institute_id") or None
        teacher_id = notes.get("teacher_id") or None
        if bool(institute_id) == bool(teacher_id):
            return None  # not one of ours
        exists = (
            db.query(Institute.id).filter(Institute.id == institute_id).first()
            if institute_id else db.query(Teacher.id).filter(Teacher.id == teacher_id).first()
        )
        if not exists:
            return None
        owner = Owner(institute_id=institute_id, teacher_id=teacher_id)
        current = get_subscription(db, owner)

        if mapped == "pending":
            # 'authenticated' = the customer authorised a payment method but the first
            # charge is scheduled for later (someone subscribing DURING their trial).
            # Remember it - otherwise the UI can't show it, it can't be cancelled, and
            # the customer can buy a second subscription. The trial itself is untouched.
            if (rz_status == "authenticated" and current is not None
                    and current.status == "trialing" and current.razorpay_subscription_id is None):
                current.razorpay_subscription_id = rz_id
                found = plans.plan_from_razorpay_plan_id(entity.get("plan_id", ""))
                if found:
                    current.scheduled_plan, current.scheduled_cycle = found
                return current
            return None
        if mapped != "active":
            return None  # e.g. a stale cancellation of an OLD subscription: not our concern

        sub = get_or_create_subscription(db, owner)
        old = sub.razorpay_subscription_id
        if old and old != rz_id and sub.status in ("active", "past_due") and superseded is not None:
            superseded.append(old)
        sub.razorpay_subscription_id = rz_id
        sub.cancel_at_period_end = False
        sub.scheduled_plan = sub.scheduled_cycle = None
    elif mapped == "pending" and sub.status == "trialing":
        return sub  # 'authenticated' echo for a subscription that starts after the trial

    found = plans.plan_from_razorpay_plan_id(entity.get("plan_id", ""))
    if found:
        held = held_plan(db, sub, entity.get("current_end"))
        if held and plans.PLAN_ORDER.index(held[0]) > plans.PLAN_ORDER.index(found[0]):
            found = held  # a paid "upgrade now" outranks Razorpay's still-old plan_id for this period
        sub.plan, sub.billing_cycle = found
    sub.status = mapped
    current_end = entity.get("current_end")
    if current_end:
        sub.current_period_end = datetime.utcfromtimestamp(int(current_end))
    if sub.scheduled_plan and sub.plan == sub.scheduled_plan:
        sub.scheduled_plan = sub.scheduled_cycle = None  # the queued change has now taken effect
    if mapped in ("cancelled", "expired"):
        sub.cancel_at_period_end = False
    if (sub.status == "active" and sub.current_period_end is not None
            and sub.current_period_end > datetime.utcnow()):
        sub.grace_until = None  # a payment ends the lapse; a founder extension must not outlive it
    _mirror_institute_plan(db, sub)
    return sub


def held_plan(db: Session, sub: Subscription, entity_end) -> Optional[tuple[str, str]]:
    """(plan, cycle) that a PAID "upgrade now" keeps in force for the billing period that ends at
    `entity_end` (Razorpay's current_end, unix seconds; the row's own period end if absent).

    Why: after an upgrade Razorpay's subscription still carries the OLD plan_id until the next
    renewal (or for good, for a UPI subscription it will not let us edit), so every sync of that
    subscription would otherwise put the customer straight back on the plan they just paid to
    leave. Once the period rolls over the end no longer matches and Razorpay's plan wins again."""
    if sub is None or sub.id is None:
        return None
    try:
        end = datetime.utcfromtimestamp(int(entity_end)) if entity_end else sub.current_period_end
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if end is None:
        return None
    row = (db.query(PlanUpgrade)
           .filter(PlanUpgrade.subscription_id == sub.id, PlanUpgrade.status == "applied",
                   PlanUpgrade.period_end == end)
           .order_by(PlanUpgrade.applied_at.desc()).first())
    return (row.to_plan, row.billing_cycle) if row else None


def cancel_superseded(client, subscription_ids: list) -> None:
    """Best-effort cancel of subscriptions a new one replaced. A failure here is logged,
    not raised: the customer's new plan is already active and the webhook must still
    succeed - an operator can cancel the leftover from the Razorpay dashboard."""
    for sid in subscription_ids:
        try:
            client.subscription.cancel(sid, {"cancel_at_cycle_end": 0})
        except Exception:
            logger.error("SUPERSEDED_SUBSCRIPTION_NOT_CANCELLED %s - cancel it in the Razorpay dashboard", sid)


def _mirror_institute_plan(db: Session, sub: Subscription) -> None:
    """Institute.plan predates subscriptions and is still what older readers show;
    keep it in step. The value that matters for gating is always effective_plan()."""
    if sub.institute_id:
        inst = db.query(Institute).filter(Institute.id == sub.institute_id).first()
        if inst:
            inst.plan = effective_plan(sub)
