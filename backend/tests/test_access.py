"""Account access lifecycle: paid -> 3-day buffer -> 15-day limited grace -> banned."""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from tests.test_billing_flow import mk_teacher, mk_institute, SessionLocal  # noqa: F401 (sets env + schema)
from app.database import settings
from app.models import Subscription, Teacher, Institute
from app.services import access, subscriptions as subs

NOW = datetime(2026, 12, 1, 12, 0, 0)
D = timedelta
R = NOW - D(days=1)  # release for the 'no live period' cases
R_OLD = NOW - D(days=100)  # release long before any paid period end


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setattr(settings, "enforcement_start", R_OLD)
    monkeypatch.setattr(settings, "billing_grace_days", 3)
    monkeypatch.setattr(settings, "limited_grace_days", 15)


def sub(plan="basic", status="active", end=None, **kw):
    return Subscription(plan=plan, status=status, current_period_end=end, **kw)


def test_off_when_enforcement_start_none(monkeypatch):
    monkeypatch.setattr(settings, "enforcement_start", None)
    a = access.access_for_subscription(sub(end=NOW - D(days=400)), NOW)
    assert a == access.Access("active", None, None, None)
    assert access.access_for_subscription(None, NOW).state == "active"


def test_paid_in_period_active():
    a = access.access_for_subscription(sub(end=NOW + D(days=5)), NOW)
    assert (a.state, a.reason, a.grace_starts_at, a.ban_at) == ("active", None, None, None)


def test_paid_buffer_then_grace_then_banned():
    e = NOW - D(days=2)
    a = access.access_for_subscription(sub(end=e), NOW)
    assert a.state == "active"
    assert a.grace_starts_at == e + D(days=3) and a.ban_at == e + D(days=18)  # R4

    e = NOW - D(days=4)
    a = access.access_for_subscription(sub(end=e), NOW)
    assert a.state == "grace" and a.reason == "payment"
    assert a.grace_starts_at == e + D(days=3)
    assert a.ban_at == e + D(days=18)

    a = access.access_for_subscription(sub(end=NOW - D(days=19)), NOW)
    assert (a.state, a.reason) == ("banned", "payment")


def test_expired_trial_clock_starts_at_release(monkeypatch):
    monkeypatch.setattr(settings, "enforcement_start", R)
    s = sub(plan="pro", status="trialing", end=NOW - D(days=200))
    a = access.access_for_subscription(s, NOW)
    assert a.state == "active"
    assert a.grace_starts_at == R + D(days=3) and a.ban_at == R + D(days=18)


def test_free_tier_and_no_row(monkeypatch):
    monkeypatch.setattr(settings, "enforcement_start", R)
    for s in (sub(plan="free", status="active"), None):
        a = access.access_for_subscription(s, NOW)
        assert a.state == "active"
        assert a.grace_starts_at == R + D(days=3) and a.ban_at == R + D(days=18)
    later = NOW + D(days=10)
    assert access.access_for_subscription(None, later).state == "grace"
    assert access.access_for_subscription(None, R + D(days=18)).state == "banned"


def test_grace_until_extends_only_when_later():
    e = NOW - D(days=4)
    gu = e + D(days=30)
    a = access.access_for_subscription(sub(end=e, grace_until=gu), NOW)
    assert a.ban_at == gu and a.state == "grace"
    a = access.access_for_subscription(sub(end=e, grace_until=e + D(days=5)), NOW)
    assert a.ban_at == e + D(days=18)


def test_admin_ban_overrides_everything():
    a = access.access_for_subscription(sub(end=NOW + D(days=30), admin_banned=True), NOW)
    assert (a.state, a.reason) == ("banned", "admin")


def test_cancelled():
    assert access.access_for_subscription(sub(status="cancelled", end=NOW + D(days=3)), NOW).state == "active"
    a = access.access_for_subscription(sub(status="cancelled", end=NOW - D(days=5)), NOW)
    assert a.state == "grace" and a.ban_at == NOW - D(days=5) + D(days=18)


# ---------- DB level ----------
def _owner_sub(db, owner, **kw):
    s = subs.get_or_create_subscription(db, owner)
    for k, v in kw.items():
        setattr(s, k, v)
    db.commit()
    return s


def test_access_for_owner_teacher_and_institute():
    tid, _ = mk_teacher()
    iid, _ = mk_institute()
    db = SessionLocal()
    try:
        t_owner = subs.owner_for_teacher(db.get(Teacher, tid))
        i_owner = subs.owner_for_institute(db.get(Institute, iid))
        assert access.access_for_owner(db, t_owner, NOW).ban_at == R_OLD + D(days=18)  # no row
        _owner_sub(db, t_owner, plan="basic", status="active", current_period_end=NOW - D(days=19))
        assert access.access_for_owner(db, t_owner, NOW).state == "banned"
        _owner_sub(db, i_owner, plan="pro", status="active", current_period_end=NOW + D(days=9))
        assert access.access_for_owner(db, i_owner, NOW).state == "active"
    finally:
        db.close()


