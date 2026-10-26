"""End-to-end checks for the subscription system + student fee payments, run against a
throwaway SQLite DB with a FAKE Razorpay client (no network, no real keys).

Run from backend/:   python -m tests.test_billing_flow
(also collectable by pytest - every check is a plain test_* function).
"""
import calendar
import contextlib
import hashlib
import hmac
import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta

# --- env must be set BEFORE app.* is imported (Settings() reads it at import) ---
_tmp = tempfile.mkdtemp()
os.environ.update({
    # Set TEST_DATABASE_URL to run the same suite against Postgres (production's DB).
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db",
    "JWT_SECRET": "test-secret",
    "RAZORPAY_KEY_ID": "rzp_test_key",
    "RAZORPAY_KEY_SECRET": "key_secret",
    "RAZORPAY_WEBHOOK_SECRET": "whsec",
    "RAZORPAY_PLAN_BASIC_MONTHLY": "plan_basic_m",
    "RAZORPAY_PLAN_BASIC_YEARLY": "plan_basic_y",
    "RAZORPAY_PLAN_PRO_MONTHLY": "plan_pro_m",
    "RAZORPAY_PLAN_PRO_YEARLY": "",  # deliberately unconfigured
    "TRIAL_DAYS": "14",
    "BILLING_GRACE_DAYS": "3",
    "FEE_PLATFORM_COMMISSION_BPS": "200",  # 2%
    # High so older tests never trip the limiter; the rate-limit tests set their own.
    "RATE_LIMIT_PAYMENT_PER_MIN": "1000",
    "RATE_LIMIT_BILLING_PER_MIN": "1000",
})

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.database import SessionLocal, Base, engine  # noqa: E402
from app.models import Institute, Teacher, Student, Batch, FeeRecord, Subscription  # noqa: E402
from app.auth import create_access_token, hash_password  # noqa: E402
from app.routers import billing, payments  # noqa: E402
from app.services import subscriptions as subs  # noqa: E402
from app.services import fee_reminders, fee_notices, fee_ledger  # noqa: E402
from app.models import FeePayment, Invoice, InvoiceCounter  # noqa: E402
from app.services import invoices, upgrades  # noqa: E402
from app.models import PlanUpgrade  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from app import ratelimit  # noqa: E402
from app.database import settings  # noqa: E402

Base.metadata.create_all(bind=engine)
client = TestClient(app)


# ---------------- fake Razorpay ----------------
class FakeRazorpay:
    def __init__(self):
        self.subscriptions = {}
        self.orders = {}
        self.calls = []
        self.payments = {}
        self.fail_payment_fetch = False
        self.edit_error = False    # Razorpay refuses to edit (e.g. a UPI subscription)
        self.cancel_error = False

        outer = self

        class _Sub:
            def create(self, body):
                sid = f"sub_{len(outer.subscriptions)+1}"
                outer.subscriptions[sid] = {
                    "id": sid, "plan_id": body["plan_id"], "status": "created",
                    "notes": body.get("notes", {}), "current_end": None,
                }
                outer.calls.append(("subscription.create", body))
                return outer.subscriptions[sid]

            def fetch(self, sid):
                return dict(outer.subscriptions[sid])

            def cancel(self, sid, data=None):
                outer.calls.append(("subscription.cancel", sid, data))
                if outer.cancel_error:
                    raise RuntimeError("cancel refused")
                return {}

            def edit(self, sid, data):
                outer.calls.append(("subscription.edit", sid, data))
                if outer.edit_error:
                    raise RuntimeError("Subscriptions cannot be updated when payment mode is UPI")
                return {}

        class _Order:
            def create(self, body):
                oid = f"order_{len(outer.orders)+1}"
                outer.orders[oid] = {"id": oid, "status": "created", "amount": body["amount"],
                                     "receipt": body.get("receipt"), "body": body}
                outer.calls.append(("order.create", body))
                return {"id": oid}

            def fetch(self, oid):
                return outer.orders[oid]

        class _Payment:
            def fetch(self, pid):
                if outer.fail_payment_fetch:
                    raise RuntimeError("razorpay unreachable")
                return outer.payments.get(pid, {"id": pid, "amount_refunded": 0})

        self.subscription = _Sub()
        self.order = _Order()
        self.payment = _Payment()

    def activate(self, sid, current_end_days=30):
        e = self.subscriptions[sid]
        e["status"] = "active"
        e["current_end"] = int(time.time()) + current_end_days * 86400


SENT = []  # every (phone, template, params) a notice WOULD have sent
fee_notices.notify = lambda phone, msg, template=None, params=None: (SENT.append((phone, template, params, msg)) or "whatsapp")
FAKE = FakeRazorpay()
billing.get_razorpay_client = lambda: FAKE
payments.get_razorpay_client = lambda: FAKE


# ---------------- helpers ----------------
_n = [0]


def _phone():
    _n[0] += 1
    return f"90000{_n[0]:05d}"


def mk_teacher(institute_id=None, trial=False, is_owner=False):
    db = SessionLocal()
    t = Teacher(institute_id=institute_id, name="T", phone=_phone(),
                hashed_password=hash_password("pw"), is_owner=is_owner)
    db.add(t)
    db.commit()
    if trial:
        subs.start_trial(db, subs.owner_for_teacher(t))
        db.commit()
    tid = t.id
    db.close()
    return tid, {"Authorization": f"Bearer {create_access_token(tid, 'teacher')}"}


def mk_institute(trial=False):
    db = SessionLocal()
    i = Institute(name="Inst", owner_phone=_phone(), hashed_password=hash_password("pw"))
    db.add(i)
    db.commit()
    if trial:
        subs.start_trial(db, subs.owner_for_institute(i))
        db.commit()
    iid = i.id
    db.close()
    return iid, {"Authorization": f"Bearer {create_access_token(iid, 'institute_admin')}"}


def mk_student(teacher_id=None, institute_id=None, batch_id=None):
    db = SessionLocal()
    s = Student(institute_id=institute_id, teacher_id=teacher_id, name="Stu", phone=_phone(),
                hashed_password=hash_password("1234"), batch_id=batch_id)
    db.add(s)
    db.commit()
    sid = s.id
    db.close()
    return sid, {"Authorization": f"Bearer {create_access_token(sid, 'student')}"}


def webhook(event, entity_key, entity, event_id):
    body = json.dumps({"event": event, "payload": {entity_key: {"entity": entity}}}).encode()
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    return client.post("/payments/webhook", content=body,
                       headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
                                "Content-Type": "application/json"})


def sub_sig(payment_id, sub_id):
    return hmac.new(b"key_secret", f"{payment_id}|{sub_id}".encode(), hashlib.sha256).hexdigest()


def order_sig(order_id, payment_id):
    return hmac.new(b"key_secret", f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


# ---------------- entitlement unit checks ----------------
def test_effective_plan_rules():
    now = datetime.utcnow()
    S = lambda **k: Subscription(plan="pro", **k)  # noqa: E731
    assert subs.effective_plan(None) == "free"
    assert subs.effective_plan(S(status="trialing", current_period_end=now + timedelta(days=1))) == "pro"
    assert subs.effective_plan(S(status="trialing", current_period_end=now - timedelta(seconds=1))) == "free"
    assert subs.effective_plan(S(status="active", current_period_end=now + timedelta(days=5))) == "pro"
    # renewal webhook late/missed: honoured through the grace window only
    assert subs.effective_plan(S(status="active", current_period_end=now - timedelta(days=2))) == "pro"
    assert subs.effective_plan(S(status="active", current_period_end=now - timedelta(days=4))) == "free"
    assert subs.effective_plan(S(status="past_due", current_period_end=now - timedelta(days=2))) == "pro"
    assert subs.effective_plan(S(status="past_due", current_period_end=now - timedelta(days=4))) == "free"
    assert subs.effective_plan(S(status="cancelled", current_period_end=now + timedelta(days=2))) == "pro"
    assert subs.effective_plan(S(status="cancelled", current_period_end=now - timedelta(days=1))) == "free"
    assert subs.effective_plan(S(status="pending", current_period_end=now + timedelta(days=9))) == "free"


# ---------------- trial + plan limits ----------------
def test_trial_and_free_limits():
    _, h = mk_teacher(trial=True)
    me = client.get("/billing/me", headers=h).json()
    assert me["plan"] == "pro" and me["status"] == "trialing" and me["can_manage"] is True

    # No trial -> Free: 25 students max
    tid, h = mk_teacher(trial=False)
    assert client.get("/billing/me", headers=h).json()["plan"] == "free"
    for i in range(25):
        mk_student(teacher_id=tid)
    r = client.post("/students", headers=h, json={"name": "X", "phone": "9111111111", "password": "1234"})
    assert r.status_code == 402, r.text
    assert "25 students" in r.json()["detail"]

    # bulk import: skipped (not rejected) once the cap is hit
    csv_body = b"name,phone\nA,9222222221\nB,9222222222\n"
    r = client.post("/students/bulk-import", headers=h, files={"file": ("s.csv", csv_body, "text/csv")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["created_count"] == 0 and out["skipped_count"] == 2
    assert "limit" in out["skipped"][0]["reason"]


def test_institute_teacher_cap_and_member_view():
    iid, ih = mk_institute(trial=False)  # Free: 1 teacher
    r = client.post("/institute/teachers", headers=ih,
                    json={"name": "A", "phone": _phone(), "password": "pw12345", "is_owner": True})
    assert r.status_code == 200, r.text
    r = client.post("/institute/teachers", headers=ih,
                    json={"name": "B", "phone": _phone(), "password": "pw12345", "is_owner": False})
    assert r.status_code == 402 and "1 teacher" in r.json()["detail"], r.text

    # an institute member can view the plan but not change it
    _, th = mk_teacher(institute_id=iid)
    me = client.get("/billing/me", headers=th).json()
    assert me["can_manage"] is False and me["owner_kind"] == "institute"
    r = client.post("/billing/subscribe", headers=th, json={"plan": "basic", "cycle": "monthly"})
    assert r.status_code == 403


# ---------------- subscribe -> verify -> webhooks -> cancel ----------------
def test_subscription_lifecycle():
    tid, h = mk_teacher(trial=False)

    plans_ = client.get("/billing/plans").json()
    pro = next(p for p in plans_ if p["key"] == "pro")
    assert pro["monthly_available"] is True and pro["yearly_available"] is False

    # unconfigured cycle is refused, not silently created
    r = client.post("/billing/subscribe", headers=h, json={"plan": "pro", "cycle": "yearly"})
    assert r.status_code == 503
    r = client.post("/billing/subscribe", headers=h, json={"plan": "enterprise", "cycle": "monthly"})
    assert r.status_code == 400

    r = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "monthly"})
    assert r.status_code == 200, r.text
    sid = r.json()["subscription_id"]
    created_body = [c for c in FAKE.calls if c[0] == "subscription.create"][-1][1]
    assert created_body["notes"] == {"plan": "basic", "cycle": "monthly", "teacher_id": tid}
    assert "start_at" not in created_body  # no trial to wait out

    # Paying hasn't happened yet: still Free
    assert client.get("/billing/me", headers=h).json()["plan"] == "free"

    # Bad signature is rejected
    r = client.post("/billing/verify", headers=h, json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid, "razorpay_signature": "nope"})
    assert r.status_code == 400

    # Real signature + subscription now active at Razorpay -> instant upgrade
    FAKE.activate(sid)
    r = client.post("/billing/verify", headers=h, json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
        "razorpay_signature": sub_sig("pay_1", sid)})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["plan"] == "basic" and me["status"] == "active" and me["billing_cycle"] == "monthly"
    assert me["students_limit"] == 150 and me["online_fee_collection"] is True

    # Someone else can't claim this subscription
    _, other = mk_teacher(trial=False)
    r = client.post("/billing/verify", headers=other, json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
        "razorpay_signature": sub_sig("pay_1", sid)})
    assert r.status_code == 403

    # Already subscribed -> subscribe again is a 409 (use change-plan)
    r = client.post("/billing/subscribe", headers=h, json={"plan": "pro", "cycle": "monthly"})
    assert r.status_code == 409

    # Webhook: bad signature 400; good one applies; same event id twice is a no-op
    bad = client.post("/payments/webhook", content=b"{}", headers={"X-Razorpay-Signature": "x"})
    assert bad.status_code == 400
    FAKE.subscriptions[sid]["status"] = "active"
    FAKE.subscriptions[sid]["current_end"] = int(time.time()) + 60 * 86400
    r = webhook("subscription.charged", "subscription", FAKE.subscriptions[sid], "evt_1")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    r = webhook("subscription.charged", "subscription", FAKE.subscriptions[sid], "evt_1")
    assert r.json()["status"] == "duplicate"

    # Plan change is queued for the next cycle, not applied now
    r = client.post("/billing/change-plan", headers=h, json={"plan": "pro", "cycle": "monthly"})
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "basic" and r.json()["scheduled_plan"] == "pro"
    assert [c for c in FAKE.calls if c[0] == "subscription.edit"][-1][2]["schedule_change_at"] == "cycle_end"
    # ...and takes effect when the renewal arrives on the new Razorpay plan
    FAKE.subscriptions[sid]["plan_id"] = "plan_pro_m"
    webhook("subscription.charged", "subscription", FAKE.subscriptions[sid], "evt_2")
    me = client.get("/billing/me", headers=h).json()
    assert me["plan"] == "pro" and me["scheduled_plan"] is None

    # Cancel: keeps access to period end
    r = client.post("/billing/cancel", headers=h)
    assert r.status_code == 200 and r.json()["cancel_at_period_end"] is True and r.json()["plan"] == "pro"
    FAKE.subscriptions[sid]["status"] = "cancelled"
    webhook("subscription.cancelled", "subscription", FAKE.subscriptions[sid], "evt_3")
    assert client.get("/billing/me", headers=h).json()["plan"] == "pro"  # paid period still running

    # Resubscribing after cancelling must not double-charge the paid time left: the
    # first charge is deferred to the end of the current period.
    r = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "monthly"})
    assert r.status_code == 200, r.text
    assert [c for c in FAKE.calls if c[0] == "subscription.create"][-1][1]["start_at"] > time.time() + 20 * 86400

    # Period over -> back to Free (and existing data is untouched)
    db = SessionLocal()
    sub = db.query(Subscription).filter(Subscription.teacher_id == tid).first()
    sub.current_period_end = datetime.utcnow() - timedelta(days=1)
    db.commit()
    db.close()
    me = client.get("/billing/me", headers=h).json()
    assert me["plan"] == "free" and me["status"] == "expired"


def test_trial_owner_first_charge_deferred_to_trial_end():
    _, h = mk_teacher(trial=True)
    r = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "monthly"})
    assert r.status_code == 200, r.text
    body = [c for c in FAKE.calls if c[0] == "subscription.create"][-1][1]
    assert body["start_at"] > time.time() + 12 * 86400  # ~trial end, not now
    # authenticated-but-not-yet-charged must not disturb the running trial
    sid = r.json()["subscription_id"]
    FAKE.subscriptions[sid]["status"] = "authenticated"
    webhook("subscription.authenticated", "subscription", FAKE.subscriptions[sid], "evt_t1")
    me = client.get("/billing/me", headers=h).json()
    assert me["plan"] == "pro" and me["status"] == "trialing"


def test_webhook_refuses_when_secret_unset():
    from app.database import settings
    old = settings.razorpay_webhook_secret
    settings.razorpay_webhook_secret = ""
    try:
        empty_sig = hmac.new(b"", b"{}", hashlib.sha256).hexdigest()
        r = client.post("/payments/webhook", content=b"{}", headers={"X-Razorpay-Signature": empty_sig})
        assert r.status_code == 503  # a forged empty-key signature must NOT be accepted
    finally:
        settings.razorpay_webhook_secret = old


