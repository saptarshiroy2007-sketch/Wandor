import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Test, TestType, Question, TestAttempt, Student
from ..schemas import TestCreateAuto, TestCreateDocument, TestSubmit, FlagEvent, TestOut, TestAnalytics, QuestionStat
from ..auth import get_current_teacher, get_current_student
from ..services.mcq_gen import generate_mcqs
from ..models import Teacher

router = APIRouter(prefix="/tests", tags=["tests"])


# ---------- List tests ----------
@router.get("", response_model=List[TestOut])
def list_tests(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Teacher-facing - every test created for their institute, newest first."""
    tests = db.query(Test).filter(Test.institute_id == teacher.institute_id).order_by(Test.id.desc()).all()
    return [TestOut(id=t.id, title=t.title, test_type=t.test_type.value, duration_minutes=t.duration_minutes, topic=t.topic) for t in tests]


@router.get("/available", response_model=List[TestOut])
def list_available_tests(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """Student-facing - tests they can start, scoped to their own institute."""
    tests = db.query(Test).filter(Test.institute_id == student.institute_id).order_by(Test.id.desc()).all()
    return [TestOut(id=t.id, title=t.title, test_type=t.test_type.value, duration_minutes=t.duration_minutes, topic=t.topic) for t in tests]


WEAK_QUESTION_THRESHOLD_PCT = 50.0  # a question <50% of students get right is flagged "weak" - either badly worded or genuinely hard, worth the teacher's attention either way


# ---------- Teacher: analytics ----------
@router.get("/{test_id}/analytics", response_model=TestAnalytics)
def test_analytics(test_id: str, db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    """Per-question correct-rate breakdown across every SUBMITTED attempt for this test,
    scoped to the teacher's own institute. Only meaningful for mcq_auto tests - a
    document_locked test has no Question rows to analyze, so this just returns zero
    questions/attempts for those rather than erroring, since a teacher checking
    analytics on the wrong test type shouldn't hit a 500."""
    test = db.query(Test).filter(Test.id == test_id, Test.institute_id == teacher.institute_id).first()
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
    for a in attempts:
        if not a.answers:
            continue
        try:
            answers = json.loads(a.answers)
        except (json.JSONDecodeError, TypeError):
            continue  # never let one malformed row blow up analytics for the whole test
        for ans in answers:
            qid = ans.get("question_id")
            if qid not in stats:
                continue  # question since deleted/edited - skip rather than crash
            stats[qid]["attempts"] += 1

    correct_by_qid = {q.id: q.correct_option for q in questions}
    for a in attempts:
        if not a.answers:
            continue
        try:
            answers = json.loads(a.answers)
        except (json.JSONDecodeError, TypeError):
            continue
        for ans in answers:
            qid = ans.get("question_id")
            if qid in stats and ans.get("chosen_option") == correct_by_qid.get(qid):
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
    test = Test(
        institute_id=teacher.institute_id,
        title=payload.title,
        test_type=TestType.mcq_auto,
        duration_minutes=payload.duration_minutes,
        topic=payload.topic,
        num_questions=payload.num_questions,
    )
    db.add(test)
    db.commit()
    db.refresh(test)

    generated = generate_mcqs(payload.topic, payload.num_questions)
    for q in generated:
        db.add(Question(test_id=test.id, **q))
    db.commit()

    return {"test_id": test.id, "questions_generated": len(generated)}


@router.post("/document")
def create_document_test(payload: TestCreateDocument, db: Session = Depends(get_db),
                          teacher: Teacher = Depends(get_current_teacher)):
    """document_url points to a PDF/image already uploaded to your storage (S3/GCS/etc).
    The Android app opens this in lock-task mode - see android/LockedTestActivity.kt."""
    test = Test(
        institute_id=teacher.institute_id,
        title=payload.title,
        test_type=TestType.document_locked,
        duration_minutes=payload.duration_minutes,
        document_url=payload.document_url,
    )
    db.add(test)
    db.commit()
    db.refresh(test)
    return {"test_id": test.id}


# ---------- Student: take tests ----------
@router.post("/{test_id}/start")
def start_attempt(test_id: str, db: Session = Depends(get_db),
                   student: Student = Depends(get_current_student)):
    test = db.query(Test).filter(
        Test.id == test_id, Test.institute_id == student.institute_id
    ).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    attempt = TestAttempt(test_id=test_id, student_id=student.id)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    if test.test_type == TestType.mcq_auto:
        questions = db.query(Question).filter(Question.test_id == test_id).all()
        payload = [{"id": q.id, "text": q.text, "option_a": q.option_a, "option_b": q.option_b,
                    "option_c": q.option_c, "option_d": q.option_d} for q in questions]  # no correct_option leaked
        return {"attempt_id": attempt.id, "type": "mcq", "duration_minutes": test.duration_minutes, "questions": payload}
    else:
        return {"attempt_id": attempt.id, "type": "document", "duration_minutes": test.duration_minutes,
                "document_url": test.document_url}


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(attempt_id: str, payload: TestSubmit, db: Session = Depends(get_db),
                    student: Student = Depends(get_current_student)):
    from datetime import datetime
    attempt = db.query(TestAttempt).filter(
        TestAttempt.id == attempt_id, TestAttempt.student_id == student.id
    ).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.submitted_at is not None:
        raise HTTPException(status_code=400, detail="Attempt already submitted")

    test = db.query(Test).filter(Test.id == attempt.test_id).first()
    correct = {q.id: q.correct_option for q in db.query(Question).filter(Question.test_id == test.id).all()}

    score = 0
    for ans in payload.answers:
        if correct.get(ans.question_id) == ans.chosen_option:
            score += 1

    attempt.score = score
    attempt.submitted_at = datetime.utcnow()
    attempt.answers = json.dumps([a.dict() for a in payload.answers])
    db.commit()

    return {"score": score, "total": len(correct), "flagged": attempt.is_flagged, "flag_count": attempt.flag_count}


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

    attempt.is_flagged = True
    attempt.flag_count += 1
    db.commit()

    return {"status": "flagged", "flag_count": attempt.flag_count}
