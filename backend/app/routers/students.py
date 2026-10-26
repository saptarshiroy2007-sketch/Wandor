import csv
import io
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student, Teacher, TeacherBatchAssignment, Batch
from ..schemas import (
    StudentCreate, StudentOut, SetStudentPassword, SetParentPin, StudentBulkImportResult,
    StudentProfileUpdate, _profile_completion_pct,
)
from ..auth import get_current_teacher, get_current_student, hash_password
from ..batch_utils import normalize_batch
from ..scoping import owner_scope
from ..services import subscriptions as subs
from ..services.cleanup import delete_student as _delete_student
from ..schemas import normalize_phone

router = APIRouter(prefix="/students", tags=["students"])


def _to_out(s: Student) -> StudentOut:
    return StudentOut(
        id=s.id, name=s.name, phone=s.phone, parent_phone=s.parent_phone,
        batch_id=s.batch_id, batch_name=s.batch.name if s.batch else None,
        has_login=s.hashed_password is not None,
        has_parent_login=s.parent_pin_hash is not None,
    )


def _validate_batch_ownership(teacher: Teacher, batch_id: str | None, db: Session) -> None:
    """A batch_id has to actually belong to this teacher's scope - without this check
    a teacher could point a student at some OTHER institute's/teacher's Batch row just
    by guessing or reusing an id, which owner_scope()'s read-side filtering wouldn't
    catch on write (this is a write, not a read)."""
    if batch_id is None:
        return
    batch = db.query(Batch).filter(Batch.id == batch_id, owner_scope(Batch, teacher)).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")


def _assert_can_add_to_batch(teacher: Teacher, batch_id: str | None, db: Session) -> None:
    """Independent teachers (Teacher.institute_id is None) and institute owners can add
    students to any batch freely. A non-owner teacher who belongs to an institute can
    only add students to a batch their institute admin has explicitly assigned them to
    (see PUT /institute/teachers/{id}/batches)."""
    if teacher.institute_id is None or teacher.is_owner:
        return
    if not batch_id:
        raise HTTPException(
            status_code=403,
            detail="You must specify a batch, and it must be one your institute has assigned you to",
        )
    assigned = db.query(TeacherBatchAssignment).filter(
        TeacherBatchAssignment.teacher_id == teacher.id,
        TeacherBatchAssignment.batch_id == batch_id,
    ).first()
    # A batch the teacher created themselves is theirs to fill - without this, a teacher could
    # make a batch and then be told they aren't allowed to put anyone in it.
    created_it = db.query(Batch.id).filter(Batch.id == batch_id, Batch.teacher_id == teacher.id).first()
    if not assigned and not created_it:
        raise HTTPException(status_code=403, detail="You're not assigned to this batch")


def _get_or_create_batch_by_name(db: Session, teacher: Teacher, raw_name: str | None) -> str | None:
    """Only used by the CSV bulk-import path below, where a human typed a batch NAME
    into a spreadsheet rather than picking an existing batch_id from a dropdown - the
    one place left in the app where a raw batch string still comes in over the wire.
    Case-insensitive match against this teacher's existing batches; creates a new
    Batch row if nothing matches, same as if they'd typed a new name into the "create
    batch" form."""
    name = normalize_batch(raw_name)
    if not name:
        return None
    existing = db.query(Batch).filter(owner_scope(Batch, teacher), Batch.name.ilike(name)).first()
    if existing:
        return existing.id
    batch = Batch(institute_id=teacher.institute_id, teacher_id=teacher.id, name=name)
    db.add(batch)
    db.flush()  # need the id before we can point a Student at it, without committing yet
    return batch.id