# ---------------- student fee flow ----------------
def test_fee_flow_end_to_end():
    tid, th = mk_teacher(trial=False)  # Free: no online collection
    db = SessionLocal()
    b = Batch(teacher_id=tid, name="10A")
    db.add(b)
    db.commit()
    bid = b.id
    db.close()
    s1, sh1 = mk_student(teacher_id=tid, batch_id=bid)
    s2, sh2 = mk_student(teacher_id=tid, batch_id=bid)
    s_other, _ = mk_student(teacher_id=tid)  # not in the batch

    due = (datetime.utcnow() + timedelta(days=5)).isoformat()
    r = client.post("/payments/fees", headers=th, json={"batch_id": bid, "amount": 1500, "due_date": due,
                                                        "description": "March tuition"})
    assert r.status_code == 200 and r.json()["created_count"] == 2, r.text

    recs = client.get("/payments/records", headers=th).json()
    assert len(recs) == 2 and recs[0]["student_name"] == "Stu" and recs[0]["batch_name"] == "10A"

    # Free plan / no linked account: online payment is refused, and the student is told why
    mine = client.get("/payments/my-fees", headers=sh1).json()
    assert mine["online_payment_available"] is False and len(mine["fees"]) == 1
    fee1 = mine["fees"][0]["id"]
    r = client.post("/payments/create-order", headers=sh1, json={"fee_record_id": fee1})
    assert r.status_code == 409

    # ...but the teacher can still record a cash payment
    r = client.post(f"/payments/fees/{recs[1]['id']}/mark-paid", headers=th)
    assert r.status_code == 200 and r.json()["payment_mode"] == "manual"
    assert client.post(f"/payments/fees/{recs[1]['id']}/mark-paid", headers=th).status_code == 400

    # A different teacher can't touch these fees
    _, other_th = mk_teacher(trial=False)
    assert client.post(f"/payments/fees/{fee1}/mark-paid", headers=other_th).status_code == 404
    assert len(client.get("/payments/records", headers=other_th).json()) == 0

    # Give the teacher a paid plan + a linked account
    db = SessionLocal()
    subs.get_or_create_subscription(db, subs.Owner(teacher_id=tid))
    sub = db.query(Subscription).filter(Subscription.teacher_id == tid).first()
    sub.plan, sub.status, sub.current_period_end = "basic", "active", datetime.utcnow() + timedelta(days=20)
    db.query(Teacher).filter(Teacher.id == tid).update({"razorpay_account_id": "acc_teacher1"})
    db.commit()
    db.close()

    assert client.get("/payments/payout-status", headers=th).json()["ready"] is True
    assert client.get("/payments/my-fees", headers=sh1).json()["online_payment_available"] is True

    r = client.post("/payments/create-order", headers=sh1, json={"fee_record_id": fee1})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["amount_paise"] == 150000 and order["key_id"] == "rzp_test_key"
    body = FAKE.orders[order["order_id"]]["body"]
    # Money is routed to the TEACHER's linked account, minus the 2% platform cut
    assert body["transfers"][0]["account"] == "acc_teacher1"
    assert body["transfers"][0]["amount"] == 150000 - 3000

    # tapping Pay again reuses the open order rather than minting a second one
    again = client.post("/payments/create-order", headers=sh1, json={"fee_record_id": fee1}).json()
    assert again["order_id"] == order["order_id"]

    # Another student can't pay/verify this fee
    assert client.post("/payments/create-order", headers=sh2, json={"fee_record_id": fee1}).status_code == 404

    # verify: bad signature rejected, good one marks paid; webhook after is a no-op
    pid = "pay_fee_1"
    r = client.post("/payments/verify", headers=sh1, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": pid, "razorpay_signature": "bad"})
    assert r.status_code == 400
    r = client.post("/payments/verify", headers=sh1, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": pid,
        "razorpay_signature": order_sig(order["order_id"], pid)})
    assert r.status_code == 200
    w = webhook("payment.captured", "payment", {"id": pid, "order_id": order["order_id"]}, "evt_fee1")
    assert w.status_code == 200
    db = SessionLocal()
    f = db.query(FeeRecord).filter(FeeRecord.id == fee1).first()
    assert f.is_paid and f.amount_paid == 1500 and f.payment_mode == "online" and f.razorpay_payment_id == pid
    db.close()
    assert client.post("/payments/create-order", headers=sh1, json={"fee_record_id": fee1}).status_code == 400

    # paid fees can't be deleted; unpaid can
    assert client.delete(f"/payments/fees/{fee1}", headers=th).status_code == 400


def test_institute_students_pay_the_institute_account():
    iid, ih = mk_institute(trial=False)
    db = SessionLocal()
    sub = subs.get_or_create_subscription(db, subs.Owner(institute_id=iid))
    sub.plan, sub.status, sub.current_period_end = "pro", "active", datetime.utcnow() + timedelta(days=20)
    db.query(Institute).filter(Institute.id == iid).update({"razorpay_account_id": "acc_inst1"})
    db.commit()
    db.close()
    tid, th = mk_teacher(institute_id=iid, is_owner=True)
    sid, sh = mk_student(institute_id=iid)
    db = SessionLocal()
    fee = FeeRecord(student_id=sid, amount_due=999.5, due_date=datetime.utcnow() + timedelta(days=1))
    db.add(fee)
    db.commit()
    fid = fee.id
    db.close()
    r = client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid})
    assert r.status_code == 200, r.text
    assert r.json()["amount_paise"] == 99950
    assert FAKE.orders[r.json()["order_id"]]["body"]["transfers"][0]["account"] == "acc_inst1"


# ---------------- audit round 2: gaps found on review ----------------
def _paid_teacher(plan="basic", days=20, account="acc_t"):
    tid, h = mk_teacher(trial=False)
    db = SessionLocal()
    sub = subs.get_or_create_subscription(db, subs.Owner(teacher_id=tid))
    sub.plan, sub.status, sub.current_period_end = plan, "active", datetime.utcnow() + timedelta(days=days)
    db.query(Teacher).filter(Teacher.id == tid).update({"razorpay_account_id": account})
    db.commit()
    db.close()
    return tid, h


def test_gap_double_subscribe_during_trial():
    """Trial user subscribes (first charge deferred -> Razorpay status 'authenticated').
    That pending subscription must be remembered, or they can subscribe again and end
    up with two live subscriptions."""
    _, h = mk_teacher(trial=True)
    r = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "monthly"})
    sid = r.json()["subscription_id"]
    FAKE.subscriptions[sid]["status"] = "authenticated"
    r = client.post("/billing/verify", headers=h, json={
        "razorpay_payment_id": "pay_a", "razorpay_subscription_id": sid,
        "razorpay_signature": sub_sig("pay_a", sid)})
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["status"] == "trialing" and me["plan"] == "pro"      # trial untouched
    assert me["scheduled_plan"] == "basic"                          # ...and the purchase is visible
    r = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "monthly"})
    assert r.status_code == 409, r.text                             # no second subscription

    # the deferred first charge lands -> becomes the live subscription
    FAKE.activate(sid)
    webhook("subscription.activated", "subscription", FAKE.subscriptions[sid], "evt_gap1")
    me = client.get("/billing/me", headers=h).json()
    assert me["plan"] == "basic" and me["status"] == "active" and me["scheduled_plan"] is None

    # cancelling a still-pending (authenticated) subscription works and keeps the trial
    _, h2 = mk_teacher(trial=True)
    sid2 = client.post("/billing/subscribe", headers=h2, json={"plan": "basic", "cycle": "monthly"}).json()["subscription_id"]
    FAKE.subscriptions[sid2]["status"] = "authenticated"
    client.post("/billing/verify", headers=h2, json={
        "razorpay_payment_id": "pay_b", "razorpay_subscription_id": sid2,
        "razorpay_signature": sub_sig("pay_b", sid2)})
    r = client.post("/billing/cancel", headers=h2)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "trialing" and r.json()["scheduled_plan"] is None
    assert [c for c in FAKE.calls if c[0] == "subscription.cancel"][-1][1:] == (sid2, {"cancel_at_cycle_end": 0})


def test_gap_failed_payment_dead_end_and_old_sub_keeps_charging():
    """A halted (past_due) subscription used to block re-subscribing with no way out; and
    when a NEW subscription activates, the old one must be cancelled at Razorpay or the
    customer is charged twice."""
    tid, h = mk_teacher(trial=False)
    sid_a = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "monthly"}).json()["subscription_id"]
    FAKE.activate(sid_a)
    client.post("/billing/verify", headers=h, json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid_a,
        "razorpay_signature": sub_sig("pay_1", sid_a)})
    FAKE.subscriptions[sid_a]["status"] = "halted"
    webhook("subscription.halted", "subscription", FAKE.subscriptions[sid_a], "evt_gap2")
    assert client.get("/billing/me", headers=h).json()["status"] == "past_due"

    r = client.post("/billing/subscribe", headers=h, json={"plan": "basic", "cycle": "yearly"})
    assert r.status_code == 200, r.text                       # was 409: a dead end
    sid_b = r.json()["subscription_id"]
    FAKE.activate(sid_b, 365)
    r = client.post("/billing/verify", headers=h, json={
        "razorpay_payment_id": "pay_2", "razorpay_subscription_id": sid_b,
        "razorpay_signature": sub_sig("pay_2", sid_b)})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["billing_cycle"] == "yearly"
    cancels = [c for c in FAKE.calls if c[0] == "subscription.cancel" and c[1] == sid_a]
    assert cancels, "old subscription was left running at Razorpay"
    # late events for the OLD subscription must not disturb the new one
    FAKE.subscriptions[sid_a]["status"] = "cancelled"
    webhook("subscription.cancelled", "subscription", FAKE.subscriptions[sid_a], "evt_gap3")
    me = client.get("/billing/me", headers=h).json()
    assert me["status"] == "active" and me["billing_cycle"] == "yearly"


def test_gap_payment_on_superseded_order_is_not_orphaned():
    """Two open orders for one fee (double-tap / two devices): the fee row only remembers
    the latest, so paying the earlier one used to leave money taken with no fee marked."""
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    db = SessionLocal()
    fee = FeeRecord(student_id=sid, amount_due=500, due_date=datetime.utcnow() + timedelta(days=2))
    db.add(fee)
    db.commit()
    fid = fee.id
    db.close()
    o1 = client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).json()["order_id"]
    db = SessionLocal()   # simulate a second order having replaced the remembered one
    db.query(FeeRecord).filter(FeeRecord.id == fid).update({"razorpay_order_id": "order_replacement"})
    db.commit()
    db.close()
    w = webhook("payment.captured", "payment", {"id": "pay_o1", "order_id": o1}, "evt_gap4")
    assert w.status_code == 200
    db = SessionLocal()
    f = db.query(FeeRecord).filter(FeeRecord.id == fid).first()
    assert f.is_paid and f.razorpay_payment_id == "pay_o1"
    db.close()


def test_gap_duplicate_payment_is_flagged():
    """Teacher records cash, then the student's still-open online order gets paid too."""
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    db = SessionLocal()
    fee = FeeRecord(student_id=sid, amount_due=500, due_date=datetime.utcnow() + timedelta(days=2))
    db.add(fee)
    db.commit()
    fid = fee.id
    db.close()
    o = client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).json()["order_id"]
    assert client.post(f"/payments/fees/{fid}/mark-paid", headers=th).status_code == 200
    webhook("payment.captured", "payment", {"id": "pay_dup", "order_id": o}, "evt_gap5")
    rec = next(r for r in client.get("/payments/records", headers=th).json() if r["id"] == fid)
    assert rec["payment_mode"] == "manual" and rec["duplicate_payment"] is True
    # the same payment reported twice (browser verify + webhook) is NOT a duplicate
    sid2, sh2 = mk_student(teacher_id=tid)
    db = SessionLocal()
    fee2 = FeeRecord(student_id=sid2, amount_due=300, due_date=datetime.utcnow() + timedelta(days=2))
    db.add(fee2)
    db.commit()
    fid2 = fee2.id
    db.close()
    o2 = client.post("/payments/create-order", headers=sh2, json={"fee_record_id": fid2}).json()["order_id"]
    client.post("/payments/verify", headers=sh2, json={
        "razorpay_order_id": o2, "razorpay_payment_id": "pay_ok", "razorpay_signature": order_sig(o2, "pay_ok")})
    webhook("payment.captured", "payment", {"id": "pay_ok", "order_id": o2}, "evt_gap6")
    rec2 = next(r for r in client.get("/payments/records", headers=th).json() if r["id"] == fid2)
    assert rec2["is_paid"] and rec2["duplicate_payment"] is False


def test_gap_cross_tenant_and_odd_webhook_orders():
    tid_a, ha = mk_teacher(trial=False)
    tid_b, hb = mk_teacher(trial=False)
    db = SessionLocal()
    batch_b = Batch(teacher_id=tid_b, name="B-batch")
    db.add(batch_b)
    db.commit()
    bb = batch_b.id
    db.close()
    sb, _ = mk_student(teacher_id=tid_b, batch_id=bb)
    due = (datetime.utcnow() + timedelta(days=3)).isoformat()
    # teacher A can't bill teacher B's student or batch, and nothing gets created
    r = client.post("/payments/fees", headers=ha, json={"student_ids": [sb], "amount": 100, "due_date": due})
    assert r.status_code == 404
    r = client.post("/payments/fees", headers=ha, json={"batch_id": bb, "amount": 100, "due_date": due})
    assert r.status_code == 404
    assert client.get("/payments/records", headers=hb).json() == []
    # validation: amount must be positive, and a target is required
    assert client.post("/payments/fees", headers=hb, json={"student_ids": [sb], "amount": 0, "due_date": due}).status_code == 422
    assert client.post("/payments/fees", headers=hb, json={"amount": 5, "due_date": due}).status_code == 400
    # teacher tokens can't use student endpoints and vice-versa
    assert client.get("/payments/my-fees", headers=ha).status_code == 401

    # Webhooks for orders that aren't ours must be acknowledged, never crash (on Postgres a
    # non-UUID receipt compared against a UUID column would raise and Razorpay would retry forever)
    FAKE.orders["order_foreign"] = {"id": "order_foreign", "status": "paid", "amount": 100, "receipt": "invoice-2026-77"}
    assert webhook("payment.captured", "payment", {"id": "pay_x", "order_id": "order_foreign"}, "evt_odd1").status_code == 200
    assert webhook("payment.captured", "payment", {"id": "pay_y", "order_id": "order_unknown"}, "evt_odd2").status_code == 200
    assert webhook("payment.captured", "payment", {"id": "pay_z"}, "evt_odd3").status_code == 200  # no order at all
    assert webhook("payment.failed", "payment", {"id": "pay_f", "order_id": "order_foreign"}, "evt_odd4").status_code == 200


# ---------------- Phase 1: rate limits + free-plan reminder gating ----------------
def _fee_for(student_id, days=1, amount=500):
    db = SessionLocal()
    fee = FeeRecord(student_id=student_id, amount_due=amount, due_date=datetime.utcnow() + timedelta(days=days))
    db.add(fee)
    db.commit()
    fid = fee.id
    db.close()
    return fid


class _limits:
    """Temporarily override rate-limit settings and start from empty counters."""
    def __init__(self, **kw):
        self.kw = kw

    def __enter__(self):
        self.old = {k: getattr(settings, k) for k in self.kw}
        for k, v in self.kw.items():
            setattr(settings, k, v)
        ratelimit.reset()

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(settings, k, v)
        ratelimit.reset()


