"""Platform-admin identity: login, token role isolation in both directions, CLI script."""
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from fastapi import Depends

from tests.test_billing_flow import (  # noqa: F401  (import sets the throwaway DB env)
    app, client, SessionLocal, mk_teacher, mk_institute, mk_student, _phone,
)
from app.auth import create_access_token, hash_password, get_current_platform_admin
from app.database import settings
from app.models import (
    AdminAuditLog, Institute, Invoice, PlatformAdmin, Student, Subscription, Teacher,
)
from app.timeutil import month_start_utc

ADMIN_PW = "admin-pw-123"


def mk_admin():
    db = SessionLocal()
    a = PlatformAdmin(phone=_phone(), hashed_password=hash_password(ADMIN_PW))
    db.add(a)
    db.commit()
    aid, phone = a.id, a.phone
    db.close()
    return aid, phone, {"Authorization": f"Bearer {create_access_token(aid, 'platform_admin')}"}


# Task 5 adds the real /admin/* endpoints; until then probe the dependency directly.
def _probe(admin=Depends(get_current_platform_admin)):
    return {"id": admin.id}


if not any(getattr(r, "path", "") == "/admin/_probe" for r in app.routes):
    app.add_api_route("/admin/_probe", _probe, methods=["GET"])


def test_login_returns_token_accepted_by_dependency():
    aid, phone, _ = mk_admin()
    r = client.post("/admin/login", json={"phone": phone, "password": ADMIN_PW})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    p = client.get("/admin/_probe", headers={"Authorization": f"Bearer {tok}"})
    assert p.status_code == 200 and p.json()["id"] == aid


def test_login_normalises_phone():
    _, phone, _ = mk_admin()
    r = client.post("/admin/login", json={"phone": f"+91 {phone}", "password": ADMIN_PW})
    assert r.status_code == 200, r.text


