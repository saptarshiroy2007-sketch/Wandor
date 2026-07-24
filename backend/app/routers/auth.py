from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db, settings
from ..models import Institute, Teacher, Student, SuperAdmin
from ..schemas import LoginRequest, Token, TeacherRegister, StudentRegister, CurrentUser, SuperAdminRegister
from ..auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token)
def register_teacher(payload: TeacherRegister, db: Session = Depends(get_db)):
    existing_teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if existing_teacher:
        raise HTTPException(status_code=400, detail="Teacher with this phone already exists")

    existing_institute = db.query(Institute).filter(Institute.owner_phone == payload.phone).first()
    if existing_institute:
        raise HTTPException(status_code=400, detail="Institute owner phone already registered")

    institute = Institute(name=payload.institute_name, owner_phone=payload.phone)
    db.add(institute)
    db.commit()
    db.refresh(institute)

    teacher = Teacher(
        institute_id=institute.id,
        name=payload.name,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        is_owner=True,
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)

    token = create_access_token(teacher.id, "teacher")
    return Token(access_token=token, role="teacher")


@router.post("/student-register", response_model=Token)
def register_student(payload: StudentRegister, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.phone == payload.phone).first()
    if student:
        raise HTTPException(status_code=400, detail="Student with this phone already exists")

    institute = db.query(Institute).filter(Institute.invite_code == payload.invite_code).first()
    if not institute:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    student = Student(
        institute_id=institute.id,
        name=payload.name,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        batch=payload.batch,
        parent_phone=payload.parent_phone,
    )
    db.add(student)
    db.commit()
    db.refresh(student)

    token = create_access_token(student.id, "student")
    return Token(access_token=token, role="student")


@router.post("/register-superadmin", response_model=Token)
def register_superadmin(payload: SuperAdminRegister, db: Session = Depends(get_db)):
    if not settings.superadmin_register_secret or payload.register_secret != settings.superadmin_register_secret:
        raise HTTPException(status_code=403, detail="Invalid superadmin registration secret")

    existing_admin = db.query(SuperAdmin).filter(SuperAdmin.phone == payload.phone).first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="Superadmin with this phone already exists")

    admin = SuperAdmin(
        name=payload.name,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)

    token = create_access_token(admin.id, "superadmin")
    return Token(access_token=token, role="superadmin")


@router.get("/me", response_model=CurrentUser)
def current_user(current: tuple[object, str] = Depends(get_current_user)):
    user, role = current
    if role == "teacher":
        return CurrentUser(role=role, invite_code=user.institute.invite_code)
    return CurrentUser(role=role, invite_code=None)


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(SuperAdmin).filter(SuperAdmin.phone == payload.phone).first()
    if admin and verify_password(payload.password, admin.hashed_password):
        token = create_access_token(admin.id, "superadmin")
        return Token(access_token=token, role="superadmin")

    teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if teacher and verify_password(payload.password, teacher.hashed_password):
        token = create_access_token(teacher.id, "teacher")
        return Token(access_token=token, role="teacher")

    student = db.query(Student).filter(Student.phone == payload.phone).first()
    if student and verify_password(payload.password, student.hashed_password):
        token = create_access_token(student.id, "student")
        return Token(access_token=token, role="student")

    raise HTTPException(status_code=401, detail="Wrong phone number or password")
