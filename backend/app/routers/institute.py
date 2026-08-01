from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Institute, Teacher
from ..schemas import InstituteOut, InstituteUpdate, TeacherCreate, TeacherOut
from ..auth import get_current_institute_admin, hash_password

router = APIRouter(prefix="/institute", tags=["institute"])


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
    return db.query(Teacher).filter(Teacher.institute_id == institute.id).all()


@router.post("/teachers", response_model=TeacherOut)
def create_teacher(
    payload: TeacherCreate,
    db: Session = Depends(get_db),
    institute: Institute = Depends(get_current_institute_admin),
):
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
    db.commit()
    db.refresh(teacher)
    return teacher


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
