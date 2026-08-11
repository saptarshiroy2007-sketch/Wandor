from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Institute, Teacher, Student, TeacherBatchAssignment
from ..schemas import (
    InstituteOut, InstituteUpdate, TeacherCreate, TeacherOut, BatchAssignmentSet,
    StudentCreate, StudentOut,
)
from ..auth import get_current_institute_admin, hash_password

router = APIRouter(prefix="/institute", tags=["institute"])


def _teacher_to_out(t: Teacher) -> TeacherOut:
    return TeacherOut(
        id=t.id, name=t.name, phone=t.phone, is_owner=t.is_owner,
        batches=[a.batch for a in t.batch_assignments],
    )


def _student_to_out(s: Student) -> StudentOut:
    return StudentOut(
        id=s.id, name=s.name, phone=s.phone, parent_phone=s.parent_phone,
        batch=s.batch, has_login=s.hashed_password is not None,
        has_parent_login=s.parent_pin_hash is not None,
    )


@router.get("/me", response_model=InstituteOut)
def get_institute(institute: Institute = Depends(get_current_institute_admin)):
    return institute


@router.patch("/me", response_model=InstituteOut)
def update_institute(
    payload: InstituteUpdate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    """Only the name is editable here - plan is a billing concern, not self-serve yet."""
    institute.name = payload.name
    db.commit()
    db.refresh(institute)
    return institute


@router.get("/teachers", response_model=List[TeacherOut])
def list_teachers(
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    teachers = db.query(Teacher).filter(Teacher.institute_id == institute.id).all()
    return [_teacher_to_out(t) for t in teachers]


@router.post("/teachers", response_model=TeacherOut)
def create_teacher(
    payload: TeacherCreate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    """Owners aren't batch-scoped, so payload.batches is ignored (not rejected -
    an admin might reuse the same form/payload shape for both) when is_owner=True."""
    existing = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="A teacher with this phone already exists")

    teacher = Teacher(
        institute_id=institute.id,
        name=payload.name,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        is_owner=payload.is_owner,
    )
    db.add(teacher)
    db.flush()  # get teacher.id before adding batch assignments

    if not payload.is_owner:
        for batch in dict.fromkeys(payload.batches):  # dedupe, keep order
            db.add(TeacherBatchAssignment(teacher_id=teacher.id, batch=batch))

    db.commit()
    db.refresh(teacher)
    return _teacher_to_out(teacher)


@router.put("/teachers/{teacher_id}/batches", response_model=TeacherOut)
def set_teacher_batches(
    teacher_id: str,
    payload: BatchAssignmentSet,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    """Full replacement of a teacher's assigned batches. No-op restriction-wise if the
    teacher is the owner (owners are never batch-scoped, see _assert_can_add_to_batch
    in routers/students.py) - the rows get written but simply never checked."""
    teacher = db.query(Teacher).filter(
        Teacher.id == teacher_id, Teacher.institute_id == institute.id
    ).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    db.query(TeacherBatchAssignment).filter(TeacherBatchAssignment.teacher_id == teacher.id).delete()
    for batch in dict.fromkeys(payload.batches):
        db.add(TeacherBatchAssignment(teacher_id=teacher.id, batch=batch))
    db.commit()
    db.refresh(teacher)
    return _teacher_to_out(teacher)


@router.delete("/teachers/{teacher_id}")
def delete_teacher(
    teacher_id: str,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    teacher = db.query(Teacher).filter(
        Teacher.id == teacher_id, Teacher.institute_id == institute.id
    ).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    db.delete(teacher)
    db.commit()
    return {"status": "deleted"}


# ---------- Institute-admin adding students directly ----------
# Unlike a non-owner teacher (see routers/students.py), the institute admin is never
# batch-scoped - they can add a student to any batch in their own institute.
@router.get("/students", response_model=List[StudentOut])
def list_institute_students(
    batch: str | None = None,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    q = db.query(Student).filter(Student.institute_id == institute.id)
    if batch:
        q = q.filter(Student.batch == batch)
    return [_student_to_out(s) for s in q.all()]


@router.post("/students", response_model=StudentOut)
def create_institute_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    existing = db.query(Student).filter(
        Student.institute_id == institute.id, Student.phone == payload.phone
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A student with this phone already exists at your institute")

    student = Student(
        institute_id=institute.id,
        name=payload.name,
        phone=payload.phone,
        parent_phone=payload.parent_phone,
        batch=payload.batch,
        hashed_password=hash_password(payload.password),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return _student_to_out(student)