def test_wrong_password_and_unknown_phone_401():
    _, phone, _ = mk_admin()
    r = client.post("/admin/login", json={"phone": phone, "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "Wrong phone number or password"
    r = client.post("/admin/login", json={"phone": "9111111111", "password": ADMIN_PW})
    assert r.status_code == 401 and r.json()["detail"] == "Wrong phone number or password"


def test_admin_token_rejected_by_existing_dependencies():
    _, _, ah = mk_admin()
    for path in ("/students", "/institute/me", "/billing/me", "/classes"):
        assert client.get(path, headers=ah).status_code == 401, path


def test_other_roles_rejected_by_admin_dependency():
    _, th = mk_teacher()
    _, ih = mk_institute()
    sid, sh = mk_student()
    parent = {"Authorization": f"Bearer {create_access_token(sid, 'parent')}"}
    for h in (th, ih, sh, parent):
        assert client.get("/admin/_probe", headers=h).status_code == 401
    assert client.get("/admin/_probe").status_code == 401


def test_deleted_admin_token_rejected():
    aid, _, ah = mk_admin()
    db = SessionLocal()
    db.query(PlatformAdmin).filter(PlatformAdmin.id == aid).delete()
    db.commit()
    db.close()
    assert client.get("/admin/_probe", headers=ah).status_code == 401


def test_create_script_creates_then_updates_and_normalises():
    import os
    from app.database import settings
    env = dict(os.environ, DATABASE_URL=str(settings.database_url))
    phone = _phone()
    def run(p, pw):
        return subprocess.run([sys.executable, "-m", "scripts.create_platform_admin", p, pw],
                              capture_output=True, text=True, env=env,
                              cwd=os.path.dirname(os.path.dirname(__file__)))
    r = run(f"+91 {phone}", "first-pw-1")
    assert r.returncode == 0, r.stderr
    assert client.post("/admin/login", json={"phone": phone, "password": "first-pw-1"}).status_code == 200
    r = run(phone, "second-pw-2")
    assert r.returncode == 0, r.stderr
    db = SessionLocal()
    assert db.query(PlatformAdmin).filter(PlatformAdmin.phone == phone).count() == 1
    db.close()
    assert client.post("/admin/login", json={"phone": phone, "password": "first-pw-1"}).status_code == 401
    assert client.post("/admin/login", json={"phone": phone, "password": "second-pw-2"}).status_code == 200


# ---------------- Task 5: dashboard API ----------------
D = timedelta


@pytest.fixture
def lifecycle(monkeypatch):
    monkeypatch.setattr(settings, "enforcement_start", datetime.utcnow() - D(days=100))
    monkeypatch.setattr(settings, "billing_grace_days", 3)
    monkeypatch.setattr(settings, "limited_grace_days", 15)


def _seed_owner(kind, plan="basic", status="active", end=None, name=None, **sub_kw):
    """Insert an institute/teacher + its subscription directly. Returns (sub_id, owner_id)."""
    db = SessionLocal()
    if kind == "institute":
        o = Institute(name=name or "Inst X", owner_phone=_phone(), hashed_password="x")
    else:
        o = Teacher(name=name or "Teach X", phone=_phone(), hashed_password="x")
    db.add(o)
    db.commit()
    sub = Subscription(plan=plan, status=status, current_period_end=end,
                       institute_id=o.id if kind == "institute" else None,
                       teacher_id=o.id if kind == "teacher" else None, **sub_kw)
    db.add(sub)
    db.commit()
    ids = (sub.id, o.id)
    db.close()
    return ids


def _invoice(sub_id, issued_at, base, gst):
    db = SessionLocal()
    db.add(Invoice(invoice_number=f"T5/{uuid.uuid4().hex}", subscription_id=sub_id, plan="basic",
                   gst_rate_bps=1800, base_paise=base, gst_paise=gst, total_paise=base + gst,
                   issued_at=issued_at))
    db.commit()
    db.close()


def _stats(ah):
    r = client.get("/admin/stats", headers=ah)
    assert r.status_code == 200, r.text
    return r.json()


def _ist_month_start_utc(now):
    ist = timezone(timedelta(hours=5, minutes=30))
    local = now.replace(tzinfo=timezone.utc).astimezone(ist)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)


def _seed_five():
    now = datetime.utcnow()
    return {
        "trial": _seed_owner("institute", plan="pro", status="trialing", end=now + D(days=10))[0],
        "paid": _seed_owner("teacher", end=now + D(days=20))[0],
        "grace": _seed_owner("institute", end=now - D(days=10))[0],
        "pban": _seed_owner("teacher", end=now - D(days=30))[0],
        "aban": _seed_owner("institute", end=now + D(days=20), admin_banned=True,
                            admin_ban_reason="fraud", admin_banned_at=now)[0],
    }


def _acct(ah, sid, status="all"):
    rows = client.get(f"/admin/accounts?status={status}", headers=ah).json()
    return next((r for r in rows if r["subscription_id"] == sid), None)


def _audit_rows(sid):
    db = SessionLocal()
    rows = db.query(AdminAuditLog).filter(AdminAuditLog.subscription_id == sid).order_by(AdminAuditLog.created_at).all()
    out = [(r.action, r.old_value, r.new_value, r.note, r.admin_id) for r in rows]
    db.close()
    return out


def _sub_state(sid):
    db = SessionLocal()
    s = db.query(Subscription).filter(Subscription.id == sid).one()
    out = (s.grace_until, s.admin_banned, s.admin_ban_reason, s.admin_banned_at)
    db.close()
    return out


def test_stats_requires_platform_admin():
    _, th = mk_teacher()
    _, ih = mk_institute()
    sid, sh = mk_student()
    parent = {"Authorization": f"Bearer {create_access_token(sid, 'parent')}"}
    assert client.get("/admin/stats").status_code == 401
    for h in (th, ih, sh, parent):
        assert client.get("/admin/stats", headers=h).status_code == 401
    assert client.get("/admin/accounts").status_code == 401


def test_month_start_utc_uses_kolkata():
    assert month_start_utc(datetime(2026, 10, 24, 12, 0)) == datetime(2026, 9, 30, 18, 30)
    assert month_start_utc(datetime(2026, 10, 31, 19, 0)) == datetime(2026, 10, 31, 18, 30)  # already Nov 1 in IST
    assert month_start_utc(datetime(2026, 10, 31, 18, 29)) == datetime(2026, 9, 30, 18, 30)


def test_stats_numbers(lifecycle):
    _, _, ah = mk_admin()
    before = _stats(ah)
    now = datetime.utcnow()
    seeds = _seed_five()
    # users: 1 institute + 1 teacher (+ owners above: 3 institutes + 2 teachers), students below
    db = SessionLocal()
    old = now - D(days=30)
    db.add_all([
        Student(name="a", phone=_phone(), hashed_password="x", created_at=now),                       # gained
        Student(name="b", phone=_phone(), hashed_password="x", created_at=old, parent_pin_hash="h"),  # old + parent
        Student(name="c", phone=_phone(), hashed_password="x", parent_pin_hash="h"),  # null date + parent
        Teacher(name="t", phone=_phone(), hashed_password="x"),                       # never gained
    ])
    db.commit()
    # an explicit None gets the column default on insert, so null the dates afterwards (legacy rows)
    db.query(Student).filter(Student.name == "c").update({"created_at": None})
    db.query(Teacher).filter(Teacher.name == "t").update({"created_at": None})
    db.commit()
    db.close()
    _invoice(seeds["paid"], now - D(minutes=5), 1000, 180)
    _invoice(seeds["paid"], now - D(days=3), 2000, 360)
    _invoice(seeds["grace"], now - D(days=40), 4000, 720)
    after = _stats(ah)

    assert after["paying_accounts"] - before["paying_accounts"] == 2  # paid + grace; not trial / banned
    # 3 institutes + 2 teachers (seed) + 3 students + 1 teacher + 2 parents
    assert after["total_users"] - before["total_users"] == 3 + 2 + 3 + 1 + 2
    # gained: 3 institutes + 2 teachers (created_at default now) + student a; null-date rows and parents excluded
    assert after["users_gained_week"] - before["users_gained_week"] == 3 + 2 + 1

    def d(k, f):
        return after["revenue"][k][f] - before["revenue"][k][f]
    assert (d("total", "base_paise"), d("total", "gst_paise")) == (7000, 1260)
    assert (d("week", "base_paise"), d("week", "gst_paise")) == (3000, 540)
    ms = _ist_month_start_utc(now)
    exp_m = [(1000, 180)] + ([(2000, 360)] if now - D(days=3) >= ms else [])
    assert (d("month", "base_paise"), d("month", "gst_paise")) == (sum(b for b, _ in exp_m), sum(g for _, g in exp_m))


def test_stats_month_boundary_is_kolkata(lifecycle):
    _, _, ah = mk_admin()
    sid = _seed_owner("teacher")[0]
    ms = _ist_month_start_utc(datetime.utcnow())  # e.g. 18:30 UTC on the last day of the previous month
    before = _stats(ah)["revenue"]["month"]
    _invoice(sid, ms + D(minutes=1), 500, 90)   # 00:01 IST on the 1st: this month
    _invoice(sid, ms - D(minutes=1), 7000, 1260)  # 23:59 IST the day before: last month
    after = _stats(ah)["revenue"]["month"]
    assert after["base_paise"] - before["base_paise"] == 500
    assert after["gst_paise"] - before["gst_paise"] == 90


def test_accounts_list_and_filters(lifecycle):
    _, _, ah = mk_admin()
    seeds = _seed_five()
    expect = {"trial": ("active", "trial"), "paid": ("active", "active"), "grace": ("grace", "grace"),
              "pban": ("banned", "banned"), "aban": ("banned", "banned")}
    for key, (state, flt) in expect.items():
        row = _acct(ah, seeds[key])
        assert row is not None and row["access_state"] == state, key
        for f in ("active", "grace", "banned", "trial"):
            present = _acct(ah, seeds[key], f) is not None
            assert present == (f == flt), (key, f)
    rows = {k: _acct(ah, v) for k, v in seeds.items()}
    assert rows["pban"]["kind"] == "teacher" and rows["pban"]["access_reason"] == "payment"
    assert rows["pban"]["name"] == "Teach X" and rows["pban"]["phone"]
    assert rows["aban"]["kind"] == "institute" and rows["aban"]["access_reason"] == "admin"
    assert rows["aban"]["admin_banned"] and rows["aban"]["admin_ban_reason"] == "fraud"
    assert rows["grace"]["ban_at"].endswith("Z") and rows["grace"]["current_period_end"].endswith("Z")
    assert rows["paid"]["plan"] == "basic" and rows["paid"]["status"] == "active"
    # newest first
    ids = [r["subscription_id"] for r in client.get("/admin/accounts", headers=ah).json()]
    pos = [ids.index(seeds[k]) for k in ("aban", "pban", "grace", "paid", "trial")]
    assert pos == sorted(pos)


def test_accounts_unknown_status_422():
    _, _, ah = mk_admin()
    assert client.get("/admin/accounts?status=bogus", headers=ah).status_code == 422


def test_extend_grace_happy_path_grace_account(lifecycle):
    aid, _, ah = mk_admin()
    sid = _seed_five()["grace"]
    before = _acct(ah, sid)
    until = datetime.utcnow() + D(days=30)
    r = client.post(f"/admin/accounts/{sid}/extend-grace", headers=ah,
                    json={"until": until.isoformat() + "Z", "note": "paying Friday"})
    assert r.status_code == 200, r.text
    assert r.json()["access_state"] == "grace" and r.json()["ban_at"].startswith(until.isoformat()[:19])
    assert _sub_state(sid)[0] == until
    rows = _audit_rows(sid)
    assert len(rows) == 1
    assert rows[0][0] == "extend_grace" and rows[0][3] == "paying Friday" and rows[0][4] == aid
    assert rows[0][2] == until.isoformat()
    assert datetime.fromisoformat(rows[0][1]) == datetime.fromisoformat(before["ban_at"].rstrip("Z"))


def test_extend_grace_revives_payment_banned(lifecycle):
    _, _, ah = mk_admin()
    sid = _seed_five()["pban"]
    until = datetime.utcnow() + D(days=5)
    r = client.post(f"/admin/accounts/{sid}/extend-grace", headers=ah, json={"until": until.isoformat() + "Z"})
    assert r.status_code == 200, r.text
    assert r.json()["access_state"] == "grace"
    assert len(_audit_rows(sid)) == 1


def test_extend_grace_invalid_cases_400_no_change(lifecycle):
    _, _, ah = mk_admin()
    seeds = _seed_five()
    now = datetime.utcnow()
    grace_ban_at = datetime.fromisoformat(_acct(ah, seeds["grace"])["ban_at"].rstrip("Z"))

    def post(sid, until, **kw):
        return client.post(f"/admin/accounts/{sid}/extend-grace", headers=ah,
                           json={"until": until.isoformat() + "Z", **kw})
    cases = [
        (seeds["paid"], now + D(days=60)),        # active
        (seeds["trial"], now + D(days=60)),       # active (trial)
        (seeds["aban"], now + D(days=60)),        # manually banned
        (seeds["grace"], now - D(days=1)),        # in the past
        (seeds["grace"], grace_ban_at),           # equal to current ban_at
        (seeds["grace"], grace_ban_at - D(days=1)),  # before current ban_at
        (seeds["pban"], now - D(minutes=1)),      # banned, until in the past
    ]
    for sid, until in cases:
        r = post(sid, until)
        assert r.status_code == 400 and isinstance(r.json()["detail"], str), (sid, until, r.text)
        assert _sub_state(sid)[0] is None and _audit_rows(sid) == []
    # buffer: lapsed 1 day ago, still "active" -> 400
    buf = _seed_owner("teacher", end=now - D(days=1))[0]
    assert post(buf, now + D(days=60)).status_code == 400 and _audit_rows(buf) == []
    # note too long -> 422, unknown id -> 404
    assert post(seeds["grace"], now + D(days=60), note="x" * 301).status_code == 422
    assert post(str(uuid.uuid4()), now + D(days=60)).status_code == 404
    assert _audit_rows(seeds["grace"]) == []


def test_ban_and_lift_happy_path(lifecycle):
    aid, _, ah = mk_admin()
    sid = _seed_five()["paid"]
    r = client.post(f"/admin/accounts/{sid}/ban", headers=ah, json={"reason": "  chargeback abuse  "})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["access_state"] == "banned" and j["access_reason"] == "admin"
    assert j["admin_banned"] and j["admin_ban_reason"] == "chargeback abuse"
    g, banned, reason, at = _sub_state(sid)
    assert banned and reason == "chargeback abuse" and at is not None
    assert _acct(ah, sid, "banned") is not None

    r = client.post(f"/admin/accounts/{sid}/lift-ban", headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["access_state"] == "active" and not r.json()["admin_banned"]
    assert _sub_state(sid) == (None, False, None, None)
    rows = _audit_rows(sid)
    assert [(a, o, n, note) for a, o, n, note, _ in rows] == [
        ("ban", "not_banned", "banned", "chargeback abuse"),
        ("lift_ban", "banned", "not_banned", "chargeback abuse"),
    ]
    assert all(x[4] == aid for x in rows)


def test_ban_lift_invalid_cases_400_no_change(lifecycle):
    _, _, ah = mk_admin()
    seeds = _seed_five()
    for reason in ("", "   ", "x" * 301):
        r = client.post(f"/admin/accounts/{seeds['paid']}/ban", headers=ah, json={"reason": reason})
        assert r.status_code == 422, reason
    assert client.post(f"/admin/accounts/{seeds['paid']}/ban", headers=ah, json={}).status_code == 422
    assert _sub_state(seeds["paid"])[1] is False and _audit_rows(seeds["paid"]) == []
    # already manually banned
    r = client.post(f"/admin/accounts/{seeds['aban']}/ban", headers=ah, json={"reason": "again"})
    assert r.status_code == 400 and isinstance(r.json()["detail"], str)
    assert _sub_state(seeds["aban"])[2] == "fraud" and _audit_rows(seeds["aban"]) == []
    # lift on not-manually-banned (active and payment-banned)
    for k in ("paid", "pban"):
        r = client.post(f"/admin/accounts/{seeds[k]}/lift-ban", headers=ah)
        assert r.status_code == 400 and isinstance(r.json()["detail"], str)
        assert _audit_rows(seeds[k]) == []
    for path in ("ban", "lift-ban"):
        r = client.post(f"/admin/accounts/{uuid.uuid4()}/{path}", headers=ah, json={"reason": "x"})
        assert r.status_code == 404


def test_mutations_require_platform_admin(lifecycle):
    _, th = mk_teacher()
    sid = _seed_five()["paid"]
    until = (datetime.utcnow() + D(days=9)).isoformat() + "Z"
    for h in ({}, th):
        assert client.post(f"/admin/accounts/{sid}/ban", headers=h, json={"reason": "x"}).status_code == 401
        assert client.post(f"/admin/accounts/{sid}/lift-ban", headers=h).status_code == 401
        assert client.post(f"/admin/accounts/{sid}/extend-grace", headers=h, json={"until": until}).status_code == 401
    assert _audit_rows(sid) == []


def test_paying_accounts_counts_cancelled_and_past_due_excludes_free_and_trial(lifecycle):
    _, _, ah = mk_admin()
    before = _stats(ah)["paying_accounts"]
    now = datetime.utcnow()
    _seed_owner("teacher", status="cancelled", end=now + D(days=5))
    _seed_owner("institute", plan="pro", status="past_due", end=now + D(days=5))
    _seed_owner("teacher", plan="free", status="active")                       # free: not paying
    _seed_owner("institute", plan="pro", status="trialing", end=now + D(days=5))  # trial: not paying
    assert _stats(ah)["paying_accounts"] - before == 2


def test_list_has_expired_trial_and_free_rows_not_paying(lifecycle):
    _, _, ah = mk_admin()
    now = datetime.utcnow()
    exp = _seed_owner("institute", plan="pro", status="trialing", end=now - D(days=10))[0]
    free = _seed_owner("teacher", plan="free", status="active")[0]
    paid = _seed_owner("teacher", end=now + D(days=5))[0]
    assert _acct(ah, exp)["is_paying"] is False and _acct(ah, exp)["access_state"] == "grace"
    assert _acct(ah, free)["is_paying"] is False
    assert _acct(ah, paid)["is_paying"] is True


def test_headline_derivable_from_list(lifecycle):
    _, _, ah = mk_admin()

    def from_list():
        rows = client.get("/admin/accounts", headers=ah).json()
        return sum(1 for r in rows if r["is_paying"] and r["access_state"] in ("active", "grace"))
    b_list, b_stat = from_list(), _stats(ah)["paying_accounts"]
    _seed_five()
    now = datetime.utcnow()
    _seed_owner("teacher", status="cancelled", end=now + D(days=5))
    _seed_owner("teacher", plan="free", status="active")
    _seed_owner("institute", plan="pro", status="trialing", end=now - D(days=10))
    assert from_list() - b_list == _stats(ah)["paying_accounts"] - b_stat == 3
    assert from_list() - b_list == _stats(ah)["paying_accounts"] - b_stat


def test_manual_ban_works_on_trial_and_free_and_only_subscription_ids(lifecycle):
    _, _, ah = mk_admin()
    now = datetime.utcnow()
    trial = _seed_owner("institute", plan="pro", status="trialing", end=now + D(days=5))[0]
    free = _seed_owner("teacher", plan="free", status="active")[0]
    exp = _seed_owner("teacher", plan="pro", status="trialing", end=now - D(days=40))[0]
    for sid in (trial, free, exp):
        r = client.post(f"/admin/accounts/{sid}/ban", headers=ah, json={"reason": "abuse"})
        assert r.status_code == 200 and r.json()["access_state"] == "banned", sid
        r = client.post(f"/admin/accounts/{sid}/lift-ban", headers=ah)
        assert r.status_code == 200 and not r.json()["admin_banned"], sid
    # student / parent / in-institute teacher ids are not subscription ids -> 404
    iid, _ = mk_institute()
    tid, _ = mk_teacher(institute_id=iid)
    stid, _ = mk_student()
    for other in (tid, stid, iid):
        assert client.post(f"/admin/accounts/{other}/ban", headers=ah, json={"reason": "x"}).status_code == 404
        assert client.post(f"/admin/accounts/{other}/lift-ban", headers=ah).status_code == 404


def test_account_without_prior_row_is_listed_extendable_and_bannable(lifecycle, monkeypatch):
    """start_trial with trials off leaves a free/active row, so the founders can see and act on the account."""
    from app.services import subscriptions as subs_svc
    monkeypatch.setattr(settings, "trial_days", 0)
    _, _, ah = mk_admin()
    tid, _h = mk_teacher()
    db = SessionLocal()
    t = db.get(Teacher, tid)
    subs_svc.start_trial(db, subs_svc.owner_for_teacher(t))
    db.commit()
    sid = db.query(Subscription).filter(Subscription.teacher_id == tid).one().id
    db.close()
    monkeypatch.setattr(settings, "enforcement_start", None)  # not enforcing yet: visible and active
    row = _acct(ah, sid)
    assert row is not None and row["access_state"] == "active"
    # enforcement started 10 days ago: the free row is now in grace and the founders can extend it
    monkeypatch.setattr(settings, "enforcement_start", datetime.utcnow() - D(days=10))
    assert _acct(ah, sid)["access_state"] == "grace"
    until = datetime.utcnow() + D(days=60)
    r = client.post(f"/admin/accounts/{sid}/extend-grace", headers=ah, json={"until": until.isoformat() + "Z"})
    assert r.status_code == 200, r.text
    r = client.post(f"/admin/accounts/{sid}/ban", headers=ah, json={"reason": "abuse"})
    assert r.status_code == 200 and r.json()["access_state"] == "banned"
    r = client.post(f"/admin/accounts/{sid}/lift-ban", headers=ah)
    assert r.status_code == 200 and r.json()["access_state"] == "grace"
