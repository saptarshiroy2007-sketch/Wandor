from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Institute, Teacher, Student, TeacherBatchAssignment, Batch
from ..schemas import (
    BatchCreate,
    InstituteOut, InstituteUpdate, TeacherCreate, TeacherOut, BatchAssignmentSet,
    StudentCreate, StudentOut, BatchOut, _profile_completion_pct,
)
from ..auth import get_current_institute_admin, hash_password
from ..services import subscriptions as subs
from ..services.cleanup import detach_teacher, delete_student
from sqlalchemy.orm import object_session

router = APIRouter(prefix="/institute", tags=["institute"])


def _teacher_to_out(t: Teacher) -> TeacherOut:
    return TeacherOut(
        id=t.id, name=t.name, phone=t.phone, is_owner=t.is_owner,
        batches=[BatchOut(id=a.batch.id, name=a.batch.name) for a in t.batch_assignments],
    )


def _student_to_out(s: Student) -> StudentOut:
    return StudentOut(
        id=s.id, name=s.name, phone=s.phone, parent_phone=s.parent_phone,
        batch_id=s.batch_id, batch_name=s.batch.name if s.batch else None,
        has_login=s.hashed_password is not None,
        has_parent_login=s.parent_pin_hash is not None,
    )


def _validate_institute_batch_ids(institute: Institute, batch_ids: list[str], db: Session) -> None:
    """Every batch_id an admin assigns a teacher to (or a student into) has to
    actually belong to THIS institute - otherwise an admin could point at some other
    institute's/teacher's batch just by guessing an id."""
    if not batch_ids:
        return
    found = db.query(Batch.id).filter(Batch.institute_id == institute.id, Batch.id.in_(batch_ids)).all()
    found_ids = {b_id for (b_id,) in found}
    missing = [b for b in batch_ids if b not in found_ids]
    if missing:
        raise HTTPException(status_code=404, detail=f"Batch(es) not found in your institute: {missing}")


def _institute_to_out(institute: Institute) -> InstituteOut:
    return InstituteOut(
        id=institute.id, name=institute.name, owner_phone=institute.owner_phone,
        plan=(subs.plan_for_owner(object_session(institute), subs.owner_for_institute(institute))
              if object_session(institute) is not None else institute.plan),
        created_at=institute.created_at,
        bio=institute.bio, photo_url=institute.photo_url, email=institute.email,
        profile_completion_pct=_profile_completion_pct(institute.bio, institute.photo_url, institute.email),
    )


@router.get("/me", response_model=InstituteOut)
def get_institute(institute: Institute = Depends(get_current_institute_admin)):
    return _institute_to_out(institute)


@router.patch("/me", response_model=InstituteOut)
def update_institute(
    payload: InstituteUpdate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    """Name plus the new My Profile fields (bio/email) - plan is a billing concern,
    not self-serve yet."""
    institute.name = payload.name
    if payload.bio is not None:
        institute.bio = payload.bio
    if payload.email is not None:
        institute.email = payload.email
    db.commit()
    db.refresh(institute)
    return _institute_to_out(institute)


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
    """Owners aren't batch-scoped, so payload.batch_ids is ignored (not rejected -
    an admin might reuse the same form/payload shape for both) when is_owner=True."""
    existing = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if existing:
        if existing.institute_id is None:
            # Reconciliation case (HANDOFF item 5): this phone belongs to an
            # independent teacher's existing account, not a duplicate signup. The
            # admin can't just absorb someone else's account by knowing their phone
            # number - the teacher has to consent by joining from their own login,
            # via POST /auth/teacher/join-institute, using this institute's own
            # credentials as proof of authorization.
            raise HTTPException(
                status_code=409,
                detail="This phone number already has an independent teacher account. "
                       "Ask them to log in and use 'Join institute' with your institute's "
                       "phone and password instead - they can't be added directly.",
            )
        raise HTTPException(status_code=400, detail="A teacher with this phone already exists")

    if not payload.is_owner:
        _validate_institute_batch_ids(institute, payload.batch_ids, db)

    subs.assert_can_add_teacher(db, subs.owner_for_institute(institute))

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
        for batch_id in dict.fromkeys(payload.batch_ids):  # dedupe, keep order
            db.add(TeacherBatchAssignment(teacher_id=teacher.id, batch_id=batch_id))

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

    _validate_institute_batch_ids(institute, payload.batch_ids, db)

    db.query(TeacherBatchAssignment).filter(TeacherBatchAssignment.teacher_id == teacher.id).delete()
    for batch_id in dict.fromkeys(payload.batch_ids):
        db.add(TeacherBatchAssignment(teacher_id=teacher.id, batch_id=batch_id))
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

    detach_teacher(db, teacher)  # keeps their batches/students/tests/classes
    db.commit()
    return {"status": "deleted"}


# ---------- Institute-admin adding students directly ----------
# Unlike a non-owner teacher (see routers/students.py), the institute admin is never
# batch-scoped - they can add a student to any batch in their own institute.
@router.get("/students", response_model=List[StudentOut])
def list_institute_students(
    batch_id: str | None = None,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    q = db.query(Student).filter(Student.institute_id == institute.id)
    if batch_id:
        q = q.filter(Student.batch_id == batch_id)
    return [_student_to_out(s) for s in q.all()]


@router.post("/students", response_model=StudentOut)
def create_institute_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    if payload.batch_id:
        _validate_institute_batch_ids(institute, [payload.batch_id], db)

    existing = db.query(Student).filter(
        Student.institute_id == institute.id, Student.phone == payload.phone
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A student with this phone already exists at your institute")

    subs.assert_can_add_students(db, subs.owner_for_institute(institute))

    student = Student(
        institute_id=institute.id,
        name=payload.name,
        phone=payload.phone,
        parent_phone=payload.parent_phone,
        batch_id=payload.batch_id,
        hashed_password=hash_password(payload.password),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return _student_to_out(student)


# ---------- Institute-admin batches ----------
# The owner had no way to create a batch (only a teacher could), so a brand-new institute
# couldn't assign anyone to anything. Batches created here belong to the institute with no
# individual teacher attached.
@router.get("/batches", response_model=List[BatchOut])
def list_institute_batches(
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    return db.query(Batch).filter(Batch.institute_id == institute.id).order_by(Batch.name).all()


@router.post("/batches", response_model=BatchOut)
def create_institute_batch(
    payload: BatchCreate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    existing = db.query(Batch).filter(Batch.institute_id == institute.id, Batch.name.ilike(payload.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f'A batch named "{existing.name}" already exists')
    batch = Batch(institute_id=institute.id, teacher_id=None, name=payload.name)
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@router.delete("/students/{student_id}")
def delete_institute_student(
    student_id: str,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
    student = db.query(Student).filter(Student.id == student_id, Student.institute_id == institute.id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    delete_student(db, student)
    db.commit()
    return {"status": "deleted"}
