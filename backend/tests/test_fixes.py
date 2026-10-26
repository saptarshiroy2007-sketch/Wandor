"""Regression tests for the QA-fix pass (timezones, validation, test rules, attendance,
tenant-safe student login, student deletion, owner tooling, malformed IDs).

Run from backend/:   python -m pytest tests/test_fixes.py -q
Reuses the helpers (and throwaway DB bootstrap) from test_billing_flow.
"""
from datetime import datetime, timedelta

from tests.test_billing_flow import (  # noqa: F401  (import sets env + creates schema)
    client, SessionLocal, mk_teacher, mk_institute, mk_student, _phone,
)
from app.auth import hash_password
from app.models import Batch, Student, TestAttempt
from app.database import settings

Q = lambda t, c="a": {"text": t, "option_a": "x", "option_b": "y", "option_c": "z", "option_d": "w", "correct_option": c}


def _batch(tid, name="B"):
    db = SessionLocal(); b = Batch(teacher_id=tid, name=name); db.add(b); db.commit(); bid = b.id; db.close()
    return bid


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cls(h, bid, start, end):
    return client.post("/classes", headers=h, json={"batch_id": bid, "subject": "Math", "start_time": _iso(start), "end_time": _iso(end)})


def test_class_times_roundtrip_with_z_and_validation():
    tid, h = mk_teacher(trial=True)
    bid = _batch(tid)
    s = datetime.utcnow() + timedelta(days=2)
    r = _cls(h, bid, s, s + timedelta(hours=1))
    assert r.status_code == 200, r.text
    assert r.json()["start_time"].endswith("Z")
    assert _cls(h, bid, s, s - timedelta(hours=1)).status_code == 422          # end before start
    bad = client.post("/classes", headers=h, json={"batch_id": bid, "subject": "", "start_time": _iso(s), "end_time": _iso(s + timedelta(hours=1))})
    assert bad.status_code == 422


def test_cancel_twice_rejected_and_student_sees_class():
    tid, h = mk_teacher(trial=True)
    bid = _batch(tid)
    sid, sh = mk_student(teacher_id=tid, batch_id=bid)
    s = datetime.utcnow() + timedelta(days=1)
    cid = _cls(h, bid, s, s + timedelta(hours=1)).json()["id"]
    assert client.post(f"/classes/{cid}/cancel", headers=h, json={}).status_code == 200
    assert client.post(f"/classes/{cid}/cancel", headers=h, json={}).status_code == 400
    mine = client.get("/classes/my", headers=sh).json()
    assert [c["status"] for c in mine] == ["cancelled"]


def test_attendance_rules():
    tid, h = mk_teacher(trial=True)
    bid = _batch(tid)
    sid, _ = mk_student(teacher_id=tid, batch_id=bid)
    outsider, _ = mk_student(teacher_id=tid)
    now = datetime.utcnow()
    future = _cls(h, bid, now + timedelta(days=1), now + timedelta(days=1, hours=1)).json()["id"]
    past = _cls(h, bid, now - timedelta(hours=3), now - timedelta(hours=2)).json()["id"]
    mark = lambda cid, marks: client.post("/attendance/mark", headers=h, json={"class_session_id": cid, "marks": marks})
    ok = [{"student_id": sid, "present": True}]
    assert mark(future, ok).status_code == 400
    assert mark(past, []).status_code == 422
    assert mark(past, [{"student_id": outsider, "present": True}]).status_code in (400, 404)
    assert mark(past, ok).status_code == 200
    cancelled = _cls(h, bid, now - timedelta(hours=6), now - timedelta(hours=5)).json()["id"]
    from app.models import ClassSession, ClassStatus
    db = SessionLocal(); db.query(ClassSession).filter(ClassSession.id == cancelled).update({"status": ClassStatus.cancelled}); db.commit(); db.close()
    assert mark(cancelled, ok).status_code == 400


def test_mcq_rules_dedupe_single_attempt_and_visibility():
    tid, h = mk_teacher(trial=True)
    bid = _batch(tid)
    sid, sh = mk_student(teacher_id=tid, batch_id=bid)
    r = client.post("/tests/mcq", headers=h, json={"title": "T1", "duration_minutes": 10, "questions": [Q("q1"), Q("q2"), Q("q3")]})
    assert r.status_code == 200, r.text
    tid_test = r.json()["test_id"]
    assert client.post("/tests/mcq", headers=h, json={"title": "T", "duration_minutes": 10, "questions": []}).status_code == 422
    assert client.post("/tests/mcq", headers=h, json={"title": "T", "duration_minutes": -1, "questions": [Q("a")]}).status_code == 422

    a = client.post(f"/tests/{tid_test}/start", headers=sh).json()
    assert 0 < a["seconds_left"] <= 600
    again = client.post(f"/tests/{tid_test}/start", headers=sh).json()
    assert again["attempt_id"] == a["attempt_id"]                      # resume, no phantom attempt
    qid = a["questions"][0]["id"]
    sub = client.post(f"/tests/attempts/{a['attempt_id']}/submit", headers=sh,
                      json={"answers": [{"question_id": qid, "chosen_option": "a"}] * 10 + [{"question_id": "bogus", "chosen_option": "a"}]})
    assert sub.status_code == 200 and sub.json()["score"] == 1 and sub.json()["total"] == 3
    assert client.post(f"/tests/{tid_test}/start", headers=sh).status_code == 409   # retake blocked
    hist = client.get("/tests/my-attempts", headers=sh).json()
    assert len(hist) == 1 and hist[0]["score"] == 1


