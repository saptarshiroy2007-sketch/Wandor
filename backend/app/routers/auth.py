from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Teacher, Student, Institute
from ..schemas import TeacherLogin, StudentLogin, ParentLogin, InstituteLogin, Token
from ..auth import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(payload: TeacherLogin, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if not teacher or not verify_password(payload.password, teacher.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    token = create_access_token(teacher.id, role="teacher")
    return Token(access_token=token)


@router.post("/student-login", response_model=Token)
def student_login(payload: StudentLogin, db: Session = Depends(get_db)):
    """Students log in with phone + the PIN/password their teacher set when adding them
    (see POST /students). If a student was added before login existed and has no
    hashed_password yet, this correctly rejects until a teacher sets one via
    POST /students/{id}/set-password."""
    student = db.query(Student).filter(Student.phone == payload.phone).first()
    if not student or not student.hashed_password or not verify_password(payload.password, student.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    token = create_access_token(student.id, role="student")
    return Token(access_token=token)


@router.post("/parent-login", response_model=Token)
def parent_login(payload: ParentLogin, db: Session = Depends(get_db)):
    """Parents log in with their child's phone + the parent PIN a teacher set via
    POST /students/{id}/set-parent-pin. Same not-yet-activated handling as student
    login: if parent_pin_hash is null, this correctly rejects until a teacher sets one.
    NOTE: student.phone is only unique within an institute (not globally), same caveat
    that applies to student-login - see student_login()'s note above."""
    student = db.query(Student).filter(Student.phone == payload.student_phone).first()
    if not student or not student.parent_pin_hash or not verify_password(payload.pin, student.parent_pin_hash):
        raise HTTPException(status_code=401, detail="Wrong phone number or PIN")
    token = create_access_token(student.id, role="parent")
    return Token(access_token=token)


@router.post("/institute-login", response_model=Token)
def institute_login(payload: InstituteLogin, db: Session = Depends(get_db)):
    """Institute-admin login (owner_phone + Institute.hashed_password) - a separate
    credential from any Teacher row. If hashed_password is null, the owner's login
    hasn't been activated yet - see backend/scripts/set_institute_password.py."""
    institute = db.query(Institute).filter(Institute.owner_phone == payload.phone).first()
    if not institute or not institute.hashed_password or not verify_password(payload.password, institute.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    token = create_access_token(institute.id, role="institute_admin")
    return Token(access_token=token)
