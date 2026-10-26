from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AdminAuditLog, Institute, Invoice, PlatformAdmin, Student, Subscription, Teacher
from ..schemas import (
    AdminAccount, AdminBan, AdminExtendGrace, AdminLogin, AdminMoney, AdminRevenue, AdminStats, Token,
)
from ..auth import verify_password, create_access_token, get_current_platform_admin
from ..services.access import access_for_subscription
from ..timeutil import month_start_utc, utcnow
from ..ratelimit import rate_limit

router = APIRouter(prefix="/admin", tags=["admin"])

_login_limit = [Depends(rate_limit("login", "rate_limit_login_per_min"))]


@router.post("/login", response_model=Token, dependencies=_login_limit)
def admin_login(payload: AdminLogin, db: Session = Depends(get_db)):
    admin = db.query(PlatformAdmin).filter(PlatformAdmin.phone == payload.phone).first()
    if not admin or not verify_password(payload.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    return Token(access_token=create_access_token(admin.id, role="platform_admin"))


# ---------- dashboard API ----------
_STATUS_FILTERS = ("all", "active", "grace", "banned", "trial")


def _is_live_trial(sub: Subscription, now: datetime) -> bool:
    return sub.status == "trialing" and sub.current_period_end is not None and sub.current_period_end > now


def _is_paying(sub: Subscription) -> bool:
    """A paid plan (not free, not a trial). Headline paying_accounts = rows with this AND access active/grace."""
    return sub.plan != "free" and sub.status in ("active", "past_due", "cancelled")


def _row(sub: Subscription, name: str, phone: str, kind: str, now: datetime) -> dict:
    a = access_for_subscription(sub, now)
    return {
        "subscription_id": sub.id, "kind": kind, "name": name, "phone": phone,
        "plan": sub.plan, "status": sub.status, "is_paying": _is_paying(sub), "access_state": a.state, "access_reason": a.reason,
        "current_period_end": sub.current_period_end, "ban_at": a.ban_at,
        "admin_banned": bool(sub.admin_banned), "admin_ban_reason": sub.admin_ban_reason,
    }


def _account_rows(db: Session, now: datetime) -> list:
    rows = []
    for sub, inst in (db.query(Subscription, Institute).join(Institute, Subscription.institute_id == Institute.id)):
        rows.append((sub, _row(sub, inst.name, inst.owner_phone, "institute", now)))
    for sub, t in (db.query(Subscription, Teacher).join(Teacher, Subscription.teacher_id == Teacher.id)):
        rows.append((sub, _row(sub, t.name, t.phone, "teacher", now)))
    rows.sort(key=lambda r: (r[0].created_at or datetime.min, r[0].id), reverse=True)
    return rows


def _account_out(db: Session, sub: Subscription, now: datetime) -> dict:
    if sub.institute_id:
        inst = db.query(Institute).filter(Institute.id == sub.institute_id).one()
        return _row(sub, inst.name, inst.owner_phone, "institute", now)
    t = db.query(Teacher).filter(Teacher.id == sub.teacher_id).one()
    return _row(sub, t.name, t.phone, "teacher", now)


def _money(db: Session, *conds) -> AdminMoney:
    base, gst = db.query(func.coalesce(func.sum(Invoice.base_paise), 0),
                         func.coalesce(func.sum(Invoice.gst_paise), 0)).filter(*conds).one()
    return AdminMoney(base_paise=int(base), gst_paise=int(gst))


@router.get("/stats", response_model=AdminStats)
def admin_stats(db: Session = Depends(get_db), _admin: PlatformAdmin = Depends(get_current_platform_admin)):
    now = utcnow()
    week_ago = now - timedelta(days=7)
    paying = sum(1 for sub in db.query(Subscription)
                 if _is_paying(sub) and access_for_subscription(sub, now).state in ("active", "grace"))
    count = lambda col, *c: db.query(func.count(col)).filter(*c).scalar() or 0
    total_users = (count(Teacher.id) + count(Institute.id) + count(Student.id)
                   + count(Student.id, Student.parent_pin_hash.isnot(None)))
    gained = (count(Teacher.id, Teacher.created_at >= week_ago) + count(Institute.id, Institute.created_at >= week_ago)
              + count(Student.id, Student.created_at >= week_ago))
    return AdminStats(
        paying_accounts=paying, total_users=total_users, users_gained_week=gained,
        revenue=AdminRevenue(total=_money(db), week=_money(db, Invoice.issued_at >= week_ago),
                             month=_money(db, Invoice.issued_at >= month_start_utc(now))),
    )


@router.get("/accounts", response_model=List[AdminAccount])
def admin_accounts(status: str = "all", db: Session = Depends(get_db),
                   _admin: PlatformAdmin = Depends(get_current_platform_admin)):
    if status not in _STATUS_FILTERS:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(_STATUS_FILTERS)}")
    now = utcnow()
    out = []
    for sub, row in _account_rows(db, now):
        trial = _is_live_trial(sub, now)
        if status == "trial":
            ok = trial
        elif status == "all":
            ok = True
        else:
            ok = row["access_state"] == status and not trial
        if ok:
            out.append(row)
    return out