def test_rate_limit_create_order():
    tid, th = _paid_teacher()
    s1, sh1 = mk_student(teacher_id=tid)
    s2, sh2 = mk_student(teacher_id=tid)
    f1, f2 = _fee_for(s1), _fee_for(s2)
    with _limits(rate_limit_payment_per_min=3):
        for _ in range(3):
            assert client.post("/payments/create-order", headers=sh1, json={"fee_record_id": f1}).status_code == 200
        r = client.post("/payments/create-order", headers=sh1, json={"fee_record_id": f1})
        assert r.status_code == 429, r.text
        assert isinstance(r.json()["detail"], str) and int(r.headers["Retry-After"]) >= 1
        # limit is per person: another student is unaffected
        assert client.post("/payments/create-order", headers=sh2, json={"fee_record_id": f2}).status_code == 200
    # kill switch
    with _limits(rate_limit_payment_per_min=1, rate_limit_enabled=False):
        for _ in range(4):
            assert client.post("/payments/create-order", headers=sh1, json={"fee_record_id": f1}).status_code == 200
    # limit 0 = unlimited for that bucket
    with _limits(rate_limit_payment_per_min=0):
        for _ in range(4):
            assert client.post("/payments/create-order", headers=sh1, json={"fee_record_id": f1}).status_code == 200


def test_rate_limit_blocked_call_makes_no_razorpay_request():
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_for(sid)
    with _limits(rate_limit_payment_per_min=1):
        assert client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).status_code == 200
        before = len(FAKE.calls)
        assert client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).status_code == 429
        assert len(FAKE.calls) == before


def test_rate_limit_subscribe_and_change_plan():
    _, h1 = mk_teacher(trial=False)
    _, h2 = mk_teacher(trial=False)
    body = {"plan": "basic", "cycle": "monthly"}
    with _limits(rate_limit_billing_per_min=2):
        for _ in range(2):
            assert client.post("/billing/subscribe", headers=h1, json=body).status_code != 429
        before = len(FAKE.calls)
        r = client.post("/billing/subscribe", headers=h1, json=body)
        assert r.status_code == 429 and "Retry-After" in r.headers
        assert len(FAKE.calls) == before  # nothing created at Razorpay
        # buckets are separate: change-plan has its own allowance
        assert client.post("/billing/change-plan", headers=h1, json=body).status_code != 429
        # another account is unaffected
        assert client.post("/billing/subscribe", headers=h2, json=body).status_code != 429


def test_rate_limit_ignores_forged_token_identity():
    # A garbage token must not get its own private bucket per forged subject: those
    # requests fall back to the IP bucket and are rejected by auth anyway.
    with _limits(rate_limit_payment_per_min=2):
        codes = [client.post("/payments/create-order", headers={"Authorization": f"Bearer junk{i}"},
                             json={"fee_record_id": "x"}).status_code for i in range(4)]
        assert codes[:2] == [401, 401] and codes[2:] == [429, 429], codes


def test_free_plan_gets_no_fee_reminders_paid_plan_does():
    sent_to = []
    real = fee_reminders.notify
    fee_reminders.notify = lambda phone, msg, kind, params=None: (sent_to.append((phone, kind)) or "whatsapp")
    try:
        # ---- Free independent teacher: skipped, and left untouched ----
        tid, th = mk_teacher(trial=False)
        db = SessionLocal()
        stu = Student(teacher_id=tid, name="Free Stu", phone=_phone(), parent_phone="7000000001",
                      hashed_password=hash_password("1234"))
        db.add(stu)
        db.commit()
        sid = stu.id
        db.close()
        fid = _fee_for(sid, days=-2)  # already overdue
        res = fee_reminders.send_due_fee_reminders(teacher_id=tid)
        assert res == {"checked": 1, "sent": 0, "failed": 0, "skipped_plan": 1}, res
        assert sent_to == []
        db = SessionLocal()
        assert db.query(FeeRecord).filter(FeeRecord.id == fid).first().last_reminder_sent_at is None
        db.close()

        # manual trigger says so plainly instead of a silent "sent 0"
        r = client.post("/payments/send-reminders-now", headers=th)
        assert r.status_code == 402 and isinstance(r.json()["detail"], str), r.text
        assert sent_to == []

        # ---- upgrade: the SAME fee is now reminded (student + parent) ----
        db = SessionLocal()
        sub = subs.get_or_create_subscription(db, subs.Owner(teacher_id=tid))
        sub.plan, sub.status, sub.current_period_end = "basic", "active", datetime.utcnow() + timedelta(days=20)
        db.commit()
        db.close()
        r = client.post("/payments/send-reminders-now", headers=th)
        assert r.status_code == 200 and r.json()["sent"] == 1 and r.json()["skipped_plan"] == 0, r.text
        assert len(sent_to) == 2 and all(k == "fee_reminder" for _, k in sent_to)
        db = SessionLocal()
        assert db.query(FeeRecord).filter(FeeRecord.id == fid).first().last_reminder_sent_at is not None
        db.close()
        # dedupe still works: second pass same day sends nothing new
        sent_to.clear()
        assert fee_reminders.send_due_fee_reminders(teacher_id=tid)["sent"] == 0 and sent_to == []

        # ---- trial (Pro) owners are covered too ----
        ttid, _ = mk_teacher(trial=True)
        tsid, _ = mk_student(teacher_id=ttid)
        _fee_for(tsid, days=-1)
        assert fee_reminders.send_due_fee_reminders(teacher_id=ttid)["sent"] == 1

        # ---- an institute mixes fine: free institute skipped, paid institute reminded ----
        free_i, _ = mk_institute(trial=False)
        paid_i, _ = mk_institute(trial=False)
        db = SessionLocal()
        sub = subs.get_or_create_subscription(db, subs.Owner(institute_id=paid_i))
        sub.plan, sub.status, sub.current_period_end = "pro", "active", datetime.utcnow() + timedelta(days=20)
        db.commit()
        db.close()
        fs, _ = mk_student(institute_id=free_i)
        ps, _ = mk_student(institute_id=paid_i)
        _fee_for(fs, days=-1)
        _fee_for(ps, days=-1)
        assert fee_reminders.send_due_fee_reminders(institute_id=free_i)["skipped_plan"] == 1
        assert fee_reminders.send_due_fee_reminders(institute_id=paid_i)["sent"] == 1
    finally:
        fee_reminders.notify = real


def test_plan_catalog_exposes_fee_reminders():
    plans_out = {p["key"]: p for p in client.get("/billing/plans").json()}
    assert plans_out["free"]["fee_reminders"] is False
    assert plans_out["basic"]["fee_reminders"] is True and plans_out["pro"]["fee_reminders"] is True
    _, th = mk_teacher(trial=False)
    assert client.get("/billing/me", headers=th).json()["fee_reminders"] is False



# ---------------- Phase 2: parents pay their child's fees ----------------
def _parent_h(student_id):
    return {"Authorization": f"Bearer {create_access_token(student_id, 'parent')}"}


def test_parent_pays_childs_fee_end_to_end():
    tid, th = _paid_teacher(account="acc_parent_t")
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_for(sid, days=3, amount=1200)
    ph = _parent_h(sid)

    r = client.get("/parents/my-fees", headers=ph)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["online_payment_available"] is True
    assert [f["id"] for f in body["fees"]] == [fid] and body["fees"][0]["is_paid"] is False

    r = client.post("/parents/create-order", headers=ph, json={"fee_record_id": fid})
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["amount_paise"] == 120000 and order["key_id"] == "rzp_test_key"
    t = FAKE.orders[order["order_id"]]["body"]["transfers"][0]
    # money goes to the TEACHER's linked account minus the platform cut - never the parent/platform
    assert t["account"] == "acc_parent_t" and t["amount"] == 120000 - 2400

    # parent and child tapping Pay on the same fee share the one open order
    again = client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).json()
    assert again["order_id"] == order["order_id"]

    pid = "pay_parent_1"
    bad = client.post("/parents/verify", headers=ph, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": pid, "razorpay_signature": "bad"})
    assert bad.status_code == 400
    ok = client.post("/parents/verify", headers=ph, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": pid,
        "razorpay_signature": order_sig(order["order_id"], pid)})
    assert ok.status_code == 200 and ok.json() == {"status": "paid"}

    # the webhook after the browser call is a harmless no-op, and nothing is flagged duplicate
    assert webhook("payment.captured", "payment", {"id": pid, "order_id": order["order_id"]}, "evt_parent1").status_code == 200
    db = SessionLocal()
    f = db.query(FeeRecord).filter(FeeRecord.id == fid).first()
    assert f.is_paid and f.amount_paid == 1200 and f.payment_mode == "online"
    assert f.razorpay_payment_id == pid and not f.duplicate_payment_id
    db.close()

    # visible as paid to parent, child and teacher; can't be paid twice
    assert client.get("/parents/my-fees", headers=ph).json()["fees"][0]["is_paid"] is True
    assert client.get("/payments/my-fees", headers=sh).json()["fees"][0]["is_paid"] is True
    assert client.get("/payments/records", headers=th).json()[0]["is_paid"] is True
    assert client.post("/parents/create-order", headers=ph, json={"fee_record_id": fid}).status_code == 400


def test_parent_cannot_touch_another_childs_fee():
    tid, _ = _paid_teacher(account="acc_x")
    mine, _ = mk_student(teacher_id=tid)
    sibling_of_a_stranger, _ = mk_student(teacher_id=tid)  # same teacher, different family
    other_fee = _fee_for(sibling_of_a_stranger)
    ph = _parent_h(mine)

    assert client.post("/parents/create-order", headers=ph, json={"fee_record_id": other_fee}).status_code == 404
    assert client.post("/parents/create-order", headers=ph, json={"fee_record_id": "nope"}).status_code == 404
    assert client.get("/parents/my-fees", headers=ph).json()["fees"] == []

    # ...nor settle it by verifying a real, correctly-signed payment against it
    stranger_h = _parent_h(sibling_of_a_stranger)
    order = client.post("/parents/create-order", headers=stranger_h, json={"fee_record_id": other_fee}).json()
    r = client.post("/parents/verify", headers=ph, json={
        "razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_steal",
        "razorpay_signature": order_sig(order["order_id"], "pay_steal")})
    assert r.status_code == 404
    db = SessionLocal()
    assert not db.query(FeeRecord).filter(FeeRecord.id == other_fee).first().is_paid
    db.close()


def test_parent_routes_reject_the_wrong_role():
    tid, th = _paid_teacher(account="acc_y")
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_for(sid)
    ph = _parent_h(sid)
    for h in (sh, th, {}):  # student, teacher, no token at all
        assert client.get("/parents/my-fees", headers=h).status_code == 401
        assert client.post("/parents/create-order", headers=h, json={"fee_record_id": fid}).status_code == 401
        assert client.post("/parents/verify", headers=h, json={
            "razorpay_order_id": "o", "razorpay_payment_id": "p", "razorpay_signature": "s"}).status_code == 401
    # and a parent token can't use the student's own payment routes
    assert client.post("/payments/create-order", headers=ph, json={"fee_record_id": fid}).status_code == 401
    assert client.get("/payments/my-fees", headers=ph).status_code == 401


def test_parent_online_payment_needs_plan_and_payout_account():
    tid, _ = mk_teacher(trial=False)  # Free, no linked account
    sid, _ = mk_student(teacher_id=tid)
    fid = _fee_for(sid)
    ph = _parent_h(sid)
    assert client.get("/parents/my-fees", headers=ph).json()["online_payment_available"] is False
    r = client.post("/parents/create-order", headers=ph, json={"fee_record_id": fid})
    assert r.status_code == 409 and isinstance(r.json()["detail"], str)


def test_parent_create_order_has_its_own_rate_limit_bucket():
    tid, _ = _paid_teacher(account="acc_z")
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_for(sid)
    ph = _parent_h(sid)
    with _limits(rate_limit_payment_per_min=2):
        for _ in range(2):
            assert client.post("/parents/create-order", headers=ph, json={"fee_record_id": fid}).status_code == 200
        before = len(FAKE.calls)
        r = client.post("/parents/create-order", headers=ph, json={"fee_record_id": fid})
        assert r.status_code == 429 and len(FAKE.calls) == before
        # the child's own quota is untouched by the parent's taps (same user id, different bucket)
        assert client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).status_code == 200


def test_legacy_parent_fees_endpoint_still_works():
    tid, _ = mk_teacher(trial=False)
    sid, _ = mk_student(teacher_id=tid)
    fid = _fee_for(sid)
    r = client.get("/parents/fees", headers=_parent_h(sid))
    assert r.status_code == 200 and [f["id"] for f in r.json()] == [fid]



# ---------------- Phase 3: ledger, partial payments, receipts, refunds, notices ----------------
def _fee_row(fid):
    db = SessionLocal()
    f = db.query(FeeRecord).filter(FeeRecord.id == fid).first()
    out = {
        "paid": bool(f.is_paid), "amount_paid": f.amount_paid, "paid_at": f.paid_at, "mode": f.payment_mode,
        "dup": f.duplicate_payment_id, "rz": f.razorpay_payment_id,
        "net": sum(p.amount_paise - p.refunded_paise for p in f.payments if p.status == "paid"),
        "payments": [(p.status, p.amount_paise, p.refunded_paise, p.mode, p.paid_by) for p in f.payments],
    }
    db.close()
    return out


def _consistent(fid):
    """The cached totals on the fee must always equal what the ledger says."""
    r = _fee_row(fid)
    assert round(r["amount_paid"] * 100) == r["net"], r
    return r


def _fee_with(student_id, amount=1000, partial=False, days=3):
    db = SessionLocal()
    fee = FeeRecord(student_id=student_id, amount_due=amount, allow_partial=partial,
                    due_date=datetime.utcnow() + timedelta(days=days))
    db.add(fee)
    db.commit()
    fid = fee.id
    db.close()
    return fid


def _pay_online(headers, fid, amount, pid, role="student"):
    """create-order + verify as the given role; returns (order, verify response)."""
    base = "/payments" if role == "student" else "/parents"
    body = {"fee_record_id": fid}
    if amount is not None:
        body["amount"] = amount
    r = client.post(f"{base}/create-order", headers=headers, json=body)
    assert r.status_code == 200, r.text
    o = r.json()
    v = client.post(f"{base}/verify", headers=headers, json={
        "razorpay_order_id": o["order_id"], "razorpay_payment_id": pid,
        "razorpay_signature": order_sig(o["order_id"], pid)})
    return o, v


def _refund(pid, total_paise, event_id, amount=None):
    FAKE.payments[pid] = {"id": pid, "amount_refunded": total_paise}
    return webhook("refund.processed", "refund",
                   {"id": "rfnd_" + event_id, "payment_id": pid, "amount": amount or total_paise}, event_id)


def test_partial_payments_online_student_then_parent():
    tid, th = _paid_teacher(account="acc_partial")
    sid, sh = mk_student(teacher_id=tid)
    ph = _parent_h(sid)
    fid = _fee_with(sid, 1000, partial=True)

    o1, v = _pay_online(sh, fid, 400, "pay_p1")
    assert o1["amount_paise"] == 40000 and v.status_code == 200
    # the order's Route transfer is for THIS instalment (minus the 2% test commission)
    assert FAKE.orders[o1["order_id"]]["body"]["transfers"][0]["amount"] == 40000 - 800
    r = _consistent(fid)
    assert r["paid"] is False and r["amount_paid"] == 400 and r["paid_at"] is None
    assert r["payments"] == [("paid", 40000, 0, "online", "student")]

    mine = client.get("/payments/my-fees", headers=sh).json()["fees"][0]
    assert mine["allow_partial"] is True and mine["amount_paid"] == 400 and len(mine["payments"]) == 1
    assert mine["payments"][0]["receipt_no"].startswith("R-") and mine["payments"][0]["paid_by"] == "student"

    # the parent pays the rest (no amount = whatever is still owed)
    o2, v = _pay_online(ph, fid, None, "pay_p2", role="parent")
    assert o2["amount_paise"] == 60000 and v.status_code == 200
    r = _consistent(fid)
    assert r["paid"] is True and r["amount_paid"] == 1000 and r["paid_at"] is not None
    assert r["dup"] is None and r["mode"] == "online" and r["rz"] == "pay_p2"
    assert [x[4] for x in r["payments"]] == ["student", "parent"]
    assert client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).status_code == 400


