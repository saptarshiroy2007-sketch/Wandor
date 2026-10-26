from typing import List
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student, FeeRecord, TestAttempt, Test
from ..ratelimit import rate_limit
from ..schemas import (
    StudentOut, AttendanceSummary, FeeRecordOut, TestAttemptOut,
    MyFeesOut, CreateOrderRequest, VerifyFeePayment, ReceiptOut,
)
from ..auth import get_current_parent
from . import payments
from .attendance import _summary_for

router = APIRouter(prefix="/parents", tags=["parents"])

# The parent view is a dashboard, not a management surface: everything is read-only
# EXCEPT paying the child's fees (the three fee-payment routes further down, which are
# the only POSTs here). Scoping is baked into the token itself via get_current_parent -
# it can only ever resolve to the one linked child - so there's no separate ownership
# check per endpoint the way there is for teacher routes checking institute_id.


@router.get("/me", response_model=StudentOut)
def my_child(
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    """Basic profile of the child this parent token is linked to."""
    return StudentOut(
        id=child.id, name=child.name, phone=child.phone, parent_phone=child.parent_phone,
        batch_id=child.batch_id, batch_name=child.batch.name if child.batch else None,
        has_login=child.hashed_password is not None,
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
    """(Older, thinner view - the dashboard now uses /my-fees.) All fee records for this child, paid and unpaid - lets a parent see payment
    history, not just what's currently due (that narrower view is payments.py's
    teacher-facing /payments/due, which is intentionally different in scope)."""
    return db.query(FeeRecord).filter(FeeRecord.student_id == child.id).all()


# ---------- Paying the child's fees ----------
# Same flow as the student's own /payments/* routes - see the shared helpers in
# routers/payments.py. Reachable only with a PARENT token (a student/teacher token is
# rejected by get_current_parent), and only ever touches the one linked child's fees.
# Own rate-limit bucket so a parent and child on the same account don't share a quota.
@router.get("/my-fees", response_model=MyFeesOut)
def my_child_fees_payable(
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    """Like /fees but with description/paid-on and whether online payment is available."""
    return payments.my_fees_for(db, child)


@router.post("/create-order",
             dependencies=[Depends(rate_limit("parent-create-order", "rate_limit_payment_per_min"))])
def parent_create_order(
    payload: CreateOrderRequest,
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    return payments.create_order_for(db, child, payload, "parent")


@router.post("/verify", dependencies=[Depends(rate_limit("parent-verify", "rate_limit_verify_per_min"))])
def parent_verify_payment(
    payload: VerifyFeePayment,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    return payments.verify_payment_for(db, child, payload, background_tasks, "parent")


@router.get("/receipts/{payment_id}", response_model=ReceiptOut)
def parent_receipt(
    payment_id: str,
    db: Session = Depends(get_db),
    child: Student = Depends(get_current_parent),
):
    return payments.receipt_for_student(db, child, payment_id)


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
            score=a.score, max_score=a.max_score, graded_at=a.graded_at,
            is_flagged=a.is_flagged, flag_count=a.flag_count,
        )
        for a, title in attempts
    ]