def _locked_sub(db: Session, subscription_id: str) -> Subscription:
    sub = db.query(Subscription).filter(Subscription.id == subscription_id).with_for_update().first()
    if sub is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return sub


def _audit(db: Session, admin: PlatformAdmin, action: str, sub: Subscription, old: str, new: str, note):
    db.add(AdminAuditLog(admin_id=admin.id, action=action, subscription_id=sub.id,
                         old_value=old, new_value=new, note=note))


@router.post("/accounts/{subscription_id}/extend-grace", response_model=AdminAccount)
def admin_extend_grace(subscription_id: str, payload: AdminExtendGrace, db: Session = Depends(get_db),
                       admin: PlatformAdmin = Depends(get_current_platform_admin)):
    sub = _locked_sub(db, subscription_id)
    now = utcnow()
    a = access_for_subscription(sub, now)
    if sub.admin_banned:
        raise HTTPException(status_code=400, detail="This account is banned manually; lift the ban first")
    if a.state == "active":
        raise HTTPException(status_code=400, detail="This account is still active; there is no grace to extend")
    if payload.until <= now or (a.ban_at is not None and payload.until <= a.ban_at):
        raise HTTPException(status_code=400, detail="The new date must be in the future and after the current ban date")
    old = a.ban_at.isoformat() if a.ban_at else None
    sub.grace_until = payload.until
    _audit(db, admin, "extend_grace", sub, old, payload.until.isoformat(), payload.note)
    db.commit()
    return _account_out(db, sub, utcnow())


# Any account (subscription id) may be banned, trial or free tier included; ids are subscriptions, so
# students, parents and teachers inside an institute can never be targeted.
@router.post("/accounts/{subscription_id}/ban", response_model=AdminAccount)
def admin_ban(subscription_id: str, payload: AdminBan, db: Session = Depends(get_db),
              admin: PlatformAdmin = Depends(get_current_platform_admin)):
    sub = _locked_sub(db, subscription_id)
    if sub.admin_banned:
        raise HTTPException(status_code=400, detail="This account is already banned")
    sub.admin_banned = True
    sub.admin_ban_reason = payload.reason
    sub.admin_banned_at = utcnow()
    _audit(db, admin, "ban", sub, "not_banned", "banned", payload.reason)
    db.commit()
    return _account_out(db, sub, utcnow())


@router.post("/accounts/{subscription_id}/lift-ban", response_model=AdminAccount)
def admin_lift_ban(subscription_id: str, db: Session = Depends(get_db),
                   admin: PlatformAdmin = Depends(get_current_platform_admin)):
    sub = _locked_sub(db, subscription_id)
    if not sub.admin_banned:
        raise HTTPException(status_code=400, detail="This account is not banned manually")
    reason = sub.admin_ban_reason
    sub.admin_banned = False
    sub.admin_ban_reason = None
    sub.admin_banned_at = None
    _audit(db, admin, "lift_ban", sub, "banned", "not_banned", reason)
    db.commit()
    return _account_out(db, sub, utcnow())