def test_late_webhook_and_payment_recovery():
    tid, _ = mk_teacher()
    db = SessionLocal()
    try:
        owner = subs.owner_for_teacher(db.get(Teacher, tid))
        s = _owner_sub(db, owner, plan="basic", status="active", current_period_end=NOW - D(hours=1))
        assert access.access_for_owner(db, owner, NOW).state == "active"
        for days_ago, state in ((5, "grace"), (30, "banned")):
            s.current_period_end = NOW - D(days=days_ago)
            db.commit()
            assert access.access_for_owner(db, owner, NOW).state == state
            s.current_period_end = NOW + D(days=30)  # payment arrives
            db.commit()
            assert access.access_for_owner(db, owner, NOW).state == "active"
        s.admin_banned = True
        db.commit()
        s.current_period_end = NOW + D(days=60)  # a payment does not lift an admin ban
        db.commit()
        a = access.access_for_owner(db, owner, NOW)
        assert (a.state, a.reason) == ("banned", "admin")
    finally:
        db.close()


def test_assert_not_locked_and_full_access(monkeypatch):
    tid, _ = mk_teacher()
    db = SessionLocal()
    try:
        owner = subs.owner_for_teacher(db.get(Teacher, tid))
        s = _owner_sub(db, owner, plan="basic", status="active",
                       current_period_end=datetime.utcnow() - D(days=30))
        monkeypatch.setattr(settings, "enforcement_start", datetime.utcnow() - D(days=60))
        with pytest.raises(HTTPException) as e:
            access.assert_not_locked(db, owner)
        assert e.value.status_code == 403
        assert e.value.headers["X-Account-Status"] == "banned_payment"
        assert "X-Account-Can-Pay" not in e.value.headers
        assert e.value.detail == "This account is inactive because the plan wasn't renewed. Please contact your institute."
        with pytest.raises(HTTPException) as e:
            access.assert_not_locked(db, owner, payer=True)
        assert e.value.headers["X-Account-Can-Pay"] == "1"
        assert e.value.detail == "Your plan wasn't renewed. Renew in Billing to restore access."

        access.assert_not_locked(db, owner, billing=True, payer=True)  # billing routes stay open

        s.admin_banned = True
        db.commit()
        with pytest.raises(HTTPException) as e:
            access.assert_not_locked(db, owner, billing=True, payer=True)
        assert e.value.headers["X-Account-Status"] == "banned_admin"
        assert "X-Account-Can-Pay" not in e.value.headers
        assert e.value.detail == "This account has been suspended. Please contact Wandor support."

        s.admin_banned = False
        s.current_period_end = datetime.utcnow() - D(days=5)
        db.commit()
        access.assert_not_locked(db, owner)  # grace is not locked
        with pytest.raises(HTTPException) as e:
            access.assert_full_access(db, owner, "Attendance")
        assert e.value.status_code == 402
        assert e.value.detail == "Attendance is paused because your plan has lapsed. Renew in Billing to turn it back on."
        s.current_period_end = datetime.utcnow() + D(days=5)
        db.commit()
        access.assert_full_access(db, owner, "Attendance")
    finally:
        db.close()


def test_plan_for_owner_in_grace(monkeypatch):
    tid, _ = mk_teacher()
    db = SessionLocal()
    try:
        owner = subs.owner_for_teacher(db.get(Teacher, tid))
        # lapsed 5 days ago relative to real now, with enforcement on
        monkeypatch.setattr(settings, "enforcement_start", datetime.utcnow() - D(days=10))  # free row: in grace
        _owner_sub(db, owner, plan="basic", status="active",
                   current_period_end=datetime.utcnow() - D(days=5))
        assert subs.effective_plan(subs.get_subscription(db, owner)) == "free"
        assert subs.plan_for_owner(db, owner) == "basic"
        _owner_sub(db, owner, plan="free", status="active", current_period_end=None)
        assert subs.plan_for_owner(db, owner) == "pro"  # TRIAL_PLAN
    finally:
        db.close()


# ---------- Enforcement through the HTTP layer (Task 3) ----------
from tests.test_billing_flow import client, mk_student, _parent_h  # noqa: E402
from app.models import Test, TestType, TestAttempt  # noqa: E402


def _lapse(owner_kind, oid, days_ago=None, admin=False):
    """Put an owner's subscription `days_ago` past its period end (None = still paid)."""
    db = SessionLocal()
    try:
        owner = subs.Owner(institute_id=oid) if owner_kind == "institute" else subs.Owner(teacher_id=oid)
        kw = dict(plan="basic", status="active", admin_banned=admin,
                  current_period_end=datetime.utcnow() - D(days=days_ago) if days_ago is not None
                  else datetime.utcnow() + D(days=20))
        _owner_sub(db, owner, **kw)
    finally:
        db.close()


