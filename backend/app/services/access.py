"""Account access lifecycle: paid -> 3-day buffer -> 15-day limited grace -> banned.

Pure date maths over a Subscription (access_for_subscription), plus the two guards routes use.
settings.enforcement_start None switches the whole lifecycle off (always "active").
For accounts with no live paid period the lapse clock starts at enforcement_start, never earlier.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..database import settings
from ..models import Subscription
from .subscriptions import Owner, get_subscription

MSG_PAYMENT_NON_PAYER = "This account is inactive because the plan wasn't renewed. Please contact your institute."
MSG_PAYMENT_PAYER = "Your plan wasn't renewed. Renew in Billing to restore access."
MSG_ADMIN = "This account has been suspended. Please contact Wandor support."


@dataclass(frozen=True)
class Access:
    state: str  # "active" | "grace" | "banned"
    reason: Optional[str] = None  # None | "payment" | "admin"
    grace_starts_at: Optional[datetime] = None  # set whenever the account has lapsed (even in the buffer)
    ban_at: Optional[datetime] = None


def access_for_subscription(sub: Optional[Subscription], now: Optional[datetime] = None) -> Access:
    if sub is not None and sub.admin_banned:
        return Access("banned", "admin")
    release = settings.enforcement_start
    if release is None:
        return Access("active")
    now = now or datetime.utcnow()

    # E is the end of a live paid/trial period; None means no live period (the clock starts at release).
    end = None
    if sub is not None and sub.plan != "free" and sub.status in ("trialing", "active", "past_due", "cancelled"):
        end = sub.current_period_end
        if end is None and sub.status == "active":
            return Access("active")  # open-ended paid row: nothing to lapse
    base = max(end or release, release)
    if now <= base:
        return Access("active")

    grace_starts = base + timedelta(days=settings.billing_grace_days)
    ban_at = grace_starts + timedelta(days=settings.limited_grace_days)
    if sub is not None and sub.grace_until is not None and sub.grace_until > ban_at:
        ban_at = sub.grace_until
    if now >= ban_at:
        return Access("banned", "payment", grace_starts, ban_at)
    if now >= grace_starts:
        return Access("grace", "payment", grace_starts, ban_at)
    return Access("active", None, grace_starts, ban_at)


def access_for_owner(db: Session, owner: Owner, now: Optional[datetime] = None) -> Access:
    return access_for_subscription(get_subscription(db, owner), now)


def assert_not_locked(db: Session, owner: Owner, *, billing: bool = False, payer: bool = False) -> None:
    a = access_for_owner(db, owner)
    if a.state != "banned":
        return
    if a.reason == "admin":
        raise HTTPException(status_code=403, detail=MSG_ADMIN, headers={"X-Account-Status": "banned_admin"})
    if billing:
        return  # paying is how a payment-banned account comes back
    headers = {"X-Account-Status": "banned_payment"}
    if payer:
        headers["X-Account-Can-Pay"] = "1"
    raise HTTPException(status_code=403, detail=MSG_PAYMENT_PAYER if payer else MSG_PAYMENT_NON_PAYER,
                        headers=headers)


def assert_full_access(db: Session, owner: Owner, what: str) -> None:
    if access_for_owner(db, owner).state == "grace":
        raise HTTPException(
            status_code=402,
            detail=f"{what} is paused because your plan has lapsed. Renew in Billing to turn it back on.",
        )
