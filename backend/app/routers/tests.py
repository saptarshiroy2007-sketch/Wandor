import json
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Test, TestType, Question, TestAttempt, Student, Teacher
from ..schemas import TestCreateAuto, TestCreateDocument, TestSubmit, FlagEvent, TestOut, UploadResponse, AttemptReviewOut
from ..auth import get_current_teacher, get_current_student
from ..services.mcq_gen import generate_mcqs

router = APIRouter(prefix="/tests", tags=["tests"])


# ---------- Teacher: create tests ----------
@router.get("", response_model=list[TestOut])
def list_tests(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    return db.query(Test).filter(Test.institute_id == teacher.institute_id).all()


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


@router.post("/upload", response_model=UploadResponse)
def upload_test_document(
    file: UploadFile = File(...),
    teacher: Teacher = Depends(get_current_teacher),
):
    uploads_dir = Path(__file__).resolve().parent.parent / 'uploads'
    uploads_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{Path(file.filename).suffix}"
    destination = uploads_dir / filename
    with destination.open("wb") as buffer:
        buffer.write(file.file.read())

    return {"document_url": f"/uploads/{filename}"}


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
@router.get("/available", response_model=list[TestOut])
def list_available_tests(student: Student = Depends(get_current_student), db: Session = Depends(get_db)):
    return db.query(Test).filter(Test.institute_id == student.institute_id).all()


@router.get("/attempts", response_model=list[AttemptReviewOut])
def list_attempts(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    attempts = (
        db.query(TestAttempt)
        .join(Test, Test.id == TestAttempt.test_id)
        .join(Student, Student.id == TestAttempt.student_id)
        .filter(Test.institute_id == teacher.institute_id)
        .order_by(TestAttempt.is_flagged.desc(), TestAttempt.started_at.desc())
        .all()
    )
    response = []
    for attempt in attempts:
        response.append({
            "id": attempt.id,
            "test_id": attempt.test_id,
            "test_title": attempt.test.title,
            "test_type": attempt.test.test_type,
            "student_id": attempt.student_id,
            "student_name": attempt.student.name,
            "flagged": attempt.is_flagged,
            "flag_count": attempt.flag_count,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
            "score": attempt.score,
        })
    return response


@router.post("/{test_id}/start")
def start_attempt(test_id: str, db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    test = db.query(Test).filter(Test.id == test_id, Test.institute_id == student.institute_id).first()
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
def submit_attempt(attempt_id: str, payload: TestSubmit, db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    from datetime import datetime
    attempt = db.query(TestAttempt).filter(TestAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt.student_id != student.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    test = db.query(Test).filter(Test.id == attempt.test_id).first()
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")

    attempt.submitted_at = datetime.utcnow()
    attempt.answers = json.dumps([a.dict() for a in payload.answers]) if payload.answers else None

    if test.test_type == TestType.document_locked:
        db.commit()
        return {"status": "submitted", "flagged": attempt.is_flagged, "flag_count": attempt.flag_count}

    correct = {q.id: q.correct_option for q in db.query(Question).filter(Question.test_id == test.id).all()}
    score = 0
    for ans in payload.answers:
        if correct.get(ans.question_id) == ans.chosen_option:
            score += 1

    attempt.score = score
    db.commit()

    return {"score": score, "total": len(correct), "flagged": attempt.is_flagged, "flag_count": attempt.flag_count}


# ---------- Anti-cheat: called by the Android app the moment it detects a break ----------
@router.post("/attempts/flag")
def flag_attempt(event: FlagEvent, db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """
    The Android client (see LockedTestActivity.kt) calls this the instant onUserLeaveHint()
    or a lock-task exit fires. We flag rather than auto-fail, since the teacher should make
    the call (kid could've had a genuine reason, or it's a false positive on some devices).
    """
    attempt = db.query(TestAttempt).filter(TestAttempt.id == event.attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")

    attempt.is_flagged = True
    attempt.flag_count += 1
    db.commit()

    return {"status": "flagged", "flag_count": attempt.flag_count}
