from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Student
from ..schemas import StudentRegister
from ..auth import get_current_teacher, hash_password

router = APIRouter(prefix="/students", tags=["students"])


@router.post("", response_model=dict)
def create_student(payload: StudentRegister, db: Session = Depends(get_db), teacher = Depends(get_current_teacher)):
    existing = db.query(Student).filter(Student.phone == payload.phone, Student.institute_id == teacher.institute_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Student with this phone already exists")

    student = Student(
        institute_id=teacher.institute_id,
        name=payload.name,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        batch=payload.batch,
        parent_phone=payload.parent_phone,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return {"id": student.id, "name": student.name, "phone": student.phone, "batch": student.batch}


@router.get("", response_model=list[dict])
def list_students(db: Session = Depends(get_db), teacher = Depends(get_current_teacher)):
    return db.query(Student).filter(Student.institute_id == teacher.institute_id).all()