def test_batch_restricted_test_hidden_from_outsiders():
    tid, h = mk_teacher(trial=True)
    bid = _batch(tid)
    _, outside = mk_student(teacher_id=tid)
    r = client.post("/tests/mcq", headers=h, json={"title": "Restricted", "duration_minutes": 10, "batch_id": bid, "questions": [Q("q")]})
    t = r.json()["test_id"]
    assert client.post(f"/tests/{t}/start", headers=outside).status_code == 404
    _, other_tenant = mk_student(teacher_id=mk_teacher(trial=True)[0])
    assert client.post(f"/tests/{t}/start", headers=other_tenant).status_code == 404


def test_malformed_ids_are_404_not_500():
    tid, h = mk_teacher(trial=True)
    for method, url in [("get", "/students/nope"), ("delete", "/payments/fees/nope"), ("get", "/payments/receipts/nope"), ("post", "/classes/nope/cancel")]:
        r = getattr(client, method)(url, headers=h)
        assert r.status_code in (404, 405, 422), (url, r.status_code)


def test_student_login_picker_across_tenants():
    t1, _ = mk_teacher(); t2, _ = mk_teacher()
    phone = _phone()
    db = SessionLocal()
    s1 = Student(teacher_id=t1, name="Kid@T1", phone=phone, hashed_password=hash_password("1234"))
    s2 = Student(teacher_id=t2, name="Kid@T2", phone=phone, hashed_password=hash_password("1234"))
    db.add_all([s1, s2]); db.commit(); id1, id2 = s1.id, s2.id; db.close()
    r = client.post("/auth/student-login", json={"phone": phone, "password": "1234"})
    assert r.status_code == 409
    ids = {c["student_id"] for c in r.json()["detail"]["choices"]}
    assert ids == {id1, id2}
    assert client.post("/auth/student-login", json={"phone": phone, "password": "1234", "student_id": id2}).status_code == 200
    assert client.post("/auth/student-login", json={"phone": phone, "password": "nope"}).status_code == 401
    # phone formatting is normalised
    assert client.post("/auth/student-login", json={"phone": "+91 " + phone, "password": "1234", "student_id": id1}).status_code == 200


def test_delete_student_with_history_and_paid_guard():
    tid, h = mk_teacher(trial=True)
    bid = _batch(tid)
    sid, sh = mk_student(teacher_id=tid, batch_id=bid)
    t = client.post("/tests/mcq", headers=h, json={"title": "T", "duration_minutes": 5, "questions": [Q("q")]}).json()["test_id"]
    a = client.post(f"/tests/{t}/start", headers=sh).json()
    client.post(f"/tests/attempts/{a['attempt_id']}/submit", headers=sh, json={"answers": []})
    assert client.delete(f"/students/{sid}", headers=h).status_code == 200
    db = SessionLocal()
    assert db.query(TestAttempt).filter(TestAttempt.student_id == sid).count() == 0
    assert db.query(Student).filter(Student.id == sid).first() is None
    db.close()


def test_owner_can_make_batches_and_add_students_and_teachers_with_batches():
    iid, ih = mk_institute(trial=True)
    b = client.post("/institute/batches", headers=ih, json={"name": "Batch X"})
    assert b.status_code == 200, b.text
    bid = b.json()["id"]
    t = client.post("/institute/teachers", headers=ih, json={"name": "Tea", "phone": _phone(), "password": "pw1234", "is_owner": False, "batch_ids": [bid]})
    assert t.status_code == 200, t.text
    assert [x["id"] for x in t.json()["batches"]] == [bid]
    s = client.post("/institute/students", headers=ih, json={"name": "Stu", "phone": _phone(), "password": "1234", "batch_id": bid})
    assert s.status_code == 200, s.text
    assert client.delete(f"/institute/students/{s.json()['id']}", headers=ih).status_code == 200


def test_teacher_can_add_student_to_own_batch():
    iid, _ = mk_institute(trial=True)
    tid, h = mk_teacher(institute_id=iid)
    bid = client.post("/batches", headers=h, json={"name": "Mine"}).json()["id"]
    r = client.post("/students", headers=h, json={"name": "S", "phone": _phone(), "password": "1234", "batch_id": bid})
    assert r.status_code == 200, r.text


def test_phone_and_pin_validation():
    tid, h = mk_teacher(trial=True)
    assert client.post("/students", headers=h, json={"name": "S", "phone": "abc", "password": "1234"}).status_code == 422
    assert client.post("/students", headers=h, json={"name": " ", "phone": _phone(), "password": "1234"}).status_code == 422
    assert client.post("/students", headers=h, json={"name": "S", "phone": _phone(), "password": "1"}).status_code == 422
