from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student, FeeRecord, TestAttempt, Test
from ..schemas import StudentOut, AttendanceSummary, FeeRecordOut, TestAttemptOut
from ..auth import get_current_parent
from .attendance import _summary_for

router = APIRouter(prefix="/parents", tags=["parents"])

# Everything below is intentionally read-only (GET only, no POST/PUT/DELETE) - the
# parent view is a dashboard, not a management surface. It reuses the same scoping
# logic teacher/student routes use elsewhere, but here the "scope" is baked into the
# token itself via get_current_parent, so there's no separate ownership check per
# endpoint the way there is for teacher routes checking institute_id.


@router.get("/me", response_model=StudentOut)
def my_child(
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    """Basic profile of the child this parent token is linked to."""
    return StudentOut(
        id=child.id, name=child.name, phone=child.phone, parent_phone=child.parent_phone,
        batch=child.batch, has_login=child.hashed_password is not None,
        has_parent_login=child.parent_pin_hash is not None,
    )


@router.get("/attendance", response_model=AttendanceSummary)
def my_child_attendance(
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    return _summary_for(db, child.id)


@router.get("/fees", response_model=List[FeeRecordOut])
def my_child_fees(
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    """All fee records for this child, paid and unpaid - lets a parent see payment
    history, not just what's currently due (that narrower view is payments.py's
    teacher-facing /payments/due, which is intentionally different in scope)."""
    return db.query(FeeRecord).filter(FeeRecord.student_id == child.id).all()


@router.get("/tests", response_model=List[TestAttemptOut])
def my_child_test_results(
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    """Submitted test attempts only - an in-progress attempt (submitted_at is null)
    isn't shown here since there's no score yet and showing a half-done attempt
    would just be confusing on a parent dashboard."""
    attempts = (
        db.query(TestAttempt, Test.title)
        .join(Test, Test.id == TestAttempt.test_id)
        .filter(TestAttempt.student_id == child.id, TestAttempt.submitted_at.isnot(None))
        .order_by(TestAttempt.submitted_at.desc())
        .all()
    )
    return [
        TestAttemptOut(
            id=a.id, test_id=a.test_id, test_title=title,
            started_at=a.started_at, submitted_at=a.submitted_at,
            score=a.score, is_flagged=a.is_flagged, flag_count=a.flag_count,
        )
        for a, title in attempts
    ]