@router.post("", response_model=StudentOut)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    _validate_batch_ownership(teacher, payload.batch_id, db)
    _assert_can_add_to_batch(teacher, payload.batch_id, db)

    existing = db.query(Student).filter(
        owner_scope(Student, teacher), Student.phone == payload.phone
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A student with this phone number already exists in your roster")

    subs.assert_can_add_students(db, subs.owner_for_teacher(teacher))

    student = Student(
        institute_id=teacher.institute_id,
        teacher_id=teacher.id,  # only load-bearing when institute_id is None - see app/scoping.py
        name=payload.name,
        phone=payload.phone,
        parent_phone=payload.parent_phone,
        batch_id=payload.batch_id,
        hashed_password=hash_password(payload.password),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return _to_out(student)


@router.get("", response_model=List[StudentOut])
def list_students(
    batch_id: str | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    q = db.query(Student).filter(owner_scope(Student, teacher))
    if batch_id:
        q = q.filter(Student.batch_id == batch_id)
    return [_to_out(s) for s in q.all()]


# ---------- Student self-service (My Profile) - registered BEFORE /{student_id}
# below on purpose. FastAPI/Starlette matches routes in declaration order, and "me"
# would otherwise get swallowed by the {student_id} path parameter (which matches
# any string, including literally "me") if that route were declared first. ----------
@router.get("/me", response_model=StudentOut)
def get_my_profile(student: Student = Depends(get_current_student)):
    out = _to_out(student)
    out.profile_completion_pct = _profile_completion_pct(student.bio, student.photo_url, student.email)
    return out


@router.patch("/me", response_model=StudentOut)
def update_my_profile(
    payload: StudentProfileUpdate,
    db: Session = Depends(get_db),
    student: Student = Depends(get_current_student),
):
    """Same partial-update semantics as the teacher/institute profile endpoints -
    only fields actually sent get changed, everything else is left as-is."""
    if payload.name is not None:
        student.name = payload.name
    if payload.bio is not None:
        student.bio = payload.bio
    if payload.email is not None:
        student.email = payload.email
    db.commit()
    db.refresh(student)
    out = _to_out(student)
    out.profile_completion_pct = _profile_completion_pct(student.bio, student.photo_url, student.email)
    return out


@router.get("/{student_id}", response_model=StudentOut)
def get_student(
    student_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    student = db.query(Student).filter(
        Student.id == student_id, owner_scope(Student, teacher)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    return _to_out(student)


@router.post("/{student_id}/set-password")
def set_student_password(
    student_id: str,
    payload: SetStudentPassword,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Lets a teacher reset a student's login PIN, or activate login for a student
    who was added before this feature existed (hashed_password was null)."""
    student = db.query(Student).filter(
        Student.id == student_id, owner_scope(Student, teacher)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student.hashed_password = hash_password(payload.password)
    db.commit()
    return {"status": "password updated"}


@router.post("/{student_id}/set-parent-pin")
def set_parent_pin(
    student_id: str,
    payload: SetParentPin,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Activates (or resets) the read-only parent-view login for this student's parent.
    Separate PIN from the student's own login, on purpose - parents and kids shouldn't
    share a credential, and a kid changing their PIN shouldn't lock a parent out."""
    student = db.query(Student).filter(
        Student.id == student_id, owner_scope(Student, teacher)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    student.parent_pin_hash = hash_password(payload.pin)
    db.commit()
    return {"status": "parent pin updated"}


@router.post("/bulk-import", response_model=StudentBulkImportResult)
async def bulk_import_students(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """CSV columns: name, phone, parent_phone (optional), batch (optional - a NAME,
    resolved or created via _get_or_create_batch_by_name), password (optional -
    defaults to last 4 digits of phone if blank). Dedupes against existing students
    in this institute AND within the same file (by phone). Never partially fails -
    bad rows are skipped and reported, good rows still get created."""
    if file.content_type not in ("text/csv", "application/vnd.ms-excel", "application/octet-stream", "text/plain"):
        raise HTTPException(status_code=400, detail=f"Expected a CSV file, got {file.content_type}")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File isn't valid UTF-8 text")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(status_code=400, detail="CSV has no header row")
    required_cols = {"name", "phone"}
    missing_cols = required_cols - {c.strip().lower() for c in reader.fieldnames}
    if missing_cols:
        raise HTTPException(status_code=400, detail=f"CSV missing required column(s): {', '.join(missing_cols)}")

    existing_phones = {
        p for (p,) in db.query(Student.phone).filter(owner_scope(Student, teacher)).all()
    }
    seen_in_file = set()
    # Plan cap: rows past the remaining room are skipped and reported like any other
    # bad row (this endpoint never partially fails) rather than rejecting the whole file.
    room = subs.student_capacity(db, subs.owner_for_teacher(teacher))
    created: List[Student] = []
    skipped = []
    total_rows = 0

    for i, row in enumerate(reader, start=2):  # row 1 is the header
        total_rows += 1
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = row.get("name", "")[:120]
        try:
            phone = normalize_phone(row.get("phone", "")) if row.get("phone") else ""
        except ValueError:
            skipped.append({"row": i, "phone": row.get("phone", ""), "reason": "invalid phone number"})
            continue
        if row.get("parent_phone"):
            try:
                row["parent_phone"] = normalize_phone(row["parent_phone"])
            except ValueError:
                row["parent_phone"] = ""

        if not name or not phone:
            skipped.append({"row": i, "phone": phone, "reason": "missing name or phone"})
            continue
        if phone in existing_phones:
            skipped.append({"row": i, "phone": phone, "reason": "already exists in your institute"})
            continue
        if phone in seen_in_file:
            skipped.append({"row": i, "phone": phone, "reason": "duplicate phone within this file"})
            continue

        if room is not None and len(created) >= room:
            skipped.append({"row": i, "phone": phone,
                            "reason": "student limit for your plan reached - upgrade in Billing to add more"})
            continue

        batch_id = _get_or_create_batch_by_name(db, teacher, row.get("batch") or None)
        try:
            _assert_can_add_to_batch(teacher, batch_id, db)
        except HTTPException as exc:
            skipped.append({"row": i, "phone": phone, "reason": exc.detail})
            continue

        password = row.get("password") or phone[-4:]
        if len(password) < 4:
            skipped.append({"row": i, "phone": phone, "reason": "password/PIN must be at least 4 characters"})
            continue
        student = Student(
            institute_id=teacher.institute_id,
            teacher_id=teacher.id,
            name=name,
            phone=phone,
            parent_phone=row.get("parent_phone") or None,
            batch_id=batch_id,
            hashed_password=hash_password(password),
        )
        db.add(student)
        created.append(student)
        seen_in_file.add(phone)

    db.commit()
    for s in created:
        db.refresh(s)

    return StudentBulkImportResult(
        created=[_to_out(s) for s in created],
        skipped=skipped,
        total_rows=total_rows,
        created_count=len(created),
        skipped_count=len(skipped),
    )


@router.delete("/{student_id}")
def delete_student(
    student_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    student = db.query(Student).filter(
        Student.id == student_id, owner_scope(Student, teacher)
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    _delete_student(db, student)
    db.commit()
    return {"status": "deleted"}
