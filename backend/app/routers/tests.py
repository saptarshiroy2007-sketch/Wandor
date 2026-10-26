import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Test, TestType, Question, TestAttempt, Student, Batch
from ..schemas import (
    TestCreateAuto, TestCreateDocument, TestSubmit, FlagEvent,
    TestOut, TestAnalytics, QuestionStat, TestGradeSubmit, TestAttemptOut,
)
from ..auth import get_current_teacher, get_current_student
from ..services.notify import notify
from ..services.access import assert_full_access
from ..services.subscriptions import owner_for_teacher, owner_for_student
from ..database import settings
from ..timeutil import utcnow
from datetime import timedelta
from sqlalchemy import or_
from ..scoping import owner_scope, student_test_scope
from ..models import Teacher, NotificationLog

router = APIRouter(prefix="/tests", tags=["tests"])

VALID_OPTIONS = {"a", "b", "c", "d"}


def _to_out(t: Test) -> TestOut:
    return TestOut(
        id=t.id, title=t.title, test_type=t.test_type.value, duration_minutes=t.duration_minutes,
        batch_id=t.batch_id, batch_name=t.batch.name if t.batch else None,
    )


def _validate_batch_ownership(teacher: Teacher, batch_id: str | None, db: Session) -> None:
    """Same check as students.py's - a batch_id on a Test has to actually belong to
    this teacher's scope, or a teacher could restrict a test to some other
    institute's/teacher's batch just by guessing an id."""
    if batch_id is None:
        return
    batch = db.query(Batch).filter(Batch.id == batch_id, owner_scope(Batch, teacher)).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")


