from typing import List
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AttendanceRecord, ClassSession, Student, Teacher, NotificationLog, Batch
from ..schemas import AttendanceMarkBulk, AttendanceOut, AttendanceSummary, BatchAttendanceAnalytics, StudentAttendanceRow
from ..auth import get_current_teacher, get_current_student
from ..services.notify import notify
from ..services.access import assert_full_access
from ..services.subscriptions import owner_for_teacher
from ..scoping import owner_scope
from ..timeutil import fmt_local, utcnow
from ..models import ClassStatus

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _notify_absent_parents(db: Session, institute_id: str, session_id: str, absent_student_ids: list[str]):
    """Runs as a background task, same pattern as classes.py's _notify_batch, so
    marking attendance for a big batch doesn't block the teacher's request on N
    WhatsApp calls. Only notifies a PARENT (not the student themselves - the student
    already knows they were absent) and only if parent_phone is set."""
    if not absent_student_ids:
        return
    session = db.query(ClassSession).filter(ClassSession.id == session_id).first()
    if not session:
        return
    students = db.query(Student).filter(Student.id.in_(absent_student_ids)).all()
    for s in students:
        if not s.parent_phone:
            continue
        msg = (
            f"Attendance alert: {s.name} was marked ABSENT for {session.subject} "
            f"({session.batch.name if session.batch else ''}) on {fmt_local(session.start_time)}."
        )
        channel = notify(s.parent_phone, msg, "attendance_absent")
        db.add(NotificationLog(institute_id=institute_id, recipient_phone=s.parent_phone,
                                channel=channel, message=msg, status=channel))
    db.commit()


@router.post("/mark", response_model=List[AttendanceOut])
def mark_attendance(
    payload: AttendanceMarkBulk,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Bulk-marks attendance for every student in payload.marks against one class session.
    Upserts - calling this again for the same class re-marks rather than duplicating rows."""
    assert_full_access(db, owner_for_teacher(teacher), 'Attendance')
    session = db.query(ClassSession).filter(
        ClassSession.id == payload.class_session_id, owner_scope(ClassSession, teacher)
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class session not found")
    # Attendance only means something for a class that actually ran. Marking a cancelled or
    # not-yet-started class used to be accepted and silently inflated every attendance %.
    if session.status == ClassStatus.cancelled:
        raise HTTPException(status_code=400, detail="This class was cancelled - there's no attendance to mark")
    if session.start_time > utcnow():
        raise HTTPException(status_code=400, detail="This class hasn't started yet")

    # ...and only for students who are in that class's batch.
    valid_student_ids = {
        s.id for s in db.query(Student.id).filter(
            owner_scope(Student, teacher),
            Student.batch_id == session.batch_id,
            Student.id.in_([m.student_id for m in payload.marks]),
        ).all()
    }
    invalid = [m.student_id for m in payload.marks if m.student_id not in valid_student_ids]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Student(s) not in this class's batch: {invalid}")

    results = []
    newly_absent = []
    marks = list({m.student_id: m for m in payload.marks}.values())  # same student twice: last mark wins
    for mark in marks:
        existing = db.query(AttendanceRecord).filter(
            AttendanceRecord.class_session_id == payload.class_session_id,
            AttendanceRecord.student_id == mark.student_id,
        ).first()
        # Was this student present (or unmarked) right before this write? Unmarked
        # counts as "not previously absent" so a student's first-ever absent mark
        # still notifies. Only an actual present->absent transition should fire -
        # re-submitting an already-absent mark must NOT re-notify the parent.
        was_present_or_unmarked = existing.present if existing else True
        if existing:
            existing.present = mark.present
            existing.marked_by_teacher_id = teacher.id
            results.append(existing)
        else:
            record = AttendanceRecord(
                institute_id=teacher.institute_id,
                class_session_id=payload.class_session_id,
                student_id=mark.student_id,
                present=mark.present,
                marked_by_teacher_id=teacher.id,
            )
            db.add(record)
            results.append(record)
        if not mark.present and was_present_or_unmarked:
            newly_absent.append(mark.student_id)

    db.commit()
    for r in results:
        db.refresh(r)

    background_tasks.add_task(_notify_absent_parents, db, teacher.institute_id, payload.class_session_id, newly_absent)

    return results


@router.get("/class/{class_session_id}", response_model=List[AttendanceOut])
def get_class_attendance(
    class_session_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    session = db.query(ClassSession).filter(
        ClassSession.id == class_session_id, owner_scope(ClassSession, teacher)
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class session not found")

    return db.query(AttendanceRecord).filter(
        AttendanceRecord.class_session_id == class_session_id
    ).all()


def _summary_for(db: Session, student_id: str) -> AttendanceSummary:
    # Cancelled classes never count toward a student's attendance (rows that predate the
    # mark-time check may still exist for them).
    records = (
        db.query(AttendanceRecord)
        .join(ClassSession, ClassSession.id == AttendanceRecord.class_session_id)
        .filter(AttendanceRecord.student_id == student_id, ClassSession.status != ClassStatus.cancelled)
        .all()
    )
    total = len(records)
    present = sum(1 for r in records if r.present)
    pct = round((present / total) * 100, 1) if total else 0.0
    return AttendanceSummary(student_id=student_id, total_classes=total, present_count=present, attendance_pct=pct)


@router.get("/student/{student_id}/summary", response_model=AttendanceSummary)
def student_attendance_summary_for_teacher(
    student_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    student = db.query(Student).filter(
        Student.id == student_id, owner_scope(Student, teacher)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return _summary_for(db, student_id)


@router.get("/batch/{batch_id}/analytics", response_model=BatchAttendanceAnalytics)
def batch_attendance_analytics(
    batch_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Per-student attendance % for every student in a batch, sorted lowest-first
    so at-risk students (the ones who need a call home) surface at the top instead
    of being buried in an alphabetical roster."""
    assert_full_access(db, owner_for_teacher(teacher), 'Analytics')
    batch = db.query(Batch).filter(Batch.id == batch_id, owner_scope(Batch, teacher)).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    students = db.query(Student).filter(
        owner_scope(Student, teacher), Student.batch_id == batch_id
    ).all()
    if not students:
        raise HTTPException(status_code=404, detail="No students found in this batch")

    rows = []
    for s in students:
        summary = _summary_for(db, s.id)
        rows.append(StudentAttendanceRow(
            student_id=s.id, student_name=s.name,
            total_classes=summary.total_classes, present_count=summary.present_count,
            attendance_pct=summary.attendance_pct,
        ))
    rows.sort(key=lambda r: r.attendance_pct)

    batch_avg = round(sum(r.attendance_pct for r in rows) / len(rows), 1) if rows else 0.0
    return BatchAttendanceAnalytics(
        batch_id=batch.id, batch_name=batch.name, student_count=len(rows), batch_average_pct=batch_avg, students=rows,
    )


@router.get("/me/summary", response_model=AttendanceSummary)
def my_attendance_summary(
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    """Student-facing endpoint - powers the parent/student dashboard attendance %."""
    return _summary_for(db, student.id)