@pytest.fixture
def _live(monkeypatch):
    monkeypatch.setattr(settings, "enforcement_start", datetime.utcnow() - D(days=100))


def _inst_world():
    iid, ih = mk_institute()
    tid, th = mk_teacher(institute_id=iid)
    sid, sh = mk_student(institute_id=iid)
    return iid, ih, tid, th, sid, sh, _parent_h(sid)


def test_payment_ban_locks_members_but_not_institute_billing(_live):
    iid, ih, tid, th, sid, sh, ph = _inst_world()
    _lapse("institute", iid, 30)
    for url, h in (("/students", th), ("/students/me", sh), ("/parents/me", ph)):
        r = client.get(url, headers=h)
        assert r.status_code == 403, url
        assert r.headers["X-Account-Status"] == "banned_payment"
        assert "X-Account-Can-Pay" not in r.headers
    r = client.get("/institute/me", headers=ih)
    assert r.status_code == 403
    assert r.headers["X-Account-Status"] == "banned_payment" and r.headers["X-Account-Can-Pay"] == "1"
    r = client.get("/billing/me", headers=ih)
    assert r.status_code == 200
    assert r.json()["access_state"] == "banned" and r.json()["access_reason"] == "payment"
    assert r.json()["ban_at"]
    # R2: a teacher inside the institute is locked from Billing too
    r = client.get("/billing/me", headers=th)
    assert r.status_code == 403 and r.headers["X-Account-Status"] == "banned_payment"
    assert "X-Account-Can-Pay" not in r.headers


def test_independent_teacher_payment_ban_can_still_reach_billing(_live):
    tid, th = mk_teacher()
    _lapse("teacher", tid, 30)
    r = client.get("/students", headers=th)
    assert r.status_code == 403
    assert r.headers["X-Account-Status"] == "banned_payment" and r.headers["X-Account-Can-Pay"] == "1"
    assert client.get("/billing/me", headers=th).status_code == 200


def test_admin_ban_blocks_everyone_including_billing(_live):
    iid, ih, tid, th, sid, sh, ph = _inst_world()
    _lapse("institute", iid, None, admin=True)
    for url, h in (("/students", th), ("/students/me", sh), ("/parents/me", ph),
                   ("/institute/me", ih), ("/billing/me", ih), ("/billing/me", th)):
        r = client.get(url, headers=h)
        assert r.status_code == 403, url
        assert r.headers["X-Account-Status"] == "banned_admin"
        assert "X-Account-Can-Pay" not in r.headers
    itid, ith = mk_teacher()
    _lapse("teacher", itid, None, admin=True)
    for url in ("/students", "/billing/me"):
        r = client.get(url, headers=ith)
        assert r.status_code == 403 and r.headers["X-Account-Status"] == "banned_admin"


def test_grace_keeps_history_readable_and_pauses_features(_live):
    tid, th = mk_teacher()
    sid, sh = mk_student(teacher_id=tid)
    _sid2, sh2 = mk_student(teacher_id=tid)  # has no open attempt
    ph = _parent_h(sid)
    _lapse("teacher", tid, 5)  # buffer over, in grace
    # read-only history stays open for student and parent
    assert client.get("/attendance/me/summary", headers=sh).status_code == 200
    assert client.get("/tests/my-attempts", headers=sh).status_code == 200
    assert client.get("/parents/attendance", headers=ph).status_code == 200
    assert client.get("/parents/tests", headers=ph).status_code == 200
    # the unrelated surface is untouched
    assert client.get("/students", headers=th).status_code == 200
    assert client.get("/classes", headers=th).status_code == 200
    r = client.get("/billing/me", headers=th).json()
    assert r["access_state"] == "grace" and r["ban_at"]

    db = SessionLocal()
    t = Test(teacher_id=tid, title="T", test_type=TestType.mcq_auto, duration_minutes=30)
    db.add(t)
    db.commit()
    att = TestAttempt(test_id=t.id, student_id=sid, started_at=datetime.utcnow())
    db.add(att)
    db.commit()
    test_id, att_id = t.id, att.id
    db.close()

    paused = lambda what: f"{what} is paused because your plan has lapsed. Renew in Billing to turn it back on."
    q = {"text": "q", "option_a": "1", "option_b": "2", "option_c": "3", "option_d": "4", "correct_option": "a"}
    calls = [
        (client.post("/attendance/mark", json={"class_session_id": "x", "marks": [{"student_id": "y", "present": True}]},
                     headers=th), "Attendance"),
        (client.post("/tests/mcq", json={"title": "T", "questions": [q]}, headers=th), "Tests"),
        (client.post("/tests/document", json={"title": "T", "document_url": "http://x/y.pdf"}, headers=th), "Tests"),
        (client.post(f"/tests/{test_id}/start", headers=sh2), "Tests"),
        (client.get(f"/tests/{test_id}/analytics", headers=th), "Analytics"),
        (client.get("/attendance/batch/nope/analytics", headers=th), "Analytics"),
    ]
    for r, what in calls:
        assert r.status_code == 402, (what, r.status_code, r.text)
        assert r.json()["detail"] == paused(what)
    # an attempt already open can still be submitted
    r = client.post(f"/tests/attempts/{att_id}/submit", json={"answers": []}, headers=sh)
    assert r.status_code == 200, r.text