def test_part_payment_rules():
    tid, _ = _paid_teacher(account="acc_rules")
    sid, sh = mk_student(teacher_id=tid)
    full_only = _fee_with(sid, 1000, partial=False)
    inst = _fee_with(sid, 1000, partial=True)

    def order(fid, amount):
        return client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid, "amount": amount})

    # a fee that must be paid in full: a smaller amount is refused, the exact balance is fine
    r = order(full_only, 400)
    assert r.status_code == 400 and "in full" in r.json()["detail"]
    assert order(full_only, 1000).status_code == 200
    # instalment fee: bounds
    assert order(inst, 1500).status_code == 400            # more than owed
    assert order(inst, 0.5).status_code == 400             # under Rs.1
    r = order(inst, 999.5)                                  # would leave Rs.0.50 unpayable online
    assert r.status_code == 400 and "under Rs.1" in r.json()["detail"]
    assert client.post("/payments/create-order", headers=sh, json={"fee_record_id": inst, "amount": -5}).status_code == 422
    # reuse: same amount -> same open order, different amount -> a new one
    a = order(inst, 300).json()
    assert order(inst, 300).json()["order_id"] == a["order_id"]
    assert order(inst, 301).json()["order_id"] != a["order_id"]


def test_manual_part_payments_and_delete_rules():
    tid, th = _paid_teacher()
    sid, _ = mk_student(teacher_id=tid)
    fid = _fee_with(sid, 1000, partial=False)  # online is full-only, but the teacher can still take instalments

    r = client.post(f"/payments/fees/{fid}/mark-paid", headers=th, json={"amount": 300})
    assert r.status_code == 200 and r.json()["is_paid"] is False and r.json()["amount_paid"] == 300
    assert r.json()["payments"][0]["mode"] == "manual" and r.json()["payments"][0]["paid_by"] == "teacher"
    assert client.post(f"/payments/fees/{fid}/mark-paid", headers=th, json={"amount": 800}).status_code == 400  # > 700 left
    assert client.post(f"/payments/fees/{fid}/mark-paid", headers=th, json={"amount": 0}).status_code == 422
    assert client.delete(f"/payments/fees/{fid}", headers=th).status_code == 400  # money was received on it
    r = client.post(f"/payments/fees/{fid}/mark-paid", headers=th)  # no body = the rest
    assert r.status_code == 200 and r.json()["is_paid"] is True and r.json()["amount_paid"] == 1000
    assert client.post(f"/payments/fees/{fid}/mark-paid", headers=th).status_code == 400
    assert _consistent(fid)["mode"] == "manual"


def test_abandoned_checkout_attempts_dont_count_and_delete_with_the_fee():
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_with(sid, 500)
    client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid})  # opened, never paid
    r = _consistent(fid)
    assert r["paid"] is False and r["amount_paid"] == 0 and r["payments"][0][0] == "pending"
    assert client.get("/payments/my-fees", headers=sh).json()["fees"][0]["payments"] == []  # pending is never shown
    assert client.delete(f"/payments/fees/{fid}", headers=th).status_code == 200
    db = SessionLocal()
    assert db.query(FeePayment).filter(FeePayment.fee_record_id == fid).count() == 0
    db.close()


def test_overpayment_via_stale_order_is_flagged_not_swallowed():
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_with(sid, 1000, partial=True)
    big = client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).json()      # Rs.1000 order left open
    _pay_online(sh, fid, 400, "pay_small")                                                            # Rs.400 paid
    # the old Rs.1000 order now also gets paid -> 1400 received for a 1000 fee
    assert webhook("payment.captured", "payment", {"id": "pay_big", "order_id": big["order_id"]}, "evt_over1").status_code == 200
    r = _consistent(fid)
    assert r["paid"] is True and r["net"] == 140000 and r["dup"] == "pay_big"
    rec = next(x for x in client.get("/payments/records", headers=th).json() if x["id"] == fid)
    assert rec["duplicate_payment"] is True
    # Razorpay refunds the whole Rs.1000 payment -> the flag clears, and the fee honestly
    # shows only the Rs.400 genuinely held (so Rs.600 is owed again)
    assert _refund("pay_big", 100000, "evt_over_refund").status_code == 200
    r = _consistent(fid)
    assert r["dup"] is None and r["paid"] is False and r["amount_paid"] == 400 and r["net"] == 40000


def test_refund_webhook_reverses_payment_and_is_idempotent():
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_with(sid, 500)
    _pay_online(sh, fid, None, "pay_r1")
    assert _consistent(fid)["paid"] is True

    # partial refund: Rs.200 back -> fee is owed Rs.200 again
    assert _refund("pay_r1", 20000, "evt_rf1").status_code == 200
    r = _consistent(fid)
    assert r["paid"] is False and r["amount_paid"] == 300 and r["paid_at"] is None
    assert r["payments"][0][2] == 20000
    mine = client.get("/payments/my-fees", headers=sh).json()["fees"][0]
    assert mine["payments"][0]["status"] == "partially_refunded" and mine["payments"][0]["refunded_amount"] == 200

    # same event redelivered, and a DIFFERENT event reporting the same cumulative total: no drift
    assert webhook("refund.processed", "refund", {"id": "x", "payment_id": "pay_r1", "amount": 20000}, "evt_rf1").json()["status"] == "duplicate"
    assert _refund("pay_r1", 20000, "evt_rf1b").status_code == 200
    assert _consistent(fid)["amount_paid"] == 300

    # the rest refunded -> fully refunded, unpaid again, and the student can pay again
    assert _refund("pay_r1", 50000, "evt_rf2").status_code == 200
    r = _consistent(fid)
    assert r["paid"] is False and r["amount_paid"] == 0
    assert client.get("/payments/my-fees", headers=sh).json()["fees"][0]["payments"][0]["status"] == "refunded"
    assert client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).status_code == 200


def test_refund_webhook_edge_cases():
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_with(sid, 500)
    _pay_online(sh, fid, None, "pay_e1")
    # unknown payment / no payment id: acknowledged, nothing changes
    assert _refund("pay_not_ours", 100, "evt_e0").status_code == 200
    assert webhook("refund.processed", "refund", {"id": "r"}, "evt_e00").status_code == 200
    # can't reach Razorpay to confirm: 503 so Razorpay retries, nothing applied, event NOT marked processed
    FAKE.fail_payment_fetch = True
    try:
        assert _refund("pay_e1", 50000, "evt_e1").status_code == 503
    finally:
        FAKE.fail_payment_fetch = False
    assert _consistent(fid)["paid"] is True
    assert _refund("pay_e1", 50000, "evt_e1").status_code == 200  # the retry goes through
    assert _consistent(fid)["paid"] is False
    # a refund can never exceed what the payment was
    assert _refund("pay_e1", 999999, "evt_e2").status_code == 200
    assert _fee_row(fid)["payments"][0][2] == 50000

    # a duplicate flag set before the ledger existed is cleared by that payment's refund
    sid2, _ = mk_student(teacher_id=tid)
    fid2 = _fee_with(sid2, 300)
    db = SessionLocal()
    db.query(FeeRecord).filter(FeeRecord.id == fid2).update({"duplicate_payment_id": "pay_legacy_dup"})
    db.commit()
    db.close()
    assert _refund("pay_legacy_dup", 30000, "evt_e3").status_code == 200
    assert _fee_row(fid2)["dup"] is None


def test_receipts_content_and_isolation():
    tid, th = _paid_teacher(account="acc_rc")
    sid, sh = mk_student(teacher_id=tid)
    other_sid, osh = mk_student(teacher_id=tid)
    _, other_teacher = _paid_teacher()
    fid = _fee_with(sid, 800, partial=True)
    _pay_online(sh, fid, 300, "pay_rc1")
    pay = client.get("/payments/my-fees", headers=sh).json()["fees"][0]["payments"][0]

    for url, h in ((f"/payments/my-receipts/{pay['id']}", sh), (f"/parents/receipts/{pay['id']}", _parent_h(sid)),
                   (f"/payments/receipts/{pay['id']}", th)):
        r = client.get(url, headers=h)
        assert r.status_code == 200, (url, r.text)
        b = r.json()
        assert b["receipt_no"] == pay["receipt_no"] and b["issued_to"] == "Stu" and b["issued_by"] == "T"
        assert b["amount"] == 300 and b["fee_total"] == 800 and b["fee_balance"] == 500
        assert b["mode"] == "online" and b["razorpay_payment_id"] == "pay_rc1" and b["status"] == "paid"

    # nobody else can read it: another student, another student's parent, another teacher
    assert client.get(f"/payments/my-receipts/{pay['id']}", headers=osh).status_code == 404
    assert client.get(f"/parents/receipts/{pay['id']}", headers=_parent_h(other_sid)).status_code == 404
    assert client.get(f"/payments/receipts/{pay['id']}", headers=other_teacher).status_code == 404
    assert client.get("/payments/receipts/nope", headers=th).status_code == 404
    # a manual receipt has no Razorpay id; an unpaid (pending) attempt has no receipt at all
    client.post(f"/payments/fees/{fid}/mark-paid", headers=th, json={"amount": 100})
    man = next(p for p in client.get("/payments/records", headers=th).json()[0]["payments"] if p["mode"] == "manual")
    b = client.get(f"/payments/receipts/{man['id']}", headers=th).json()
    assert b["razorpay_payment_id"] is None and b["mode"] == "manual"
    client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid, "amount": 50})
    db = SessionLocal()
    pending = db.query(FeePayment).filter(FeePayment.fee_record_id == fid, FeePayment.status == "pending").first().id
    db.close()
    assert client.get(f"/payments/my-receipts/{pending}", headers=sh).status_code == 404


def test_fee_and_receipt_notices_paid_plan_only_and_exactly_once():
    # ---- Free plan: nothing is sent ----
    ftid, fth = mk_teacher(trial=False)
    fsid, _ = mk_student(teacher_id=ftid)
    SENT.clear()
    due = (datetime.utcnow() + timedelta(days=4)).isoformat()
    assert client.post("/payments/fees", headers=fth, json={"student_ids": [fsid], "amount": 100, "due_date": due}).status_code == 200
    fid_free = client.get("/payments/records", headers=fth).json()[0]["id"]
    assert client.post(f"/payments/fees/{fid_free}/mark-paid", headers=fth).status_code == 200
    assert SENT == []

    # ---- paid plan: fee-created notice to student AND parent ----
    tid, th = _paid_teacher(account="acc_n")
    sid, sh = mk_student(teacher_id=tid)
    db = SessionLocal()
    db.query(Student).filter(Student.id == sid).update({"parent_phone": "7111111111"})
    db.commit()
    stu_phone = db.query(Student.phone).filter(Student.id == sid).first()[0]
    db.close()
    SENT.clear()
    r = client.post("/payments/fees", headers=th, json={
        "student_ids": [sid], "amount": 1000, "due_date": due, "description": "Term 1", "allow_partial": True})
    assert r.status_code == 200
    assert {(p, t) for p, t, _, _ in SENT} == {(stu_phone, "fee_created"), ("7111111111", "fee_created")}
    params = SENT[0][2]
    assert params[0] == "Stu" and params[1] == "1,000.00" and params[3] == "Term 1"
    assert "Rs.1,000.00" in SENT[0][3] and "Term 1" in SENT[0][3]
    fid = next(x["id"] for x in client.get("/payments/records", headers=th).json() if x["student_id"] == sid)
    assert client.get("/payments/records", headers=th).json()[0]["allow_partial"] is True

    # ---- online part-payment: ONE receipt even though verify AND webhook both report it ----
    SENT.clear()
    o, _ = _pay_online(sh, fid, 400, "pay_n1")
    webhook("payment.captured", "payment", {"id": "pay_n1", "order_id": o["order_id"]}, "evt_n1")
    webhook("order.paid", "payment", {"id": "pay_n1", "order_id": o["order_id"]}, "evt_n1b")
    assert [t for _, t, _, _ in SENT].count("payment_receipt") == 2  # student + parent, once each
    assert all("Balance due: Rs.600.00" in m for _, _, _, m in SENT)
    rno = SENT[0][2][2]
    assert rno.startswith("R-") and len(rno) == 12

    # ---- manual payment for the rest: receipt says fully paid ----
    SENT.clear()
    assert client.post(f"/payments/fees/{fid}/mark-paid", headers=th).status_code == 200
    assert len(SENT) == 2 and all("Fee fully paid." in m for _, _, _, m in SENT)

    # ---- a failing provider never breaks the request, and the fee is still created ----
    real = fee_notices.notify
    def boom(*a, **k):
        raise RuntimeError("provider down")
    fee_notices.notify = boom
    try:
        sid3, _ = mk_student(teacher_id=tid)
        assert client.post("/payments/fees", headers=th, json={"student_ids": [sid3], "amount": 50, "due_date": due}).status_code == 200
        fid3 = next(x["id"] for x in client.get("/payments/records", headers=th).json() if x["student_id"] == sid3)
        o3, v3 = _pay_online(client_headers_for(sid3), fid3, None, "pay_n3")
        assert v3.status_code == 200 and _consistent(fid3)["paid"] is True  # payment unaffected by the dead provider
    finally:
        fee_notices.notify = real


def client_headers_for(student_id):
    return {"Authorization": f"Bearer {create_access_token(student_id, 'student')}"}


def test_paid_by_is_whoever_completes_checkout_not_who_opened_it():
    tid, th = _paid_teacher(account="acc_pb")
    sid, sh = mk_student(teacher_id=tid)
    ph = _parent_h(sid)
    fid = _fee_with(sid, 500)
    o_parent = client.post("/parents/create-order", headers=ph, json={"fee_record_id": fid}).json()
    # the child opens the same fee and gets the SAME open order, then is the one who pays it
    o_child = client.post("/payments/create-order", headers=sh, json={"fee_record_id": fid}).json()
    assert o_child["order_id"] == o_parent["order_id"]
    v = client.post("/payments/verify", headers=sh, json={
        "razorpay_order_id": o_child["order_id"], "razorpay_payment_id": "pay_pb",
        "razorpay_signature": order_sig(o_child["order_id"], "pay_pb")})
    assert v.status_code == 200
    assert _fee_row(fid)["payments"] == [("paid", 50000, 0, "online", "student")]


def test_ledger_stays_consistent_through_a_messy_sequence():
    tid, th = _paid_teacher(account="acc_mess")
    sid, sh = mk_student(teacher_id=tid)
    fid = _fee_with(sid, 900, partial=True)
    steps = []
    _pay_online(sh, fid, 200, "pay_m1"); steps.append(_consistent(fid)["amount_paid"])
    client.post(f"/payments/fees/{fid}/mark-paid", headers=th, json={"amount": 100}); steps.append(_consistent(fid)["amount_paid"])
    _refund("pay_m1", 5000, "evt_m1"); steps.append(_consistent(fid)["amount_paid"])
    _pay_online(sh, fid, None, "pay_m2"); steps.append(_consistent(fid)["amount_paid"])
    assert steps == [200, 300, 250, 900]
    assert _consistent(fid)["paid"] is True
    _refund("pay_m2", 80000, "evt_m2")
    # pay_m2 was only Rs.650, so a (bogus) larger refund total is clamped to it: that payment
    # is fully refunded and what remains is pay_m1's 150 + the 100 recorded by hand
    r = _consistent(fid)
    assert r["paid"] is False and r["amount_paid"] == 250
    assert len(next(x for x in client.get("/payments/records", headers=th).json() if x["id"] == fid)["payments"]) == 3



