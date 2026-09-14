from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from ..database import get_db, settings
from ..models import Teacher, Student, Institute
from ..schemas import (
    TeacherLogin, StudentLogin, ParentLogin, InstituteLogin, Token,
    TeacherSignup, InstituteSignup, PasswordChange, TeacherProfile,
)
from ..auth import verify_password, hash_password, create_access_token, get_current_teacher, _decode

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic bearer scheme for the role-agnostic change-password endpoint.
# Does NOT enforce a specific tokenUrl so any role's token is accepted.
_any_bearer = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


@router.post("/login", response_model=Token)
def login(payload: TeacherLogin, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if not teacher or not verify_password(payload.password, teacher.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    token = create_access_token(teacher.id, role="teacher")
    return Token(access_token=token)


@router.post("/teacher-signup", response_model=Token)
def teacher_signup(payload: TeacherSignup, db: Session = Depends(get_db)):
    """Self-service signup for an INDEPENDENT teacher (institute_id stays None).
    Students never get an equivalent endpoint - they're only ever created by a
    teacher or institute admin, never self-registering."""
    existing = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="A teacher with this phone already exists")

    teacher = Teacher(
        institute_id=None,
        name=payload.name,
        phone=payload.phone,
        hashed_password=hash_password(payload.password),
        is_owner=False,
    )
    db.add(teacher)
    db.commit()
    db.refresh(teacher)
    token = create_access_token(teacher.id, role="teacher")
    return Token(access_token=token)


@router.post("/institute-signup", response_model=Token)
def institute_signup(payload: InstituteSignup, db: Session = Depends(get_db)):
    """Self-service institute signup - creates the Institute row and activates its
    login password in one request, replacing the old manual DB-insert +
    scripts/set_institute_password.py bootstrap. That script still works as a
    fallback/admin tool but is no longer the only way in."""
    existing = db.query(Institute).filter(Institute.owner_phone == payload.owner_phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="An institute with this phone already exists")

    institute = Institute(
        name=payload.name,
        owner_phone=payload.owner_phone,
        hashed_password=hash_password(payload.password),
    )
    db.add(institute)
    db.commit()
    db.refresh(institute)
    token = create_access_token(institute.id, role="institute_admin")
    return Token(access_token=token)


@router.post("/student-login", response_model=Token)
def student_login(payload: StudentLogin, db: Session = Depends(get_db)):
    """Students log in with phone + the PIN/password their teacher set when adding them
    (see POST /students). If a student was added before login existed and has no
    hashed_password yet, this correctly rejects until a teacher sets one via
    POST /students/{id}/set-password.

    Lenient cross-tenant fix: if institute_id is provided in the payload, the query is
    scoped to that institute so two students at two different institutes sharing a phone
    number don't collide. If institute_id is omitted, the old single-query behaviour
    applies (first DB match wins), which is fine for single-institute deployments."""
    q = db.query(Student).filter(Student.phone == payload.phone)
    if payload.institute_id:
        q = q.filter(Student.institute_id == payload.institute_id)
    student = q.first()
    if not student or not student.hashed_password or not verify_password(payload.password, student.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    token = create_access_token(student.id, role="student")
    return Token(access_token=token)


@router.post("/parent-login", response_model=Token)
def parent_login(payload: ParentLogin, db: Session = Depends(get_db)):
    """Parents log in with their child's phone + the parent PIN a teacher set via
    POST /students/{id}/set-parent-pin. Same not-yet-activated handling as student
    login: if parent_pin_hash is null, this correctly rejects until a teacher sets one.
    NOTE: student.phone is only unique within an institute (not globally) - provide
    institute_id in the payload to avoid cross-tenant collision (see student_login)."""
    q = db.query(Student).filter(Student.phone == payload.student_phone)
    if payload.institute_id:
        q = q.filter(Student.institute_id == payload.institute_id)
    student = q.first()
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


@router.get("/me", response_model=TeacherProfile)
def get_teacher_profile(teacher: Teacher = Depends(get_current_teacher)):
    """Return the authenticated teacher's own profile data.
    Students/parents/institute-admins each have their own /me endpoints on their
    respective routers — this one is teacher-only (get_current_teacher enforces that).
    Only name + phone returned for now; no profile photo until storage is designed."""
    return TeacherProfile(
        id=teacher.id,
        name=teacher.name,
        phone=teacher.phone,
        institute_id=teacher.institute_id,
    )


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    token: str = Depends(_any_bearer),
    db: Session = Depends(get_db),
):
    """Self-service password change for teacher, student, and institute_admin.
    Parent tokens are rejected (parents don't have their own password — their PIN
    is set by a teacher via POST /students/{id}/set-parent-pin).

    The JWT is decoded directly here rather than using a role-specific dependency so
    a single endpoint handles all three writable role types without duplicating the
    route three times. The role claim in the token determines which DB model to update.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    jwt_payload = _decode(token)
    role = jwt_payload.get("role")
    sub = jwt_payload.get("sub")

    if role == "parent":
        raise HTTPException(status_code=403, detail="Parents do not have a self-managed password. Ask a teacher to update your PIN.")

    if role == "teacher":
        user = db.query(Teacher).filter(Teacher.id == sub).first()
    elif role == "student":
        user = db.query(Student).filter(Student.id == sub).first()
    elif role == "institute_admin":
        user = db.query(Institute).filter(Institute.id == sub).first()
    else:
        raise HTTPException(status_code=401, detail="Unrecognised role")

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.hashed_password or not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