# ---------- List tests ----------
@router.get("", response_model=List[TestOut])
def list_tests(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Teacher-facing - every test created for their institute, newest first."""
    tests = db.query(Test).filter(owner_scope(Test, teacher)).order_by(Test.id.desc()).all()
    return [_to_out(t) for t in tests]


@router.get("/available", response_model=List[TestOut])
def list_available_tests(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """Student-facing - tests they can start, scoped to their own institute/teacher AND
    batch. Tests with batch_id=None are visible to everyone in scope. Tests with a
    batch_id set are only visible to students in that exact batch - plain id equality
    now instead of the old case-insensitive string matching, since batch is a real
    entity (see migration 0011)."""
    from sqlalchemy import or_
    tests = db.query(Test).filter(
        student_test_scope(Test, student),
        or_(Test.batch_id.is_(None), Test.batch_id == student.batch_id) if student.batch_id else Test.batch_id.is_(None),
    ).order_by(Test.id.desc()).all()
    return [_to_out(t) for t in tests]


@router.get("/my-attempts", response_model=List[TestAttemptOut])
def my_attempts(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """Student-facing result history (submitted attempts, newest first). Same shape the parent
    view already gets from /parents/tests; document tests show score=None until graded."""
    rows = (
        db.query(TestAttempt, Test.title)
        .join(Test, Test.id == TestAttempt.test_id)
        .filter(TestAttempt.student_id == student.id, TestAttempt.submitted_at.isnot(None))
        .order_by(TestAttempt.submitted_at.desc()).limit(100).all()
    )
    return [
        TestAttemptOut(
            id=a.id, test_id=a.test_id, test_title=title, started_at=a.started_at,
            submitted_at=a.submitted_at, score=a.score, max_score=a.max_score, graded_at=a.graded_at,
            is_flagged=a.is_flagged, flag_count=a.flag_count,
        )
        for a, title in rows
    ]


WEAK_QUESTION_THRESHOLD_PCT = 50.0  # a question <50% of students get right is flagged "weak" - either badly worded or genuinely hard, worth the teacher's attention either way


# ---------- Teacher: analytics ----------
@router.get("/{test_id}/analytics", response_model=TestAnalytics)
def test_analytics(test_id: str, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Per-question correct-rate breakdown across every SUBMITTED attempt for this test,
    scoped to the teacher's own institute. Only meaningful for mcq_auto tests - a
    document_locked test has no Question rows to analyze, so this just returns zero
    questions/attempts for those rather than erroring, since a teacher checking
    analytics on the wrong test type shouldn't hit a 500."""
    assert_full_access(db, owner_for_teacher(teacher), 'Analytics')
    test = db.query(Test).filter(Test.id == test_id, owner_scope(Test, teacher)).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    questions = db.query(Question).filter(Question.test_id == test_id).all()
    attempts = db.query(TestAttempt).filter(
        TestAttempt.test_id == test_id, TestAttempt.submitted_at.isnot(None)
    ).all()

    attempt_count = len(attempts)
    avg_score = round(sum(a.score or 0 for a in attempts) / attempt_count, 2) if attempt_count else 0.0
    avg_score_pct = round((avg_score / len(questions)) * 100, 1) if questions and attempt_count else 0.0

    stats = {q.id: {"correct": 0, "attempts": 0} for q in questions}
    correct_by_qid = {q.id: q.correct_option for q in questions}
    for a in attempts:
        # Every submitted attempt counts for every question - a skipped question is an attempt
        # that got it wrong, not an attempt that never happened.
        for qid in stats:
            stats[qid]["attempts"] += 1
        if not a.answers:
            continue
        try:
            answers = json.loads(a.answers)
        except (json.JSONDecodeError, TypeError):
            continue  # never let one malformed row blow up analytics for the whole test
        for ans in answers:
            qid = ans.get("question_id")
            if qid in stats and str(ans.get("chosen_option", "")).lower() == correct_by_qid.get(qid):
                stats[qid]["correct"] += 1

    question_stats = []
    for q in questions:
        s = stats[q.id]
        pct = round((s["correct"] / s["attempts"]) * 100, 1) if s["attempts"] else 0.0
        question_stats.append(QuestionStat(
            question_id=q.id, text=q.text, attempts=s["attempts"],
            correct_count=s["correct"], correct_pct=pct,
            is_weak=s["attempts"] > 0 and pct < WEAK_QUESTION_THRESHOLD_PCT,
        ))
    question_stats.sort(key=lambda qs: qs.correct_pct)

    return TestAnalytics(
        test_id=test.id, title=test.title, attempt_count=attempt_count,
        average_score=avg_score, average_score_pct=avg_score_pct,
        weak_question_count=sum(1 for qs in question_stats if qs.is_weak),
        questions=question_stats,
    )


# ---------- Teacher: create tests ----------
@router.post("/mcq")
def create_mcq_test(payload: TestCreateAuto, db: Session = Depends(get_db),
                     teacher: Teacher = Depends(get_current_teacher)):
    """Creates a teacher-authored MCQ test. The teacher supplies every question, option,
    and correct answer directly — no LLM generation. Server validates that correct_option
    is one of a/b/c/d for each question; any invalid question causes a 400 rather than
    silently storing a bad correct answer."""
    assert_full_access(db, owner_for_teacher(teacher), 'Tests')
    for i, q in enumerate(payload.questions):
        if q.correct_option.lower() not in VALID_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Question {i+1}: correct_option must be one of a, b, c, d (got '{q.correct_option}')",
            )
    _validate_batch_ownership(teacher, payload.batch_id, db)

    test = Test(
        institute_id=teacher.institute_id,
        teacher_id=teacher.id,
        title=payload.title,
        test_type=TestType.mcq_auto,
        duration_minutes=payload.duration_minutes,
        batch_id=payload.batch_id,
    )
    db.add(test)
    db.commit()
    db.refresh(test)

    for q in payload.questions:
        db.add(Question(
            test_id=test.id,
            text=q.text,
            option_a=q.option_a,
            option_b=q.option_b,
            option_c=q.option_c,
            option_d=q.option_d,
            correct_option=q.correct_option.lower(),
        ))
    db.commit()

    return {"test_id": test.id, "questions_created": len(payload.questions)}