# ---------------- Phase 4.0: verify rate limits + reminder amount variable ----------------
def test_verify_endpoints_are_rate_limited_and_blocked_calls_never_reach_razorpay():
    tid, th = _paid_teacher()
    sid, sh = mk_student(teacher_id=tid)
    _, bh = mk_teacher(trial=False)
    _, ph = _parent_h(sid), None
    bad_fee = {"razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x", "razorpay_signature": "bad"}
    bad_sub = {"razorpay_payment_id": "pay_x", "razorpay_subscription_id": "sub_x", "razorpay_signature": "bad"}
    with _limits(rate_limit_verify_per_min=2):
        for url, hdr, body in (("/payments/verify", sh, bad_fee),
                               ("/parents/verify", _parent_h(sid), bad_fee),
                               ("/billing/verify", bh, bad_sub)):
            codes = [client.post(url, headers=hdr, json=body).status_code for _ in range(4)]
            assert codes[:2] != [429, 429] and codes[2:] == [429, 429], (url, codes)
        # separate buckets: hammering /payments/verify didn't use up /billing/verify for someone else
        _, other = mk_teacher(trial=False)
        assert client.post("/billing/verify", headers=other, json=bad_sub).status_code != 429
    # kill switch + 0 = unlimited
    with _limits(rate_limit_verify_per_min=1, rate_limit_enabled=False):
        assert all(client.post("/payments/verify", headers=sh, json=bad_fee).status_code != 429 for _ in range(3))
    with _limits(rate_limit_verify_per_min=0):
        assert all(client.post("/payments/verify", headers=sh, json=bad_fee).status_code != 429 for _ in range(3))


def test_overdue_reminder_whatsapp_variables_only_when_template_has_them():
    calls = []
    real = fee_reminders.notify
    fee_reminders.notify = lambda phone, msg, kind, params=None: (calls.append((phone, kind, params, msg)) or "whatsapp")
    old = (settings.fee_reminder_template, settings.fee_reminder_template_vars)
    try:
        tid, _ = mk_teacher(trial=True)
        sid, _ = mk_student(teacher_id=tid)
        _fee_for(sid, days=-2, amount=750)
        # default: the original no-variable template, params None (Meta rejects variables it doesn't expect)
        fee_reminders.send_due_fee_reminders(teacher_id=tid)
        assert calls and all(k == "fee_reminder" and p is None for _, k, p, _ in calls), calls
        assert "750.00" in calls[0][3]  # the SMS fallback text always carried the amount

        # switched on: new template name + 4 variables in the documented order
        calls.clear()
        settings.fee_reminder_template, settings.fee_reminder_template_vars = "fee_reminder_v2", True
        tid2, _ = mk_teacher(trial=True)
        sid2, _ = mk_student(teacher_id=tid2)
        _fee_for(sid2, days=-2, amount=750)
        fee_reminders.send_due_fee_reminders(teacher_id=tid2)
        assert calls
        _, kind, params, _ = calls[0]
        assert kind == "fee_reminder_v2" and len(params) == 4, calls[0]
        assert params[1] == "750.00" and params[3] == "was due", params
    finally:
        fee_reminders.notify = real
        settings.fee_reminder_template, settings.fee_reminder_template_vars = old



# ---------------- Phase 4.1: GST + invoices ----------------
def _a_subscription():
    """A real Subscription row (a trialing teacher's) to hang invoices on."""
    tid, _ = mk_teacher(trial=True)
    db = SessionLocal()
    sub = subs.get_subscription(db, subs.Owner(teacher_id=tid))
    return db, sub


def test_gst_is_added_on_top_rounds_half_up_and_round_trips_exactly():
    # the real catalog numbers: Rs 499 + 18% = Rs 88.82... no: 89.82 GST, 588.82 total
    assert invoices.gst_on_top(49900, 1800) == (8982, 58882)
    assert invoices.gst_on_top(149900, 1800) == (26982, 176882)
    assert invoices.gst_on_top(1499000, 1800) == (269820, 1768820)
    # half-up on the GST amount: 5% of 10 paise = 0.5 -> 1 ; of 9 paise = 0.45 -> 0
    assert invoices.gst_on_top(10, 500) == (1, 11)
    assert invoices.gst_on_top(9, 500) == (0, 9)
    assert invoices.gst_on_top(12345, 0) == (0, 12345)  # a 0% rate is just "no GST"
    # backing GST out of a total gives the original base back - for EVERY whole-paisa base,
    # at the rates GST actually uses, so an invoice built from a real charge never drifts
    for rate in (0, 500, 1200, 1800, 2800):
        for base in range(0, 60001):
            gst, total = invoices.gst_on_top(base, rate)
            assert total == base + gst
            assert invoices.split_inclusive(total, rate) == (base, gst), (rate, base)
    for bad in (lambda: invoices.gst_on_top(-1, 1800), lambda: invoices.split_inclusive(-1, 1800),
                lambda: invoices.gst_on_top(100, -5)):
        try:
            bad()
        except ValueError:
            pass
        else:
            raise AssertionError("negative money / rate must be rejected")
    # the configured rate is what's used when none is passed
    old = settings.gst_rate_bps
    try:
        settings.gst_rate_bps = 500
        assert invoices.gst_on_top(10000) == (500, 10500)
    finally:
        settings.gst_rate_bps = old


def test_plan_catalog_shows_base_price_plus_gst_and_total():
    cat = {p["key"]: p for p in client.get("/billing/plans").json()}
    basic, pro, free = cat["basic"], cat["pro"], cat["free"]
    # the existing fields are unchanged (still BASE rupees) so nothing that reads them breaks
    assert basic["price_monthly"] == 499 and basic["price_yearly"] == 4990
    assert basic["gst_rate_percent"] == 18
    assert (basic["gst_monthly_paise"], basic["total_monthly_paise"]) == (8982, 58882)
    assert (basic["gst_yearly_paise"], basic["total_yearly_paise"]) == (89820, 588820)
    assert (pro["gst_monthly_paise"], pro["total_monthly_paise"]) == (26982, 176882)
    for p in cat.values():  # total is always exactly base + GST, in paise
        assert p["total_monthly_paise"] == p["price_monthly"] * 100 + p["gst_monthly_paise"]
        assert p["total_yearly_paise"] == p["price_yearly"] * 100 + p["gst_yearly_paise"]
    assert free["total_monthly_paise"] == 0 and free["gst_yearly_paise"] == 0  # free stays free


def test_financial_year_is_april_to_march_decided_in_india_time():
    fy = invoices.financial_year_label
    assert fy(datetime(2026, 10, 1)) == "2627"
    assert fy(datetime(2026, 4, 1, 12, 0)) == "2627"
    assert fy(datetime(2026, 3, 31, 12, 0)) == "2526"
    assert fy(datetime(2027, 1, 15)) == "2627"
    # 18:30 UTC on 31 March is already midnight on 1 April in IST -> the new year
    assert fy(datetime(2026, 3, 31, 18, 29, 59)) == "2526"
    assert fy(datetime(2026, 3, 31, 18, 30, 0)) == "2627"
    assert fy(datetime(2099, 12, 31)) == "9900"  # century rollover keeps 2+2 digits


def test_invoice_numbers_are_consecutive_per_financial_year():
    db, sub = _a_subscription()
    a1 = datetime(2031, 5, 10)      # FY 3132
    b1 = datetime(2032, 3, 31, 12)  # still FY 3132
    c1 = datetime(2032, 4, 2)       # FY 3233 - sequence starts over
    nums = [invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                   razorpay_payment_id=f"pay_num_{i}", issued_at=when).invoice_number
            for i, when in enumerate([a1, a1, b1, c1, a1, c1])]
    db.commit()
    assert nums == [f"WND/3132/{n:06d}" for n in (1, 2, 3)] + ["WND/3233/000001", "WND/3132/000004", "WND/3233/000002"], nums
    assert all(len(n) <= invoices.MAX_INVOICE_NUMBER_LEN for n in nums)
    assert len(set(nums)) == len(nums)
    db.close()


def test_issuing_an_invoice_is_idempotent_and_never_burns_a_number():
    db, sub = _a_subscription()
    when = datetime(2033, 6, 1)
    first = invoices.issue_invoice(db, sub, plan="pro", cycle="yearly", total_paise=1768820,
                                   razorpay_payment_id="pay_idem_1", issued_at=when,
                                   period_start=when, period_end=datetime(2034, 6, 1))
    db.commit()
    again = invoices.issue_invoice(db, sub, plan="pro", cycle="yearly", total_paise=1768820,
                                   razorpay_payment_id="pay_idem_1", issued_at=when)
    db.commit()
    assert again.id == first.id and again.invoice_number == first.invoice_number
    assert db.query(Invoice).filter(Invoice.razorpay_payment_id == "pay_idem_1").count() == 1
    nxt = invoices.issue_invoice(db, sub, plan="pro", cycle="yearly", total_paise=1768820,
                                 razorpay_payment_id="pay_idem_2", issued_at=when)
    db.commit()
    assert int(nxt.invoice_number[-6:]) == int(first.invoice_number[-6:]) + 1  # no gap from the repeat
    # the numbers on the invoice are what was charged, split exactly
    assert (first.base_paise, first.gst_paise, first.total_paise) == (1499000, 269820, 1768820)
    assert first.gst_rate_bps == 1800 and first.currency == "INR" and first.kind == "subscription"
    assert first.description == "Pro plan - yearly subscription"
    assert first.period_end == datetime(2034, 6, 1)
    db.close()


def test_losing_a_race_for_the_same_payment_returns_the_winner_and_gives_the_number_back():
    db, sub = _a_subscription()
    when = datetime(2034, 6, 1)
    winner = invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                    razorpay_payment_id="pay_race", issued_at=when)
    db.commit()
    # simulate the loser: its "does one exist yet?" check ran BEFORE the winner committed
    real, calls = invoices.get_by_payment, [0]

    def blind_first_time(d, pid):
        calls[0] += 1
        return None if calls[0] == 1 else real(d, pid)

    invoices.get_by_payment = blind_first_time
    try:
        loser = invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                       razorpay_payment_id="pay_race", issued_at=when)
    finally:
        invoices.get_by_payment = real
    db.commit()
    assert loser.id == winner.id
    assert db.query(Invoice).filter(Invoice.razorpay_payment_id == "pay_race").count() == 1
    nxt = invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                 razorpay_payment_id="pay_race_next", issued_at=when)
    db.commit()
    assert int(nxt.invoice_number[-6:]) == int(winner.invoice_number[-6:]) + 1, "the loser's number leaked"
    assert db.query(InvoiceCounter).filter(InvoiceCounter.fy == "3435").one().last_seq == 2
    db.close()


def test_invoice_from_our_own_base_amount_adds_gst_and_input_rules():
    db, sub = _a_subscription()
    inv = invoices.issue_invoice(db, sub, plan="pro", cycle="monthly", base_paise=100000, kind="proration",
                                 description="Upgrade to Pro (prorated)", issued_at=datetime(2035, 7, 1))
    db.commit()
    assert (inv.base_paise, inv.gst_paise, inv.total_paise, inv.kind) == (100000, 18000, 118000, "proration")
    assert inv.razorpay_payment_id is None and inv.description == "Upgrade to Pro (prorated)"
    # two invoices with no payment id are fine (NULLs don't collide in the unique index)
    inv2 = invoices.issue_invoice(db, sub, plan="pro", cycle="monthly", base_paise=5, issued_at=datetime(2035, 7, 1))
    db.commit()
    assert inv2.invoice_number != inv.invoice_number
    # exactly one of total/base, never both or neither
    for kw in ({}, {"total_paise": 100, "base_paise": 100}):
        try:
            invoices.issue_invoice(db, sub, plan="pro", cycle="monthly", **kw)
        except ValueError:
            pass
        else:
            raise AssertionError("must require exactly one of total_paise / base_paise")
    db.close()


def test_invoice_number_too_long_is_refused_and_consumes_nothing():
    db, sub = _a_subscription()
    old = settings.invoice_prefix
    when = datetime(2036, 5, 1)  # FY 3637
    try:
        settings.invoice_prefix = "WANDOR-LONGPREFIX"
        try:
            invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                   razorpay_payment_id="pay_long", issued_at=when)
        except ValueError as e:
            assert "INVOICE_PREFIX" in str(e)
        else:
            raise AssertionError("an over-long invoice number must be refused")
        db.rollback()
    finally:
        settings.invoice_prefix = old
    ok = invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                razorpay_payment_id="pay_short", issued_at=when)
    db.commit()
    assert ok.invoice_number == "WND/3637/000001"  # the refused attempt did not use up number 1
    db.close()


