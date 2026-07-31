import csv
import io
from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student, Teacher
from ..schemas import StudentCreate, StudentOut, SetStudentPassword, SetParentPin, StudentBulkImportResult
from ..auth import get_current_teacher, hash_password

router = APIRouter(prefix="/students", tags=["students"])


def _to_out(s: Student) -> StudentOut:
    return StudentOut(
        id=s.id, name=s.name, phone=s.phone, parent_phone=s.parent_phone,
        batch=s.batch, has_login=s.hashed_password is not None,
        has_parent_login=s.parent_pin_hash is not None,
    )


@router.post("", response_model=StudentOut)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    existing = db.query(Student).filter(
        Student.institute_id == teacher.institute_id, Student.phone == payload.phone
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="A student with this phone already exists at your institute")

    student = Student(
        institute_id=teacher.institute_id,
        name=payload.name,
        phone=payload.phone,
        parent_phone=payload.parent_phone,
        batch=payload.batch,
        hashed_password=hash_password(payload.password),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return _to_out(student)


@router.get("", response_model=List[StudentOut])
def list_students(
    batch: str | None = None,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    q = db.query(Student).filter(Student.institute_id == teacher.institute_id)
    if batch:
        q = q.filter(Student.batch == batch)
    return [_to_out(s) for s in q.all()]


@router.get("/{student_id}", response_model=StudentOut)
def get_student(
    student_id: str,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    student = db.query(Student).filter(
        Student.id == student_id, Student.institute_id == teacher.institute_id
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
        Student.id == student_id, Student.institute_id == teacher.institute_id
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
        Student.id == student_id, Student.institute_id == teacher.institute_id
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
    """CSV columns: name, phone, parent_phone (optional), batch (optional), password
    (optional - defaults to last 4 digits of phone if blank). Dedupes against existing
    students in this institute AND within the same file (by phone). Never partially
    fails - bad rows are skipped and reported, good rows still get created."""
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
        p for (p,) in db.query(Student.phone).filter(Student.institute_id == teacher.institute_id).all()
    }
    seen_in_file = set()
    created: List[Student] = []
    skipped = []
    total_rows = 0

    for i, row in enumerate(reader, start=2):  # row 1 is the header
        total_rows += 1
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name = row.get("name", "")
        phone = row.get("phone", "")

        if not name or not phone:
            skipped.append({"row": i, "phone": phone, "reason": "missing name or phone"})
            continue
        if phone in existing_phones:
            skipped.append({"row": i, "phone": phone, "reason": "already exists in your institute"})
            continue
        if phone in seen_in_file:
            skipped.append({"row": i, "phone": phone, "reason": "duplicate phone within this file"})
            continue

        password = row.get("password") or phone[-4:]
        student = Student(
            institute_id=teacher.institute_id,
            name=name,
            phone=phone,
            parent_phone=row.get("parent_phone") or None,
            batch=row.get("batch") or None,
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
        Student.id == student_id, Student.institute_id == teacher.institute_id
    ).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    db.delete(student)
    db.commit()
    return {"status": "deleted"}