@router.post("/document")
def create_document_test(payload: TestCreateDocument, db: Session = Depends(get_db),
                          teacher: Teacher = Depends(get_current_teacher)):
    """document_url points to a PDF/image already uploaded to your storage (S3/GCS/etc).
    The Android app opens this in lock-task mode - see android/LockedTestActivity.kt."""
    assert_full_access(db, owner_for_teacher(teacher), 'Tests')
    _validate_batch_ownership(teacher, payload.batch_id, db)
    test = Test(
        institute_id=teacher.institute_id,
        teacher_id=teacher.id,
        title=payload.title,
        test_type=TestType.document_locked,
        duration_minutes=payload.duration_minutes,
        document_url=payload.document_url,
        batch_id=payload.batch_id,
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    return {"test_id": test.id}



# ---------- Student: take tests ----------
def _visible_test_for(db: Session, student: Student, test_id: str) -> Test | None:
    """The one rule for 'can this student open this test', shared with the list endpoint:
    in the student's own institute/teacher scope AND (no batch set, or the student's batch).
    /start used to check only the institute, so a batch-restricted test opened by URL for
    anyone, and (institute_id NULL matching every independent teacher) other teachers' tests."""
    q = db.query(Test).filter(Test.id == test_id, student_test_scope(Test, student))
    if student.batch_id:
        q = q.filter(or_(Test.batch_id.is_(None), Test.batch_id == student.batch_id))
    else:
        q = q.filter(Test.batch_id.is_(None))
    return q.first()


def _attempt_payload(db: Session, test: Test, attempt: TestAttempt) -> dict:
    deadline = attempt.started_at + timedelta(minutes=test.duration_minutes)
    base = {"attempt_id": attempt.id, "duration_minutes": test.duration_minutes,
            "seconds_left": max(0, int((deadline - utcnow()).total_seconds()))}
    if test.test_type == TestType.mcq_auto:
        questions = db.query(Question).filter(Question.test_id == test.id).all()
        payload = [{"id": q.id, "text": q.text, "option_a": q.option_a, "option_b": q.option_b,
                    "option_c": q.option_c, "option_d": q.option_d} for q in questions]  # no correct_option leaked
        return {**base, "type": "mcq", "questions": payload}
    return {**base, "type": "document", "document_url": test.document_url}


@router.post("/{test_id}/start")
def start_attempt(test_id: str, db: Session = Depends(get_db),
                   student: Student = Depends(get_current_student)):
    owner = owner_for_student(student)
    test = _visible_test_for(db, student, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    # Re-opening a test you started but haven't submitted resumes THAT attempt (same clock),
    # instead of minting a fresh attempt with a fresh timer each time.
    open_attempt = db.query(TestAttempt).filter(
        TestAttempt.test_id == test_id, TestAttempt.student_id == student.id,
        TestAttempt.submitted_at.is_(None),
    ).order_by(TestAttempt.started_at.desc()).first()
    if open_attempt:
        if utcnow() <= open_attempt.started_at + timedelta(minutes=test.duration_minutes, seconds=settings.test_submit_grace_seconds):
            return _attempt_payload(db, test, open_attempt)  # resuming stays allowed even in grace
        open_attempt.submitted_at = utcnow()  # abandoned and out of time: close it out (no score)
        open_attempt.score = 0.0 if test.test_type == TestType.mcq_auto else None
        open_attempt.max_score = float(db.query(Question).filter(Question.test_id == test_id).count()) if test.test_type == TestType.mcq_auto else None
        db.commit()

    # Only a NEW attempt is a paused feature; resuming one in progress returned above.
    if owner is not None:
        assert_full_access(db, owner, "Tests")
    if settings.test_max_attempts > 0:
        done = db.query(TestAttempt).filter(
            TestAttempt.test_id == test_id, TestAttempt.student_id == student.id,
            TestAttempt.submitted_at.isnot(None),
        ).count()
        if done >= settings.test_max_attempts:
            raise HTTPException(status_code=409, detail="You've already attempted this test.")

    attempt = TestAttempt(test_id=test_id, student_id=student.id, started_at=utcnow())
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return _attempt_payload(db, test, attempt)


def _notify_result(institute_id: str, student_id: str, test_title: str, score: float, total: float):
    """Runs as a background task, same fire-and-forget pattern as classes.py/attendance.py.
    Shared by two callers: mcq_auto's instant auto-grade on submit, and document_locked's
    teacher-published grade via POST /tests/attempts/{id}/grade - a document_locked
    attempt has no instant score at submit time (a teacher grades it manually,
    whenever that happens), so this only fires for it once grade_attempt() runs, not
    on the original submit. Opens its own DB session since background tasks outlive
    the request's session."""
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        student = db.query(Student).filter(Student.id == student_id).first()
        if not student:
            return
        pct = round((score / total) * 100, 1) if total else 0.0
        msg = f"Test result: {student.name} scored {score}/{total} ({pct}%) on \"{test_title}\"."
        channel = notify(student.phone, msg, "test_result")
        db.add(NotificationLog(institute_id=institute_id, recipient_phone=student.phone,
                                channel=channel, message=msg, status=channel))
        if student.parent_phone:
            p_channel = notify(student.parent_phone, msg, "test_result")
            db.add(NotificationLog(institute_id=institute_id, recipient_phone=student.parent_phone,
                                    channel=p_channel, message=msg, status=p_channel))
        db.commit()
    finally:
        db.close()


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: str, payload: TestSubmit, background_tasks: BackgroundTasks,
                    db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    from datetime import datetime
    attempt = db.query(TestAttempt).filter(
        TestAttempt.id == attempt_id, TestAttempt.student_id == student.id
    ).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.submitted_at is not None:
        raise HTTPException(status_code=400, detail="Attempt already submitted")

    test = db.query(Test).filter(Test.id == attempt.test_id).first()
    if utcnow() > attempt.started_at + timedelta(minutes=test.duration_minutes, seconds=settings.test_submit_grace_seconds):
        raise HTTPException(status_code=400, detail="Time's up - this attempt can no longer be submitted.")
    attempt.submitted_at = utcnow()
    # One answer per question (last wins), and only for questions that belong to THIS test.
    # Counting every list entry let the same right answer repeated 10x score 10/3.
    valid_qids = {q_id for (q_id,) in db.query(Question.id).filter(Question.test_id == test.id).all()}
    deduped = {a.question_id: a for a in payload.answers if a.question_id in valid_qids}
    answers = list(deduped.values())
    attempt.answers = json.dumps([a.model_dump() for a in answers])

    if test.test_type == TestType.mcq_auto:
        # Auto-graded instantly - a document_locked attempt has no Question rows to
        # score against, so it must NOT fall through this same path (previously it
        # did: `correct` came back an empty dict, the loop matched nothing, and
        # score got force-set to 0 on every document submission - indistinguishable
        # from a teacher actually grading it a zero). Leave score/max_score/graded_at
        # untouched (None) for document_locked; that's now the "awaiting grading"
        # signal, resolved via POST /tests/attempts/{id}/grade.
        correct = {q.id: q.correct_option for q in db.query(Question).filter(Question.test_id == test.id).all()}
        score = sum(1 for ans in answers if correct.get(ans.question_id) == ans.chosen_option.lower())
        total = len(correct)
        attempt.score = score
        attempt.max_score = float(total)
        db.commit()
        background_tasks.add_task(_notify_result, student.institute_id, student.id, test.title, score, total)
        return {"score": score, "total": total, "flagged": attempt.is_flagged, "flag_count": attempt.flag_count}

    db.commit()
    return {"score": None, "total": None, "flagged": attempt.is_flagged, "flag_count": attempt.flag_count,
            "status": "submitted_awaiting_grading"}


# ---------- Anti-cheat: called by the Android app the moment it detects a break ----------
@router.post("/attempts/flag")
def flag_attempt(event: FlagEvent, db: Session = Depends(get_db),
                  student: Student = Depends(get_current_student)):
    """
    The Android client (see LockedTestActivity.kt) calls this the instant onUserLeaveHint()
    or a lock-task exit fires. We flag rather than auto-fail, since the teacher should make
    the call (kid could've had a genuine reason, or it's a false positive on some devices).
    """
    attempt = db.query(TestAttempt).filter(
        TestAttempt.id == event.attempt_id, TestAttempt.student_id == student.id
    ).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.submitted_at is not None:
        raise HTTPException(status_code=400, detail="Attempt already submitted")

    attempt.is_flagged = True
    attempt.flag_count += 1
    db.commit()

    return {"status": "flagged", "flag_count": attempt.flag_count}


# ---------- Teacher: grade document_locked attempts ----------
@router.get("/{test_id}/ungraded", response_model=List[TestAttemptOut])
def list_ungraded_attempts(test_id: str, db: Session = Depends(get_db),
                            teacher: Teacher = Depends(get_current_teacher)):
    """Submitted document_locked attempts still awaiting a grade, for this teacher's
    institute. This is the worklist a teacher needs to actually find what to mark -
    without it, 'publish a grade' has nothing to publish FROM."""
    test = db.query(Test).filter(Test.id == test_id, owner_scope(Test, teacher)).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    if test.test_type != TestType.document_locked:
        raise HTTPException(status_code=400, detail="Only document_locked tests are manually graded")

    attempts = db.query(TestAttempt).filter(
        TestAttempt.test_id == test_id,
        TestAttempt.submitted_at.isnot(None),
        TestAttempt.graded_at.is_(None),
    ).order_by(TestAttempt.submitted_at.asc()).all()

    return [
        TestAttemptOut(
            id=a.id, test_id=a.test_id, test_title=test.title,
            started_at=a.started_at, submitted_at=a.submitted_at,
            score=a.score, max_score=a.max_score, graded_at=a.graded_at,
            is_flagged=a.is_flagged, flag_count=a.flag_count,
        )
        for a in attempts
    ]


@router.post("/attempts/{attempt_id}/grade", response_model=TestAttemptOut)
def grade_attempt(attempt_id: str, payload: TestGradeSubmit, background_tasks: BackgroundTasks,
                   db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Publishes a grade for a manually-marked document_locked attempt and fires the
    same student+parent notification mcq_auto tests get instantly on submit - this
    is the notify trigger document_locked tests never had (HANDOFF item 4). Only
    document_locked attempts go through here; mcq_auto is auto-graded and can't be
    re-graded through this endpoint."""
    attempt = db.query(TestAttempt).join(Test, Test.id == TestAttempt.test_id).filter(
        TestAttempt.id == attempt_id, owner_scope(Test, teacher),
    ).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    test = db.query(Test).filter(Test.id == attempt.test_id).first()
    if test.test_type != TestType.document_locked:
        raise HTTPException(status_code=400, detail="Only document_locked attempts are graded through this endpoint")
    if attempt.submitted_at is None:
        raise HTTPException(status_code=400, detail="Attempt hasn't been submitted yet")
    if payload.max_score <= 0:
        raise HTTPException(status_code=400, detail="max_score must be greater than 0")
    if payload.score < 0 or payload.score > payload.max_score:
        raise HTTPException(status_code=400, detail="score must be between 0 and max_score")

    from datetime import datetime
    attempt.score = payload.score
    attempt.max_score = payload.max_score
    attempt.graded_at = datetime.utcnow()
    db.commit()
    db.refresh(attempt)

    background_tasks.add_task(
        _notify_result, teacher.institute_id, attempt.student_id,
        test.title, payload.score, payload.max_score,
    )

    return TestAttemptOut(
        id=attempt.id, test_id=attempt.test_id, test_title=test.title,
        started_at=attempt.started_at, submitted_at=attempt.submitted_at,
        score=attempt.score, max_score=attempt.max_score, graded_at=attempt.graded_at,
        is_flagged=attempt.is_flagged, flag_count=attempt.flag_count,
    )