def test_database_itself_refuses_a_self_contradicting_or_duplicate_invoice():
    db, sub = _a_subscription()

    def raw(**over):
        row = dict(invoice_number=f"RAW/{time.time_ns()}", subscription_id=sub.id, plan="basic",
                   base_paise=1000, gst_rate_bps=1800, gst_paise=180, total_paise=1180,
                   razorpay_payment_id=None, issued_at=datetime(2037, 1, 1))
        row.update(over)
        return Invoice(**row)

    for label, over in [("total != base + gst", {"total_paise": 1181}),
                        ("negative base", {"base_paise": -1000, "total_paise": -820}),
                        ("duplicate invoice number", {"invoice_number": "DUP/1"}),
                        ("no subscription", {"subscription_id": None})]:
        if label == "duplicate invoice number":
            db.add(raw(invoice_number="DUP/1"))
            db.commit()
        db.add(raw(**over))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError(f"database accepted: {label}")
    db.add(raw(razorpay_payment_id="pay_dupe_x")); db.commit()
    db.add(raw(razorpay_payment_id="pay_dupe_x"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    else:
        raise AssertionError("database accepted the same Razorpay payment twice")
    db.close()


def test_concurrent_issuers_get_gap_free_unique_numbers_postgres_only():
    """Needs real row locks, so it only runs against PostgreSQL (TEST_DATABASE_URL=...); on SQLite
    (one writer at a time anyway) it is skipped. Threads start together, on a brand-new financial
    year so even the creation of the year's counter row is raced."""
    if engine.dialect.name != "postgresql":
        return
    import threading
    from concurrent.futures import ThreadPoolExecutor
    db0, sub0 = _a_subscription()
    sub_id = sub0.id
    db0.close()

    def issue(pay_id, when):
        db = SessionLocal()
        try:
            sub = db.get(Subscription, sub_id)
            barrier.wait(timeout=30)
            inv = invoices.issue_invoice(db, sub, plan="basic", cycle="monthly", total_paise=58882,
                                         razorpay_payment_id=pay_id, issued_at=when)
            db.commit()
            return inv.invoice_number
        finally:
            db.close()

    # 8 different payments, same new financial year (FY 4142)
    barrier = threading.Barrier(8)
    when = datetime(2041, 6, 1)
    with ThreadPoolExecutor(8) as ex:
        nums = list(ex.map(lambda i: issue(f"pay_conc_{i}", when), range(8)))
    assert sorted(nums) == [f"WND/4142/{n:06d}" for n in range(1, 9)], sorted(nums)  # 1..8, no gaps, no dupes

    # 6 threads, the SAME payment (FY 4243): exactly one invoice, everyone gets it, one number used
    barrier = threading.Barrier(6)
    when = datetime(2042, 6, 1)
    with ThreadPoolExecutor(6) as ex:
        nums = list(ex.map(lambda i: issue("pay_conc_same", when), range(6)))
    assert len(set(nums)) == 1 and nums[0] == "WND/4243/000001", nums
    db = SessionLocal()
    assert db.query(Invoice).filter(Invoice.razorpay_payment_id == "pay_conc_same").count() == 1
    assert db.query(InvoiceCounter).filter(InvoiceCounter.fy == "4243").one().last_seq == 1
    db.close()


def test_price_breakdown_matches_the_catalog_and_flags_the_upi_autopay_limit():
    b = invoices.price_breakdown("basic", "monthly")
    assert b == {"base_paise": 49900, "gst_paise": 8982, "total_paise": 58882}
    # Handoff note: UPI Autopay debits above Rs 15,000 need a PIN each time. With GST on top the
    # placeholder Pro yearly price crosses it - this documents the fact so a re-pricing is deliberate.
    assert invoices.price_breakdown("pro", "yearly")["total_paise"] == 1768820 > 1500000
    assert invoices.price_breakdown("basic", "yearly")["total_paise"] < 1500000



# ---------------- Phase 4.2: invoices from the subscription.charged webhook + list API ----------------
def charged(sub_entity, payment, event_id):
    """A real-shaped subscription.charged delivery: the subscription entity AND the payment entity."""
    pl = {"subscription": {"entity": sub_entity}}
    if payment is not None:
        pl["payment"] = {"entity": payment}
    body = json.dumps({"event": "subscription.charged", "payload": pl}).encode()
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    return client.post("/payments/webhook", content=body,
                       headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
                                "Content-Type": "application/json"})


def _pay(pid, amount, **over):
    p = {"id": pid, "amount": amount, "currency": "INR", "status": "captured", "created_at": int(time.time())}
    p.update(over)
    return p


def _subscribed_teacher(plan="basic", cycle="monthly"):
    """A teacher who has bought a plan (Razorpay says active) but whose browser never called
    /billing/verify - the webhook is the first thing to tell us, like a real first charge."""
    tid, h = mk_teacher(trial=False)
    r = client.post("/billing/subscribe", headers=h, json={"plan": plan, "cycle": cycle})
    assert r.status_code == 200, r.text
    sid = r.json()["subscription_id"]
    FAKE.activate(sid, 30)
    return tid, h, sid


def _invoices(h, **params):
    r = client.get("/billing/invoices", headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def text(self):
        return " | ".join(r.getMessage() for r in self.records)


@contextlib.contextmanager
def _watch_logs():
    h = _Logs()
    root = logging.getLogger()
    root.addHandler(h)
    try:
        yield h
    finally:
        root.removeHandler(h)


def _seed_invoice(owner, pay_id, issued_at, total=58882, plan="basic", cycle="monthly"):
    db = SessionLocal()
    sub = subs.get_or_create_subscription(db, owner)
    inv = invoices.issue_invoice(db, sub, plan=plan, cycle=cycle, total_paise=total,
                                 razorpay_payment_id=pay_id, issued_at=issued_at)
    db.commit()
    out = (inv.id, inv.invoice_number)
    db.close()
    return out


def test_charge_webhook_issues_an_invoice_from_the_amount_actually_charged():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    start, end = 1_800_000_000, 1_802_592_000
    ent = {**FAKE.subscriptions[sid], "current_start": start, "current_end": end}
    created = int(time.time()) - 3600  # charged an hour ago: the invoice is dated by the PAYMENT, not by when we heard
    r = charged(ent, _pay("pay_inv_1", 58882, created_at=created), "evt_inv_1")
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text

    got = _invoices(h)
    assert len(got) == 1, got
    inv = got[0]
    assert (inv["base_paise"], inv["gst_paise"], inv["total_paise"]) == (49900, 8982, 58882)
    assert inv["gst_rate_percent"] == 18 and inv["currency"] == "INR" and inv["kind"] == "subscription"
    assert (inv["plan"], inv["plan_label"], inv["billing_cycle"]) == ("basic", "Basic", "monthly")
    assert inv["invoice_number"].startswith("WND/") and len(inv["invoice_number"]) <= 16
    assert datetime.fromisoformat(inv["issued_at"]) == datetime.utcfromtimestamp(created)
    assert datetime.fromisoformat(inv["period_start"]) == datetime.utcfromtimestamp(start)
    assert datetime.fromisoformat(inv["period_end"]) == datetime.utcfromtimestamp(end)
    assert client.get(f"/billing/invoices/{inv['id']}", headers=h).json() == inv  # detail == list row

    # redelivery of the same event, and the same payment under a NEW event id: still one invoice
    assert charged(ent, _pay("pay_inv_1", 58882, created_at=created), "evt_inv_1").json()["status"] == "duplicate"
    assert charged(ent, _pay("pay_inv_1", 58882, created_at=created), "evt_inv_1b").json()["status"] == "ok"
    assert len(_invoices(h)) == 1
    # the next month's charge is a second invoice with its own number, newest first
    later = created + 30 * 86400
    charged(ent, _pay("pay_inv_2", 58882, created_at=later), "evt_inv_2")
    got = _invoices(h)
    assert [g["total_paise"] for g in got] == [58882, 58882] and len(got) == 2
    assert datetime.fromisoformat(got[0]["issued_at"]) == datetime.utcfromtimestamp(later)
    assert got[0]["invoice_number"] != got[1]["invoice_number"]
    assert client.get("/billing/me", headers=h).json()["status"] == "active"  # the webhook still did its normal job


def test_invoice_describes_the_plan_billed_at_the_charge_not_a_later_state():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    # the renewal that took effect was on the Pro plan, but by the time we ask Razorpay it reports Basic
    snapshot = {**FAKE.subscriptions[sid], "plan_id": "plan_pro_m"}
    assert FAKE.subscriptions[sid]["plan_id"] == "plan_basic_m"
    charged(snapshot, _pay("pay_inv_snap", 176882), "evt_inv_snap")
    inv = _invoices(h)[0]
    assert (inv["plan"], inv["billing_cycle"]) == ("pro", "monthly")
    assert (inv["base_paise"], inv["gst_paise"], inv["total_paise"]) == (149900, 26982, 176882)
    assert client.get("/billing/me", headers=h).json()["plan"] == "basic"  # subscription STATE follows the fetch, as before


def test_charge_events_with_nothing_to_invoice_are_acknowledged_and_create_nothing():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    ent = dict(FAKE.subscriptions[sid])
    cases = [
        ("no payment entity at all", None, "CHARGED_EVENT_WITHOUT_PAYMENT"),
        ("payment without an id", {"amount": 58882, "status": "captured"}, "CHARGED_EVENT_WITHOUT_PAYMENT"),
        ("payment not captured", _pay("pay_x1", 58882, status="failed"), "CHARGE_NOT_CAPTURED"),
        ("zero amount", _pay("pay_x2", 0), "CHARGE_BAD_AMOUNT"),
        ("amount as text", _pay("pay_x3", "58882"), "CHARGE_BAD_AMOUNT"),
        ("amount is a bool", _pay("pay_x4", True), "CHARGE_BAD_AMOUNT"),
        ("negative amount", _pay("pay_x5", -100), "CHARGE_BAD_AMOUNT"),
        ("not rupees", _pay("pay_x6", 58882, currency="USD"), "CHARGE_NOT_INR"),
    ]
    for i, (label, pay, expect_log) in enumerate(cases):
        with _watch_logs() as logs:
            r = charged(ent, pay, f"evt_inv_none_{i}")
        assert r.status_code == 200 and r.json()["status"] == "ok", (label, r.text)
        assert expect_log in logs.text(), (label, logs.text())
        assert _invoices(h) == [], label
    # a subscription that isn't ours (no/foreign notes, unknown id): acknowledged, logged, nothing created
    with _watch_logs() as logs:
        r = charged({"id": "sub_stranger", "plan_id": "plan_basic_m", "status": "active", "notes": {}},
                    _pay("pay_x7", 58882), "evt_inv_none_x")
    assert r.status_code == 200 and _invoices(h) == []


def test_a_failing_invoice_never_fails_the_webhook_and_a_redelivery_recovers_it():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    ent = dict(FAKE.subscriptions[sid])
    real = invoices.issue_for_charge

    def boom(*a, **k):
        raise RuntimeError("invoice bug")

    invoices.issue_for_charge = boom
    try:
        with _watch_logs() as logs:
            r = charged(ent, _pay("pay_inv_boom", 58882), "evt_inv_boom")
    finally:
        invoices.issue_for_charge = real
    # Razorpay gets a 200 (so the one shared webhook is never disabled), the subscription still activated,
    # and the failure is logged with the payment id so it can be fixed by hand
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    assert "INVOICE_NOT_ISSUED" in logs.text() and "pay_inv_boom" in logs.text()
    assert client.get("/billing/me", headers=h).json()["status"] == "active"
    assert _invoices(h) == []
    # the same charge delivered again (a retry, or after the bug is fixed) produces the invoice, exactly once
    assert charged(ent, _pay("pay_inv_boom", 58882), "evt_inv_boom_retry").json()["status"] == "ok"
    assert len(_invoices(h)) == 1


def test_a_late_charge_on_a_replaced_subscription_is_still_invoiced_to_its_owner():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    charged(dict(FAKE.subscriptions[sid]), _pay("pay_inv_first", 58882), "evt_inv_late0")
    db = SessionLocal()
    # a charge on an OLD Razorpay subscription id the row no longer carries; only the notes say whose it is
    old = {"id": "sub_replaced_long_ago", "plan_id": "plan_basic_m", "notes": {"teacher_id": tid}}
    inv = invoices.issue_for_charge(db, old, _pay("pay_inv_late", 58882))
    db.commit()
    assert inv is not None
    assert inv.subscription_id == subs.get_subscription(db, subs.Owner(teacher_id=tid)).id
    # ...but with no way to tell whose it is (no notes, or two owners at once) it is NOT guessed at
    with _watch_logs() as logs:
        assert invoices.issue_for_charge(db, {"id": "sub_nobody", "plan_id": "plan_basic_m"}, _pay("pay_inv_nb", 58882)) is None
        assert invoices.issue_for_charge(db, {"id": "sub_two", "notes": {"teacher_id": tid, "institute_id": "i"}},
                                         _pay("pay_inv_two", 58882)) is None
    assert logs.text().count("INVOICE_NOT_ISSUED") == 2
    db.close()
    assert len(_invoices(h)) == 2


def test_charge_invoice_is_dated_and_numbered_by_the_payment_time_in_india():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    ent = dict(FAKE.subscriptions[sid])
    charged(ent, _pay("pay_fy_0", 58882), "evt_fy_0")  # the first charge creates the subscription row
    db = SessionLocal()
    ts = lambda *a: calendar.timegm(datetime(*a).timetuple())
    # 18:29:59 UTC on 31 March is still the old financial year in India; one second later it is the new one
    a = invoices.issue_for_charge(db, ent, _pay("pay_fy_a", 58882, created_at=ts(2038, 3, 31, 18, 29, 59)))
    b = invoices.issue_for_charge(db, ent, _pay("pay_fy_b", 58882, created_at=ts(2038, 3, 31, 18, 30, 0)))
    db.commit()
    assert a.invoice_number.startswith("WND/3738/") and b.invoice_number.startswith("WND/3839/"), (a.invoice_number, b.invoice_number)
    assert b.invoice_number == "WND/3839/000001"
    db.close()


def test_a_razorpay_plan_priced_without_gst_is_flagged_but_still_invoiced_truthfully():
    tid, h, sid = _subscribed_teacher("basic", "monthly")
    ent = dict(FAKE.subscriptions[sid])
    with _watch_logs() as logs:
        charged(ent, _pay("pay_inv_nogst", 49900), "evt_inv_nogst")  # charged Rs 499: the Plan was created at the base price
    assert "INVOICE_AMOUNT_MISMATCH" in logs.text() and "pay_inv_nogst" in logs.text()
    inv = _invoices(h)[0]
    assert inv["total_paise"] == 49900  # the invoice matches the money that actually moved...
    assert (inv["base_paise"], inv["gst_paise"]) == invoices.split_inclusive(49900)  # ...with GST backed out of it
    with _watch_logs() as logs:  # a correctly priced charge is silent
        charged(ent, _pay("pay_inv_ok", 58882), "evt_inv_ok")
    assert "INVOICE_AMOUNT_MISMATCH" not in logs.text()


def test_invoice_api_is_scoped_to_the_owner_and_managers_only():
    _, ha, sid_a = _subscribed_teacher("basic", "monthly")
    _, hb, sid_b = _subscribed_teacher("pro", "monthly")
    assert client.get("/billing/me", headers=ha).json()["can_manage"] is True
    # A has 2 invoices, B has 1 - and neither can see or open the other's
    charged(dict(FAKE.subscriptions[sid_a]), _pay("pay_sc_a1", 58882, created_at=1_900_000_000), "evt_sc_a1")
    charged(dict(FAKE.subscriptions[sid_a]), _pay("pay_sc_a2", 58882, created_at=1_900_100_000), "evt_sc_a2")
    charged(dict(FAKE.subscriptions[sid_b]), _pay("pay_sc_b1", 176882), "evt_sc_b1")
    a_rows, b_rows = _invoices(ha), _invoices(hb)
    assert len(a_rows) == 2 and len(b_rows) == 1
    assert {r["id"] for r in a_rows}.isdisjoint({r["id"] for r in b_rows})
    assert client.get(f"/billing/invoices/{a_rows[0]['id']}", headers=ha).status_code == 200
    assert client.get(f"/billing/invoices/{a_rows[0]['id']}", headers=hb).status_code == 404   # looks like it doesn't exist
    # a malformed id is a 404, never a 500 (PostgreSQL raises on a non-UUID if it reaches the query)
    for bad in ("nope", "123", "not-a-uuid-at-all"):
        assert client.get(f"/billing/invoices/{bad}", headers=ha).status_code == 404, bad
    assert client.get("/billing/invoices/00000000-0000-0000-0000-000000000000", headers=ha).status_code == 404

    # nobody signed in / the wrong kind of token
    assert client.get("/billing/invoices").status_code == 401
    _, student_h = mk_student(teacher_id=mk_teacher()[0])
    assert client.get("/billing/invoices", headers=student_h).status_code == 401

    # an owner with no subscription row yet has no invoices (an empty list, not an error)
    _, fresh = mk_teacher(trial=False)
    assert _invoices(fresh) == []

    # institute: the admin sees them; a teacher who merely belongs to it does not
    iid, admin = mk_institute(trial=False)
    owner = subs.Owner(institute_id=iid)
    inv_id, _num = _seed_invoice(owner, "pay_sc_inst", datetime(2040, 1, 5))
    assert [r["id"] for r in _invoices(admin)] == [inv_id]
    _, member = mk_teacher(institute_id=iid)
    for url in ("/billing/invoices", f"/billing/invoices/{inv_id}"):
        r = client.get(url, headers=member)
        assert r.status_code == 403 and "institute's admin" in r.json()["detail"], (url, r.text)


def test_invoice_list_is_newest_first_and_paginates():
    tid, h = mk_teacher(trial=False)
    owner = subs.Owner(teacher_id=tid)
    ids = [_seed_invoice(owner, f"pay_pg_{i}", datetime(2043, 1 + i, 3))[0] for i in (3, 1, 2)]  # inserted out of order
    got = _invoices(h)
    assert [g["id"] for g in got] == [ids[0], ids[2], ids[1]]  # Apr, Mar, Feb (by issue date, not insert order)
    assert [g["id"] for g in _invoices(h, limit=2)] == [ids[0], ids[2]]
    assert [g["id"] for g in _invoices(h, limit=2, offset=2)] == [ids[1]]
    assert _invoices(h, offset=10) == []
    for bad in ({"limit": 0}, {"limit": 201}, {"offset": -1}, {"limit": "x"}):
        assert client.get("/billing/invoices", headers=h, params=bad).status_code == 422, bad


# ======================= Phase 4.3 - upgrade now (prorated) =======================
from types import SimpleNamespace  # noqa: E402


def _upgradable(plan="basic", cycle="monthly", days_left=15):
    """A teacher with a live paid subscription the browser has already confirmed."""
    tid, h, sid = _subscribed_teacher(plan, cycle)
    FAKE.activate(sid, days_left)
    r = client.post("/billing/verify", headers=h, json={
        "razorpay_payment_id": "pay_first", "razorpay_subscription_id": sid,
        "razorpay_signature": sub_sig("pay_first", sid)})
    assert r.status_code == 200, r.text
    return tid, h, sid


def _set_sub(tid, **kw):
    db = SessionLocal()
    row = db.query(Subscription).filter(Subscription.teacher_id == tid).one()
    for k, v in kw.items():
        setattr(row, k, v)
    db.commit()
    db.close()


def _get_sub(tid):
    db = SessionLocal()
    row = db.query(Subscription).filter(Subscription.teacher_id == tid).one()
    out = SimpleNamespace(plan=row.plan, cycle=row.billing_cycle, status=row.status, end=row.current_period_end,
                          cancel=row.cancel_at_period_end, rz=row.razorpay_subscription_id)
    db.close()
    return out


def _start_upgrade(h, plan="pro"):
    return client.post("/billing/upgrade", headers=h, json={"plan": plan})


def _upg_payment(order_id, pay_id, amount=None, status="captured", paid_order=None):
    o = FAKE.orders[order_id]
    FAKE.payments[pay_id] = {"id": pay_id, "order_id": paid_order or order_id,
                             "amount": o["amount"] if amount is None else amount, "status": status,
                             "currency": "INR", "created_at": int(time.time())}
    return FAKE.payments[pay_id]


def _verify_upgrade(h, order_id, pay_id, sig=None):
    return client.post("/billing/upgrade/verify", headers=h, json={
        "razorpay_order_id": order_id, "razorpay_payment_id": pay_id,
        "razorpay_signature": sig or order_sig(order_id, pay_id)})


def _upgrade_hook(order_id, pay_id, event_id, event="payment.captured", **over):
    return webhook(event, "payment", {**_upg_payment(order_id, pay_id), **over}, event_id)


def _edits(sid):
    return [c for c in FAKE.calls if c[0] == "subscription.edit" and c[1] == sid]


def _cancels(sid):
    return [c for c in FAKE.calls if c[0] == "subscription.cancel" and c[1] == sid]


def _upgrade_rows(tid):
    db = SessionLocal()
    sub = db.query(Subscription).filter(Subscription.teacher_id == tid).one()
    rows = db.query(PlanUpgrade).filter(PlanUpgrade.subscription_id == sub.id).all()
    out = [SimpleNamespace(status=r.status, renewal=r.renewal, note=r.note, pay=r.razorpay_payment_id,
                           total=r.total_paise) for r in rows]
    db.close()
    return out


def test_proration_maths_is_integer_exact_and_rounds_half_up():
    pb = upgrades.prorate_base
    assert pb(49900, 149900, 1, 1) == 100000            # the whole period left: the whole difference
    assert pb(49900, 149900, 0, 100) == 0               # nothing left: nothing to pay
    assert pb(49900, 149900, 1339200, 2678400) == 50000  # exactly half
    assert (pb(100, 101, 1, 2), pb(100, 101, 1, 3), pb(100, 101, 2, 3)) == (1, 0, 1)  # half-up, once
    assert pb(100, 1100, 5000, 100) == 1000             # more "left" than the period: clamped
    for bad in ((200, 100, 1, 2), (100, 200, 1, 0)):
        try:
            pb(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {bad}")
    # period start is one cycle before the stored end, clamped to the shorter month
    assert upgrades._add_months(datetime(2043, 3, 31), -1) == datetime(2043, 2, 28)
    assert upgrades._add_months(datetime(2044, 3, 31), -1) == datetime(2044, 2, 29)
    assert upgrades._add_months(datetime(2043, 1, 15), -1) == datetime(2042, 12, 15)
    assert upgrades._add_months(datetime(2043, 6, 30), -12) == datetime(2042, 6, 30)
    b = upgrades.period_bounds(SimpleNamespace(current_period_end=datetime(2044, 1, 1), billing_cycle="yearly"))
    assert b == (datetime(2043, 1, 1), datetime(2044, 1, 1))


def test_upgrade_quote_exact_values_monthly_and_yearly():
    tid, h, sid = _upgradable("basic", "monthly")
    _set_sub(tid, current_period_end=datetime(2043, 2, 1))
    db = SessionLocal()
    sub = db.query(Subscription).filter(Subscription.teacher_id == tid).one()
    q = upgrades.quote(sub, "pro", now=datetime(2043, 1, 16, 12))   # Jan has 31 days: 15.5 of 31 left = half
    assert (q["base_paise"], q["gst_paise"], q["total_paise"]) == (50000, 9000, 59000)
    assert (q["credit_base_paise"], q["charge_base_paise"]) == (24950, 74950)  # charge - credit == base
    assert q["period_start"] == datetime(2043, 1, 1) and q["period_end"] == datetime(2043, 2, 1)
    db.close()

    # yearly (Pro yearly is deliberately unconfigured in this suite, so switch it on for a moment)
    tid, h, sid = _upgradable("basic", "yearly")
    _set_sub(tid, current_period_end=datetime(2044, 1, 1))
    settings.razorpay_plan_pro_yearly = "plan_pro_y"
    try:
        db = SessionLocal()
        sub = db.query(Subscription).filter(Subscription.teacher_id == tid).one()
        q = upgrades.quote(sub, "pro", now=datetime(2043, 7, 2))   # 183 of 365 days left
        assert (q["base_paise"], q["gst_paise"], q["total_paise"]) == (501370, 90247, 591617)
        db.close()
    finally:
        settings.razorpay_plan_pro_yearly = ""


def test_upgrade_quote_endpoint_rules():
    # no subscription / trial -> nothing to upgrade
    _, h = mk_teacher(trial=False)
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code == 400
    _, h = mk_teacher(trial=True)
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code == 400

    tid, h, sid = _upgradable("basic", "monthly", days_left=15)
    r = client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"})
    assert r.status_code == 200, r.text
    q = r.json()
    assert (q["from_plan"], q["to_plan"], q["cycle"], q["gst_rate_percent"]) == ("basic", "pro", "monthly", 18)
    assert q["base_paise"] + q["gst_paise"] == q["total_paise"] and q["gst_paise"] == (q["base_paise"] * 18 + 50) // 100
    assert 40000 < q["base_paise"] < 55000 and 14 < q["remaining_days"] <= 15      # about half of Rs 1,000
    assert q["charge_base_paise"] - q["credit_base_paise"] == q["base_paise"]
    assert not [c for c in FAKE.calls if c[0] == "order.create"
                and c[1].get("notes", {}).get("teacher_id") == tid]          # a quote creates no order
    assert _upgrade_rows(tid) == []

    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "basic"}).status_code == 400   # same plan
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "free"}).status_code == 400
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "nope"}).status_code == 400

    _set_sub(tid, plan="pro")   # going DOWN is change-plan's job
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "basic"}).status_code == 400
    _set_sub(tid, plan="basic", scheduled_plan="pro", scheduled_cycle="monthly")
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code == 409
    _set_sub(tid, scheduled_plan=None, scheduled_cycle=None, cancel_at_period_end=True)
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code == 409
    _set_sub(tid, cancel_at_period_end=False)
    _set_sub(tid, status="past_due")
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code == 400
    _set_sub(tid, status="active")

    # about to renew: too little left to charge Razorpay's Rs 1 minimum, and a period that has ended
    _set_sub(tid, current_period_end=datetime.utcnow() + timedelta(seconds=30))
    r = client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"})
    assert r.status_code == 409 and "renew" in r.json()["detail"], r.text
    _set_sub(tid, current_period_end=datetime.utcnow() - timedelta(seconds=5))
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code in (400, 409)

    # the target plan has no Razorpay plan for this cycle -> can't be bought yet
    tid, h, sid = _upgradable("basic", "yearly", days_left=200)
    assert client.post("/billing/upgrade/quote", headers=h, json={"plan": "pro"}).status_code == 503


