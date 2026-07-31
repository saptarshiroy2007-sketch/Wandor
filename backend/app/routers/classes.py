from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ClassSession, ClassStatus, Student, Teacher, NotificationLog
from ..schemas import ClassCreate, ClassCancel, ClassOut
from ..auth import get_current_teacher
from ..services.notify import notify

router = APIRouter(prefix="/classes", tags=["classes"])


def _notify_batch(db: Session, institute_id: str, batch: str, message: str, template: str | None = None):
    """Fires notifications to every student (and parent, if set) in a batch. Runs as a
    background task so the teacher's API call returns instantly instead of blocking on
    N WhatsApp calls."""
    students = db.query(Student).filter(
        Student.institute_id == institute_id, Student.batch == batch
    ).all()
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
    session = ClassSession(
        institute_id=teacher.institute_id,
        teacher_id=teacher.id,
        batch=payload.batch,
        subject=payload.subject,
        start_time=payload.start_time,
        end_time=payload.end_time,
        status=ClassStatus.scheduled,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    msg = f"New class scheduled: {payload.subject} for {payload.batch} on {payload.start_time.strftime('%d %b, %I:%M %p')}"
    background_tasks.add_task(_notify_batch, db, teacher.institute_id, payload.batch, msg, "class_scheduled")

    return session


@router.post("/{class_id}/cancel", response_model=ClassOut)
def cancel_class(
    class_id: str,
    payload: ClassCancel,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    session = db.query(ClassSession).filter(
        ClassSession.id == class_id, ClassSession.institute_id == teacher.institute_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class not found")

    session.status = ClassStatus.cancelled
    session.cancel_reason = payload.reason
    db.commit()
    db.refresh(session)

    reason_txt = f" ({payload.reason})" if payload.reason else ""
    msg = f"Class CANCELLED: {session.subject} for {session.batch} originally at {session.start_time.strftime('%d %b, %I:%M %p')}{reason_txt}"
    background_tasks.add_task(_notify_batch, db, teacher.institute_id, session.batch, msg, "class_cancelled")

    return session


@router.get("", response_model=List[ClassOut])
def list_classes(db: Session = Depends(get_db), teacher: Teacher = Depends(get_current_teacher)):
    return db.query(ClassSession).filter(ClassSession.institute_id == teacher.institute_id).all()
