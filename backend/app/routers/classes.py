from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import and_

from ..database import get_db
from ..models import ClassSession, ClassStatus, Student, Teacher, NotificationLog, Batch
from ..schemas import ClassCreate, ClassCancel, ClassReschedule, ClassOut
from ..auth import get_current_teacher, get_current_student
from ..timeutil import fmt_local, utcnow
from ..services.notify import notify
from ..scoping import owner_scope, student_test_scope

router = APIRouter(prefix="/classes", tags=["classes"])


def effective_status(session: ClassSession) -> str:
    """'completed' is derived, not stored: nothing ever flipped the column, so past classes
    stayed 'scheduled' forever with a live Cancel button. A scheduled class whose end time has
    passed is completed."""
    if session.status == ClassStatus.scheduled and session.end_time <= utcnow():
        return ClassStatus.completed.value
    return session.status.value


def _to_out(session: ClassSession) -> ClassOut:
    return ClassOut(
        id=session.id, batch_id=session.batch_id, batch_name=session.batch.name if session.batch else "",
        subject=session.subject, start_time=session.start_time, end_time=session.end_time,
        status=effective_status(session),
    )


def _validate_batch_ownership(teacher: Teacher, batch_id: str, db: Session) -> Batch:
    """Same pattern as students.py/tests.py - a batch_id has to actually belong to
    this teacher's scope. Returns the Batch (callers need its .name for the
    notification message) rather than just validating and discarding it."""
    batch = db.query(Batch).filter(Batch.id == batch_id, owner_scope(Batch, teacher)).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch


def _notify_batch(db: Session, institute_id: str | None, teacher_id: str, batch_id: str, message: str, template: str | None = None):
    """Fires notifications to every student (and parent, if set) in a batch. Runs as a
    background task so the teacher's API call returns instantly instead of blocking on
    N WhatsApp calls. Plain batch_id equality now - no more case-insensitive string
    matching needed since batch is a real entity (migration 0011).

    Scoping mirrors app/scoping.py's owner_scope() but inlined against raw ids rather
    than a Teacher object, since this runs as a background task after the request's
    teacher instance may already be detached from its session. institute_id=None means
    an independent teacher, so this must also match on teacher_id - otherwise scheduling
    a class as one independent teacher would notify every OTHER independent teacher's
    same batch_id too (can't actually happen since batch_id is now teacher-scoped at
    creation, but the explicit check costs nothing and keeps this function correct on
    its own rather than relying on that invariant holding elsewhere)."""
    scope = (
        Student.institute_id == institute_id
        if institute_id is not None
        else and_(Student.institute_id.is_(None), Student.teacher_id == teacher_id)
    )
    students = db.query(Student).filter(scope, Student.batch_id == batch_id).all()
    for s in students:
        channel = notify(s.phone, message, template)
        db.add(NotificationLog(institute_id=institute_id, recipient_phone=s.phone,
                                channel=channel, message=message, status=channel))
        if s.parent_phone:
            p_channel = notify(s.parent_phone, message, template)
            db.add(NotificationLog(institute_id=institute_id, recipient_phone=s.parent_phone,
                                    channel=p_channel, message=message, status=p_channel))
    db.commit()


@router.post("", response_model=ClassOut)
def schedule_class(
    payload: ClassCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    batch = _validate_batch_ownership(teacher, payload.batch_id, db)

    session = ClassSession(
        institute_id=teacher.institute_id,
        teacher_id=teacher.id,
        batch_id=payload.batch_id,
        subject=payload.subject,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status=ClassStatus.scheduled,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    msg = f"New class scheduled: {payload.subject} for {batch.name} on {fmt_local(payload.start_time)}"
    background_tasks.add_task(_notify_batch, db, teacher.institute_id, teacher.id, payload.batch_id, msg, "class_scheduled")

    return _to_out(session)


@router.post("/{class_id}/cancel", response_model=ClassOut)
def cancel_class(
    class_id: str,
    payload: ClassCancel,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    session = db.query(ClassSession).filter(
        ClassSession.id == class_id, owner_scope(ClassSession, teacher)
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")
    if session.status == ClassStatus.cancelled:
        # Used to return 200 and re-notify the whole batch every time.
        raise HTTPException(status_code=400, detail="This class is already cancelled")
    if effective_status(session) == "completed":
        raise HTTPException(status_code=400, detail="This class has already happened")

    session.status = ClassStatus.cancelled
    session.cancel_reason = payload.reason
    db.commit()
    db.refresh(session)

    reason_txt = f" ({payload.reason})" if payload.reason else ""
    batch_name = session.batch.name if session.batch else ""
    msg = f"Class CANCELLED: {session.subject} for {batch_name} originally at {fmt_local(session.start_time)}{reason_txt}"
    background_tasks.add_task(_notify_batch, db, teacher.institute_id, teacher.id, session.batch_id, msg, "class_cancelled")

    return _to_out(session)


@router.post("/{class_id}/reschedule", response_model=ClassOut)
def reschedule_class(
    class_id: str,
    payload: ClassReschedule,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Moves a scheduled class to a new time and notifies the batch with BOTH the old
    and new time (a bare 'new time' alert is easy to skim past - showing what changed
    from is what actually gets a parent to update their kid's plan). Only meaningful
    for a still-scheduled class; a cancelled or already-completed session can't be
    rescheduled, has to be re-created via POST /classes instead."""
    session = db.query(ClassSession).filter(
        ClassSession.id == class_id, owner_scope(ClassSession, teacher)
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")
    if effective_status(session) != "scheduled":
        raise HTTPException(status_code=400, detail=f"Can't reschedule a {effective_status(session)} class")

    old_start = session.start_time
    session.start_time = payload.start_time
    session.end_time = payload.end_time
    db.commit()
    db.refresh(session)

    reason_txt = f" ({payload.reason})" if payload.reason else ""
    batch_name = session.batch.name if session.batch else ""
    msg = (
        f"Class RESCHEDULED: {session.subject} for {batch_name}, moved from "
        f"{fmt_local(old_start)} to {fmt_local(session.start_time)}{reason_txt}"
    )
    background_tasks.add_task(_notify_batch, db, teacher.institute_id, teacher.id, session.batch_id, msg, "class_rescheduled")

    return _to_out(session)


@router.get("", response_model=List[ClassOut])
def list_classes(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    sessions = db.query(ClassSession).filter(owner_scope(ClassSession, teacher)).all()
    return [_to_out(s) for s in sessions]


@router.get("/my", response_model=List[ClassOut])
def my_classes(db: Session = Depends(get_db), student: Student = Depends(get_current_student)):
    """Student-facing schedule: this student's batch's classes, cancelled ones included so a
    student can SEE a cancellation even when the WhatsApp message never arrived. Students with
    no batch see nothing (classes always belong to a batch)."""
    if not student.batch_id:
        return []
    sessions = db.query(ClassSession).filter(
        student_test_scope(ClassSession, student), ClassSession.batch_id == student.batch_id,
    ).order_by(ClassSession.start_time.desc()).limit(100).all()
    return [_to_out(s) for s in sessions]