def test_upgrade_only_billing_managers_can_use_it():
    iid, ih = mk_institute(trial=False)
    mid, mh = mk_teacher(institute_id=iid)
    for path, body in (("/billing/upgrade/quote", {"plan": "pro"}), ("/billing/upgrade", {"plan": "pro"}),
                       ("/billing/upgrade/verify", {"razorpay_order_id": "o", "razorpay_payment_id": "p",
                                                    "razorpay_signature": "s"})):
        assert client.post(path, headers=mh, json=body).status_code == 403, path
        assert client.post(path, json=body).status_code in (401, 403), path


def test_upgrade_browser_path_end_to_end():
    tid, h, sid = _upgradable("basic", "monthly", days_left=15)
    end_before = _get_sub(tid).end
    r = _start_upgrade(h)
    assert r.status_code == 200, r.text
    o = r.json()
    body = FAKE.orders[o["order_id"]]["body"]
    assert body["amount"] == o["total_paise"] and body["currency"] == "INR"
    assert body["notes"]["kind"] == "plan_upgrade" and body["notes"]["teacher_id"] == tid
    assert body["receipt"].startswith("upg_") and o["key_id"] == "rzp_test_key"   # never a bare UUID like a fee id
    # nothing changes until the payment is confirmed
    me = client.get("/billing/me", headers=h).json()
    assert (me["plan"], me["upgrade_renewal"]) == ("basic", None) and _invoices(h) == []
    assert _edits(sid) == []

    _upg_payment(o["order_id"], "pay_up_1")
    r = _verify_upgrade(h, o["order_id"], "pay_up_1")
    assert r.status_code == 200, r.text
    me = r.json()
    assert (me["plan"], me["status"], me["billing_cycle"], me["upgrade_renewal"]) == ("pro", "active", "monthly", "scheduled")
    assert me["students_limit"] is None                      # Pro's limits apply straight away
    assert _get_sub(tid).end == end_before                   # the period (and the next renewal date) does not move

    inv = _invoices(h)
    assert len(inv) == 1, inv
    inv = inv[0]
    assert (inv["kind"], inv["plan"], inv["billing_cycle"]) == ("proration", "pro", "monthly")
    assert (inv["base_paise"], inv["gst_paise"], inv["total_paise"]) == (o["base_paise"], o["gst_paise"], o["total_paise"])
    assert inv["base_paise"] + inv["gst_paise"] == inv["total_paise"] == FAKE.orders[o["order_id"]]["amount"]
    assert "Basic" in inv["description"] and "Pro" in inv["description"]
    assert datetime.fromisoformat(inv["period_end"]) == end_before

    # the NEXT renewal was moved to the new plan's price, once, for the end of the cycle
    ed = _edits(sid)
    assert len(ed) == 1 and ed[0][2]["plan_id"] == "plan_pro_m" and ed[0][2]["schedule_change_at"] == "cycle_end"
    assert _cancels(sid) == []

    # verifying again (double tap / retry) changes nothing: one invoice, one edit, still 200
    assert _verify_upgrade(h, o["order_id"], "pay_up_1").status_code == 200
    assert len(_invoices(h)) == 1 and len(_edits(sid)) == 1


def test_upgrade_webhook_path_and_the_browser_and_webhook_race():
    # webhook first (the customer closed the tab right after paying), then the browser's verify
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    with _watch_logs() as logs:
        r = _upgrade_hook(o["order_id"], "pay_up_w1", "evt_up_w1")
    assert r.status_code == 200 and r.json()["status"] == "ok", r.text
    assert "ORPHAN_FEE_PAYMENT" not in logs.text()            # not mistaken for a student fee
    me = client.get("/billing/me", headers=h).json()
    assert (me["plan"], me["upgrade_renewal"]) == ("pro", "scheduled")
    assert [i["kind"] for i in _invoices(h)] == ["proration"] and len(_edits(sid)) == 1
    assert _verify_upgrade(h, o["order_id"], "pay_up_w1").status_code == 200
    assert webhook("payment.captured", "payment", FAKE.payments["pay_up_w1"], "evt_up_w1").json()["status"] == "duplicate"
    assert _upgrade_hook(o["order_id"], "pay_up_w1", "evt_up_w1b").status_code == 200      # new event id, same payment
    assert _upgrade_hook(o["order_id"], "pay_up_w1", "evt_up_w1c", event="order.paid").status_code == 200
    assert len(_invoices(h)) == 1 and len(_edits(sid)) == 1 and [u.status for u in _upgrade_rows(tid)] == ["applied"]

    # browser first, then the webhook
    tid2, h2, sid2 = _upgradable("basic", "monthly")
    o2 = _start_upgrade(h2).json()
    _upg_payment(o2["order_id"], "pay_up_w2")
    assert _verify_upgrade(h2, o2["order_id"], "pay_up_w2").status_code == 200
    assert _upgrade_hook(o2["order_id"], "pay_up_w2", "evt_up_w2").status_code == 200
    assert len(_invoices(h2)) == 1 and len(_edits(sid2)) == 1

    # an authorised-but-not-captured payment moves nothing
    tid3, h3, sid3 = _upgradable("basic", "monthly")
    o3 = _start_upgrade(h3).json()
    _upg_payment(o3["order_id"], "pay_up_w3", status="authorized")
    assert webhook("payment.authorized", "payment", FAKE.payments["pay_up_w3"], "evt_up_w3").status_code == 200
    assert webhook("payment.captured", "payment", FAKE.payments["pay_up_w3"], "evt_up_w3b").status_code == 200
    assert client.get("/billing/me", headers=h3).json()["plan"] == "basic" and _invoices(h3) == []
    r = _verify_upgrade(h3, o3["order_id"], "pay_up_w3")
    assert r.status_code == 409 and client.get("/billing/me", headers=h3).json()["plan"] == "basic"


def test_upgraded_plan_survives_razorpay_still_reporting_the_old_plan_until_the_period_ends():
    tid, h, sid = _upgradable("basic", "monthly", days_left=15)
    o = _start_upgrade(h).json()
    _upg_payment(o["order_id"], "pay_up_h1")
    assert _verify_upgrade(h, o["order_id"], "pay_up_h1").json()["plan"] == "pro"
    assert FAKE.subscriptions[sid]["plan_id"] == "plan_basic_m"      # Razorpay still carries the OLD plan

    # any sync of that subscription (webhook, or the browser's /billing/verify) must not undo the upgrade
    assert webhook("subscription.activated", "subscription", FAKE.subscriptions[sid], "evt_hold_1").status_code == 200
    assert client.get("/billing/me", headers=h).json()["plan"] == "pro"
    r = client.post("/billing/verify", headers=h, json={"razorpay_payment_id": "pay_again",
                    "razorpay_subscription_id": sid, "razorpay_signature": sub_sig("pay_again", sid)})
    assert r.status_code == 200 and r.json()["plan"] == "pro"

    # the period rolls over: the renewal was moved to Pro (edit worked) -> Pro, hold released
    FAKE.subscriptions[sid]["plan_id"] = "plan_pro_m"
    FAKE.subscriptions[sid]["current_end"] += 31 * 86400
    assert webhook("subscription.charged", "subscription", FAKE.subscriptions[sid], "evt_hold_2").status_code == 200
    me = client.get("/billing/me", headers=h).json()
    assert me["plan"] == "pro" and me["upgrade_renewal"] is None       # a new period: the old upgrade no longer applies

    # ...and if Razorpay renews at the old plan (the renewal was never switched), the hold must NOT keep Pro forever
    tid, h, sid = _upgradable("basic", "monthly", days_left=15)
    o = _start_upgrade(h).json()
    _upg_payment(o["order_id"], "pay_up_h2")
    assert _verify_upgrade(h, o["order_id"], "pay_up_h2").json()["plan"] == "pro"
    FAKE.subscriptions[sid]["current_end"] += 31 * 86400
    assert webhook("subscription.charged", "subscription", FAKE.subscriptions[sid], "evt_hold_3").status_code == 200
    assert client.get("/billing/me", headers=h).json()["plan"] == "basic"