def test_start_in_grace_resumes_open_attempt_but_blocks_new_ones(_live):
    tid, th = mk_teacher()
    sid, sh = mk_student(teacher_id=tid)
    _sid2, sh2 = mk_student(teacher_id=tid)
    _lapse("teacher", tid, None)  # still paid
    db = SessionLocal()
    t = Test(teacher_id=tid, title="T", test_type=TestType.mcq_auto, duration_minutes=30)
    db.add(t)
    db.commit()
    test_id = t.id
    db.close()
    r = client.post(f"/tests/{test_id}/start", headers=sh)
    assert r.status_code == 200, r.text
    attempt_id = r.json()["attempt_id"]
    _lapse("teacher", tid, 5)  # plan lapses mid-test: grace
    r = client.post(f"/tests/{test_id}/start", headers=sh)  # page reload
    assert r.status_code == 200 and r.json()["attempt_id"] == attempt_id
    r = client.post(f"/tests/{test_id}/start", headers=sh2)
    assert r.status_code == 402
    assert r.json()["detail"] == "Tests is paused because your plan has lapsed. Renew in Billing to turn it back on."


def test_start_trial_always_leaves_a_row(monkeypatch):
    from app.models import Subscription as S
    monkeypatch.setattr(settings, "trial_days", 0)
    tid, _ = mk_teacher()
    db = SessionLocal()
    try:
        owner = subs.owner_for_teacher(db.get(Teacher, tid))
        subs.start_trial(db, owner)
        db.commit()
        rows = db.query(S).filter(S.teacher_id == tid).all()
        assert [(r.plan, r.status, r.current_period_end) for r in rows] == [("free", "active", None)]
        subs.start_trial(db, owner)  # repeat: still one row
        monkeypatch.setattr(settings, "trial_days", 14)
        subs.start_trial(db, owner)  # trials turned on later must not restart anything
        db.commit()
        assert db.query(S).filter(S.teacher_id == tid).count() == 1
    finally:
        db.close()
    # trials on: unchanged behaviour (a trialing row), and never restarted
    tid2, _ = mk_teacher(trial=True)
    db = SessionLocal()
    try:
        r = db.query(S).filter(S.teacher_id == tid2).one()
        assert r.status == "trialing" and r.current_period_end is not None
    finally:
        db.close()


def test_payment_clears_stale_grace_until_and_later_lapse_uses_normal_window(monkeypatch):
    import time
    tid, _ = mk_teacher()
    db = SessionLocal()
    try:
        owner = subs.owner_for_teacher(db.get(Teacher, tid))
        now = datetime.utcnow()
        s = _owner_sub(db, owner, plan="basic", status="active", current_period_end=now - D(days=5),
                       grace_until=now + D(days=365))
        assert access.access_for_owner(db, owner, now).state == "grace"
        ban_override = access.access_for_owner(db, owner, now).ban_at
        assert ban_override > now + D(days=300)  # the founder extension is in force
        end = int(time.time()) + 30 * 86400  # payment: Razorpay reports the sub active with a new period
        subs.apply_razorpay_subscription(db, {"id": "sub_grace_pay", "status": "active", "current_end": end,
                                              "notes": {"teacher_id": tid}})
        db.commit()
        db.refresh(s)
        assert s.grace_until is None and s.status == "active"
        assert access.access_for_owner(db, owner, now).state == "active"
        s.admin_banned = True  # admin ban untouched by a later payment sync
        db.commit()
        subs.apply_razorpay_subscription(db, {"id": "sub_grace_pay", "status": "active", "current_end": end,
                                              "notes": {"teacher_id": tid}})
        db.commit()
        db.refresh(s)
        assert s.admin_banned is True
        s.admin_banned = False
        db.commit()
        # a later lapse follows the normal window: end + 3d buffer + 15d grace
        pe = s.current_period_end
        a = access.access_for_owner(db, owner, pe + D(days=10))
        assert a.state == "grace" and a.ban_at == pe + D(days=18)
        assert access.access_for_owner(db, owner, pe + D(days=19)).state == "banned"
    finally:
        db.close()
