"""Deleting people without destroying or orphaning other people's records.

Before: deleting a student left their (possibly PAID) fee records, attendance and test attempts
pointing at nothing - silently on SQLite, a 500 on Postgres (FK violation). Deleting a teacher
500'd on Postgres as soon as they had created anything.
"""
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import (
    AttendanceRecord, Batch, ClassSession, FeeRecord, Student, Teacher, TeacherBatchAssignment, Test, TestAttempt,
)


def delete_student(db: Session, student: Student) -> None:
    """Removes a student and everything that only makes sense with them (attendance, test
    attempts, unpaid fees). Refuses (409) if any fee has money recorded against it: that is
    ledger history the teacher must keep, so it is never deleted from under them."""
    fees = db.query(FeeRecord).filter(FeeRecord.student_id == student.id).all()
    if any(p.status == "paid" for f in fees for p in f.payments):
        raise HTTPException(
            status_code=409,
            detail="This student has fee payments on record, so they can't be deleted. "
                   "Their payment history has to stay.",
        )
    for f in fees:
        db.delete(f)  # unpaid/abandoned only; payment rows cascade
    db.query(AttendanceRecord).filter(AttendanceRecord.student_id == student.id).delete(synchronize_session=False)
    db.query(TestAttempt).filter(TestAttempt.student_id == student.id).delete(synchronize_session=False)
    db.flush()
    db.expire(student)
    db.delete(student)


def detach_teacher(db: Session, teacher: Teacher) -> None:
    """Removes a teacher but keeps what they created. Their batches, students, tests and classes
    belong to the institute, so they just stop naming the departed teacher."""
    for model, col in (
        (Student, "teacher_id"), (Batch, "teacher_id"), (ClassSession, "teacher_id"),
        (Test, "teacher_id"), (AttendanceRecord, "marked_by_teacher_id"),
    ):
        db.query(model).filter(getattr(model, col) == teacher.id).update({col: None}, synchronize_session=False)
    db.query(TeacherBatchAssignment).filter(TeacherBatchAssignment.teacher_id == teacher.id).delete(synchronize_session=False)
    db.flush()
    db.expire(teacher)
    db.delete(teacher)