def test_upgrade_on_a_upi_subscription_falls_back_to_cancel_at_period_end():
    tid, h, sid = _upgradable("basic", "monthly", days_left=15)
    o = _start_upgrade(h).json()
    _upg_payment(o["order_id"], "pay_up_u1")
    FAKE.edit_error = True
    try:
        r = _verify_upgrade(h, o["order_id"], "pay_up_u1")
    finally:
        FAKE.edit_error = False
    assert r.status_code == 200, r.text
    me = r.json()
    # paid and upgraded despite Razorpay refusing the edit - the upgrade never depends on it
    assert (me["plan"], me["upgrade_renewal"], me["cancel_at_period_end"]) == ("pro", "reauthorise", True)
    assert len(_invoices(h)) == 1
    c = _cancels(sid)
    assert len(c) == 1 and c[0][2] == {"cancel_at_cycle_end": 1}      # the OLD subscription ends at period end, never now
    # continuing is the ordinary re-subscribe, which starts the new subscription at the period end (no double charge)
    r = client.post("/billing/subscribe", headers=h, json={"plan": "pro", "cycle": "monthly"})
    assert r.status_code == 200, r.text
    new_sid = r.json()["subscription_id"]
    start_at = [c[1] for c in FAKE.calls if c[0] == "subscription.create"][-1]["start_at"]
    assert start_at == calendar.timegm(_get_sub(tid).end.utctimetuple()) and new_sid != sid

    # Razorpay refuses BOTH: still upgraded and invoiced, and the problem is loud in the logs
    tid, h, sid = _upgradable("basic", "monthly", days_left=15)
    o = _start_upgrade(h).json()
    _upg_payment(o["order_id"], "pay_up_u2")
    FAKE.edit_error = FAKE.cancel_error = True
    try:
        with _watch_logs() as logs:
            r = _verify_upgrade(h, o["order_id"], "pay_up_u2")
    finally:
        FAKE.edit_error = FAKE.cancel_error = False
    assert r.status_code == 200 and r.json()["plan"] == "pro" and r.json()["upgrade_renewal"] == "failed"
    assert "UPGRADE_RENEWAL_NOT_SWITCHED" in logs.text() and len(_invoices(h)) == 1
    assert _get_sub(tid).cancel is False


def test_upgrade_verify_rejects_forged_foreign_and_unconfirmed_payments():
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    oid = o["order_id"]
    _upg_payment(oid, "pay_up_f1")

    assert _verify_upgrade(h, oid, "pay_up_f1", sig="0" * 64).status_code == 400           # bad signature
    assert _verify_upgrade(h, "order_nope", "pay_x").status_code == 404                     # unknown order
    # somebody else's order is indistinguishable from one that doesn't exist
    tid2, h2, sid2 = _upgradable("basic", "monthly")
    assert _verify_upgrade(h2, oid, "pay_up_f1").status_code == 404
    # a payment that belongs to a different order, even with a valid signature for that pair
    other = _start_upgrade(h2).json()["order_id"]
    _upg_payment(other, "pay_up_f2")
    FAKE.payments["pay_up_f2"]["order_id"] = oid
    assert _verify_upgrade(h2, other, "pay_up_f2").status_code == 400
    # Razorpay unreachable -> 502, nothing applied
    FAKE.fail_payment_fetch = True
    try:
        assert _verify_upgrade(h, oid, "pay_up_f1").status_code == 502
    finally:
        FAKE.fail_payment_fetch = False
    for t in (tid, tid2):
        assert _get_sub(t).plan == "basic"
    assert _invoices(h) == [] and _invoices(h2) == []
    # and the genuine payment still works afterwards
    assert _verify_upgrade(h, oid, "pay_up_f1").status_code == 200


def test_money_taken_but_upgrade_not_applicable_is_flagged_for_refund_not_swallowed():
    # 1. the payment is for a different amount than the order (should be impossible - still must not upgrade)
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    _upg_payment(o["order_id"], "pay_up_r1", amount=o["total_paise"] - 1)
    with _watch_logs() as logs:
        assert webhook("payment.captured", "payment", FAKE.payments["pay_up_r1"], "evt_up_r1").status_code == 200
    assert "UPGRADE_NEEDS_REFUND" in logs.text() and "pay_up_r1" in logs.text()
    assert _get_sub(tid).plan == "basic" and _invoices(h) == []
    assert [(u.status, u.pay) for u in _upgrade_rows(tid)] == [("refund_needed", "pay_up_r1")]
    r = _verify_upgrade(h, o["order_id"], "pay_up_r1")
    assert r.status_code == 409 and "refund" in r.json()["detail"]

    # 2. the period renewed while the customer was in Checkout: the payment was for a period that is over
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    _set_sub(tid, current_period_end=_get_sub(tid).end + timedelta(days=31))
    _upg_payment(o["order_id"], "pay_up_r2")
    with _watch_logs() as logs:
        assert _upgrade_hook(o["order_id"], "pay_up_r2", "evt_up_r2").status_code == 200
    assert "UPGRADE_NEEDS_REFUND" in logs.text() and _get_sub(tid).plan == "basic" and _invoices(h) == []
    assert _edits(sid) == []

    # 3. two orders for the same upgrade, both paid: the first upgrades, the second is flagged
    tid, h, sid = _upgradable("basic", "monthly")
    a = _start_upgrade(h).json()["order_id"]
    b = _start_upgrade(h).json()["order_id"]
    _upg_payment(a, "pay_up_r3a")
    _upg_payment(b, "pay_up_r3b")
    assert _verify_upgrade(h, a, "pay_up_r3a").status_code == 200
    with _watch_logs() as logs:
        assert _upgrade_hook(b, "pay_up_r3b", "evt_up_r3b").status_code == 200
    assert "UPGRADE_NEEDS_REFUND" in logs.text() and len(_invoices(h)) == 1
    assert sorted(u.status for u in _upgrade_rows(tid)) == ["applied", "refund_needed"]
    assert len(_edits(sid)) == 1

    # 4. the customer cancelled while in Checkout: they still paid for Pro for this period and get it
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    assert client.post("/billing/cancel", headers=h).status_code == 200
    _upg_payment(o["order_id"], "pay_up_r4")
    assert _verify_upgrade(h, o["order_id"], "pay_up_r4").json()["plan"] == "pro"
    assert _upgrade_rows(tid)[0].renewal is None            # already ending: no renewal to re-price


def test_a_failing_invoice_never_undoes_a_paid_upgrade():
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    _upg_payment(o["order_id"], "pay_up_i1")
    real = invoices.issue_invoice

    def boom(*a, **k):
        raise RuntimeError("invoice table on fire")
    invoices.issue_invoice = boom
    try:
        with _watch_logs() as logs:
            r = _upgrade_hook(o["order_id"], "pay_up_i1", "evt_up_i1")
    finally:
        invoices.issue_invoice = real
    assert r.status_code == 200, r.text                       # Razorpay must still get its 200
    assert "INVOICE_NOT_ISSUED" in logs.text() and "pay_up_i1" in logs.text()
    assert _get_sub(tid).plan == "pro" and _invoices(h) == []
    # a redelivery after the cause is fixed cannot re-apply (already applied) and the hand-issue recipe works
    db = SessionLocal()
    sub = db.query(Subscription).filter(Subscription.teacher_id == tid).one()
    invoices.issue_invoice(db, sub, plan="pro", cycle="monthly", total_paise=o["total_paise"],
                           razorpay_payment_id="pay_up_i1", kind="proration")
    db.commit()
    db.close()
    assert [i["kind"] for i in _invoices(h)] == ["proration"]


def test_upgrade_create_is_rate_limited_and_a_blocked_call_makes_no_order():
    tid, h, sid = _upgradable("basic", "monthly")
    with _limits(rate_limit_billing_per_min=2):
        before = len([c for c in FAKE.calls if c[0] == "order.create"])
        assert _start_upgrade(h).status_code == 200
        assert _start_upgrade(h).status_code == 200
        assert _start_upgrade(h).status_code == 429
        assert len([c for c in FAKE.calls if c[0] == "order.create"]) == before + 2
    with _limits(rate_limit_verify_per_min=1):
        assert _verify_upgrade(h, "order_nope", "pay_x").status_code == 404
        assert _verify_upgrade(h, "order_nope", "pay_x").status_code == 429


def test_razorpay_down_when_starting_an_upgrade_creates_nothing():
    tid, h, sid = _upgradable("basic", "monthly")
    real = FAKE.order.create

    def down(body):
        raise RuntimeError("razorpay down")
    FAKE.order.create = down
    try:
        assert _start_upgrade(h).status_code == 502
    finally:
        FAKE.order.create = real
    assert _upgrade_rows(tid) == [] and _get_sub(tid).plan == "basic"


def test_a_missed_renewal_switch_is_retried_by_a_webhook_redelivery():
    tid, h, sid = _upgradable("basic", "monthly")
    o = _start_upgrade(h).json()
    FAKE.edit_error = FAKE.cancel_error = True   # Razorpay is having a bad minute: upgrade applied, switch failed
    try:
        _upg_payment(o["order_id"], "pay_up_m1")
        assert _verify_upgrade(h, o["order_id"], "pay_up_m1").json()["upgrade_renewal"] == "failed"
    finally:
        FAKE.edit_error = FAKE.cancel_error = False
    # (a crash between commit and switch leaves renewal unset; model that)
    db = SessionLocal()
    db.query(PlanUpgrade).filter(PlanUpgrade.razorpay_order_id == o["order_id"]).update({"renewal": None})
    db.commit()
    db.close()
    assert _upgrade_hook(o["order_id"], "pay_up_m1", "evt_up_m1").status_code == 200   # a redelivery
    assert client.get("/billing/me", headers=h).json()["upgrade_renewal"] == "scheduled"
    assert len(_invoices(h)) == 1


def test_seller_details_for_the_invoice_page_are_manager_only_and_come_from_settings():
    _, h = mk_teacher(trial=False)
    old = (settings.seller_legal_name, settings.seller_gstin, settings.seller_address)
    try:
        settings.seller_legal_name, settings.seller_gstin = "Wandor Pvt Ltd", "29ABCDE1234F1Z5"
        settings.seller_address = "1 Main Road\\nBengaluru 560001"   # "\\n" in .env means a line break
        r = client.get("/billing/seller", headers=h)
        assert r.status_code == 200, r.text
        assert r.json() == {"legal_name": "Wandor Pvt Ltd", "gstin": "29ABCDE1234F1Z5",
                            "address": "1 Main Road\nBengaluru 560001"}
        settings.seller_legal_name = settings.seller_gstin = settings.seller_address = ""
        assert client.get("/billing/seller", headers=h).json() == {"legal_name": "", "gstin": "", "address": ""}
    finally:
        settings.seller_legal_name, settings.seller_gstin, settings.seller_address = old
    assert client.get("/billing/seller").status_code == 401
    _, student_h = mk_student(teacher_id=mk_teacher()[0])
    assert client.get("/billing/seller", headers=student_h).status_code == 401


# ---------------- Shipped with NO Razorpay keys: everything works, online payment is simply off ----------------
class _no_razorpay_keys:
    def __enter__(self):
        self.old = (settings.razorpay_key_id, settings.razorpay_key_secret, settings.razorpay_webhook_secret)
        settings.razorpay_key_id = settings.razorpay_key_secret = settings.razorpay_webhook_secret = ""

    def __exit__(self, *a):
        settings.razorpay_key_id, settings.razorpay_key_secret, settings.razorpay_webhook_secret = self.old


def test_without_razorpay_keys_app_works_and_online_payment_is_off():
    tid, th = _paid_teacher(account="acc_nokeys")  # paid plan AND a payout account - only the keys are missing
    sid, sh = mk_student(teacher_id=tid)
    ph = _parent_h(sid)
    fid = _fee_with(sid, 1000, partial=True)
    calls_before = len(FAKE.calls)
    with _no_razorpay_keys():
        # no dead "Pay now" button for the student or the parent
        assert client.get("/payments/my-fees", headers=sh).json()["online_payment_available"] is False
        assert client.get("/parents/my-fees", headers=ph).json()["online_payment_available"] is False
        # trying anyway gives the friendly "pay your teacher" message, never a 5xx
        for url, h in (("/payments/create-order", sh), ("/parents/create-order", ph)):
            r = client.post(url, headers=h, json={"fee_record_id": fid})
            assert r.status_code == 409 and "pay your teacher" in r.json()["detail"], r.text
        # subscribing / upgrading says so plainly
        for url, body in (("/billing/subscribe", {"plan": "pro", "cycle": "monthly"}),
                          ("/billing/upgrade", {"plan": "pro"})):
            r = client.post(url, headers=th, json=body)
            assert r.status_code == 503 and r.json()["detail"] == "Online payments aren't switched on yet.", (url, r.text)
        # a signature forged with the EMPTY secret must never be accepted anywhere
        forged = hmac.new(b"", b"order_x|pay_x", hashlib.sha256).hexdigest()
        for url, h in (("/payments/verify", sh), ("/parents/verify", ph)):
            r = client.post(url, headers=h, json={"razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x", "razorpay_signature": forged})
            assert r.status_code == 503, (url, r.text)
        r = client.post("/billing/verify", headers=th, json={
            "razorpay_payment_id": "pay_x", "razorpay_subscription_id": "sub_x",
            "razorpay_signature": hmac.new(b"", b"pay_x|sub_x", hashlib.sha256).hexdigest()})
        assert r.status_code == 503
        r = client.post("/billing/upgrade/verify", headers=th, json={
            "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x", "razorpay_signature": forged})
        assert r.status_code == 503
        assert webhook("payment.captured", "payment", {"id": "pay_x", "order_id": "order_x"}, "evt_nokeys").status_code == 503
        # the rest of the app is unaffected: plans, status, fees, manual (cash/UPI) payments, receipts
        assert client.get("/billing/plans").status_code == 200 and client.get("/billing/me", headers=th).status_code == 200
        r = client.post(f"/payments/fees/{fid}/mark-paid", headers=th, json={"amount": 400})
        assert r.status_code == 200 and r.json()["amount_paid"] == 400
        pay = client.get("/payments/my-fees", headers=sh).json()["fees"][0]["payments"][0]
        assert client.get(f"/payments/my-receipts/{pay['id']}", headers=sh).status_code == 200
    assert len(FAKE.calls) == calls_before  # nothing reached Razorpay
    # keys back -> online payment is available again
    assert client.get("/payments/my-fees", headers=sh).json()["online_payment_available"] is True



def run_all():
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"PASS  {name}")
    print(f"\n{len(tests)} passed")


if __name__ == "__main__":
    run_all()
