from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AttendanceRecord, ClassSession, Student, Teacher
from ..schemas import AttendanceMarkBulk, AttendanceOut, AttendanceSummary, BatchAttendanceAnalytics, StudentAttendanceRow
from ..auth import get_current_teacher, get_current_student

router = APIRouter(prefix="/attendance", tags=["attendance"])


@router.post("/mark", response_model=List[AttendanceOut])
def mark_attendance(
    payload: AttendanceMarkBulk,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Bulk-marks attendance for every student in payload.marks against one class session.
    Upserts - calling this again for the same class re-marks rather than duplicating rows."""
    session = db.query(ClassSession).filter(
        ClassSession.id == payload.class_session_id, ClassSession.institute_id == teacher.institute_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class session not found")

    valid_student_ids = {
        s.id for s in db.query(Student.id).filter(
            Student.institute_id == teacher.institute_id,
            Student.id.in_([m.student_id for m in payload.marks]),
        ).all()
    }
    invalid = [m.student_id for m in payload.marks if m.student_id not in valid_student_ids]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Student(s) not found in your institute: {invalid}")

    results = []
    for mark in payload.marks:
        existing = db.query(AttendanceRecord).filter(
            AttendanceRecord.class_session_id == payload.class_session_id,
            AttendanceRecord.student_id == mark.student_id,
        ).first()
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

    db.commit()
    for r in results:
        db.refresh(r)
    return results


@router.get("/class/{class_session_id}", response_model=List[AttendanceOut])
def get_class_attendance(
    class_session_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    session = db.query(ClassSession).filter(
        ClassSession.id == class_session_id, ClassSession.institute_id == teacher.institute_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Class session not found")

    return db.query(AttendanceRecord).filter(
        AttendanceRecord.class_session_id == class_session_id
    ).all()


def _summary_for(db: Session, student_id: str) -> AttendanceSummary:
    records = db.query(AttendanceRecord).filter(AttendanceRecord.student_id == student_id).all()
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
        Student.id == student_id, Student.institute_id == teacher.institute_id
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return _summary_for(db, student_id)


@router.get("/batch/{batch}/analytics", response_model=BatchAttendanceAnalytics)
def batch_attendance_analytics(
    batch: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Per-student attendance % for every student in a batch, sorted lowest-first
    so at-risk students (the ones who need a call home) surface at the top instead
    of being buried in an alphabetical roster."""
    students = db.query(Student).filter(
        Student.institute_id == teacher.institute_id, Student.batch == batch
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
        batch=batch, student_count=len(rows), batch_average_pct=batch_avg, students=rows,
    )


@router.get("/me/summary", response_model=AttendanceSummary)
def my_attendance_summary(
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    """Student-facing endpoint - powers the parent/student dashboard attendance %."""
    return _summary_for(db, student.id)
