from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db, settings
from dataclasses import dataclass
from .models import Teacher, Student, Institute, PlatformAdmin
from .services.subscriptions import Owner, owner_for_teacher, owner_for_institute, owner_for_student
from .services.access import assert_not_locked

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Kept separate so a teacher token can never be swapped in to authenticate as a student
# (or vice versa) even though both currently use the same signing secret.
student_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/student-login")

# Same isolation as above - a parent token's "sub" is a student_id (the parent view is
# scoped to exactly one child), but the "role" claim keeps it from ever being accepted
# by get_current_student, so a parent can never act as their child, only view them.
parent_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/parent-login")

# Institute-admin (institute owner) token - "sub" is an institute_id, not a teacher_id.
# Deliberately a separate login/credential from any Teacher row (owner_phone +
# Institute.hashed_password), not the existing teacher login with extra permissions -
# keeps "who can manage the institute's teachers" independent of any one teacher account.
institute_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/institute-login")

# Platform operator token - "sub" is a platform_admins.id. Own scheme + role claim so it is
# rejected by every other get_current_* dependency and vice versa.
admin_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/admin/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject_id: str, role: str = "teacher") -> str:
    """role is 'teacher', 'student', 'parent', or 'institute_admin', or 'platform_admin' - embedded in the
    token so one token type can never be used to authenticate as another role."""
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": subject_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode(token: str) -> dict:
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("sub") is None:
            raise creds_exception
        return payload
    except JWTError:
        raise creds_exception


def get_current_teacher(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Teacher:
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    if payload.get("role") != "teacher":
        raise creds_exception
    teacher = db.query(Teacher).filter(Teacher.id == payload["sub"]).first()
    if teacher is None:
        raise creds_exception
    assert_not_locked(db, owner_for_teacher(teacher), payer=teacher.institute_id is None)
    return teacher


def get_current_student(token: str = Depends(student_oauth2_scheme), db: Session = Depends(get_db)) -> Student:
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    if payload.get("role") != "student":
        raise creds_exception
    student = db.query(Student).filter(Student.id == payload["sub"]).first()
    if student is None:
        raise creds_exception
    owner = owner_for_student(student)
    if owner is not None:
        assert_not_locked(db, owner)
    return student


def get_current_parent(token: str = Depends(parent_oauth2_scheme), db: Session = Depends(get_db)) -> Student:
    """Returns the child Student record a parent token is scoped to. Routers built on
    this dependency automatically inherit that scoping - no extra ownership check
    needed, since the token itself can only ever resolve to the one linked child."""
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    if payload.get("role") != "parent":
        raise creds_exception
    student = db.query(Student).filter(Student.id == payload["sub"]).first()
    if student is None:
        raise creds_exception
    owner = owner_for_student(student)
    if owner is not None:
        assert_not_locked(db, owner)
    return student


def get_current_institute_admin(token: str = Depends(institute_oauth2_scheme), db: Session = Depends(get_db)) -> Institute:
    """Returns the Institute record an institute-admin token is scoped to. Routers
    built on this dependency inherit that scoping automatically - same pattern as
    get_current_parent, just resolving to an Institute instead of a Student."""
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    if payload.get("role") != "institute_admin":
        raise creds_exception
    institute = db.query(Institute).filter(Institute.id == payload["sub"]).first()
    if institute is None:
        raise creds_exception
    assert_not_locked(db, owner_for_institute(institute), payer=True)
    return institute


def get_current_platform_admin(token: str = Depends(admin_oauth2_scheme), db: Session = Depends(get_db)) -> PlatformAdmin:
    """Platform operator only. No lock/ban checks - admins have no subscription."""
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    if payload.get("role") != "platform_admin":
        raise creds_exception
    admin = db.query(PlatformAdmin).filter(PlatformAdmin.id == payload["sub"]).first()
    if admin is None:
        raise creds_exception
    return admin


@dataclass(frozen=True)
class BillingActor:
    """Who is calling a /billing endpoint and whose subscription it concerns.
    `owner` is the payer (institute, or an independent teacher); `can_manage` is False
    for a teacher who belongs to an institute - they can SEE their institute's plan
    but only the institute admin can buy/cancel it."""
    owner: Owner
    can_manage: bool
    name: str
    contact: str


def get_billing_actor(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> BillingActor:
    """Billing is the one area both an institute admin token and a teacher token may
    reach, so it needs its own role-aware dependency (the other get_current_* ones each
    accept exactly one role)."""
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    role = payload.get("role")
    if role == "institute_admin":
        inst = db.query(Institute).filter(Institute.id == payload["sub"]).first()
        if inst is None:
            raise creds_exception
        assert_not_locked(db, owner_for_institute(inst), billing=True, payer=True)
        return BillingActor(owner_for_institute(inst), True, inst.name, inst.owner_phone)
    if role == "teacher":
        teacher = db.query(Teacher).filter(Teacher.id == payload["sub"]).first()
        if teacher is None:
            raise creds_exception
        independent = teacher.institute_id is None
        # R2: only someone who can pay may reach Billing under a payment-ban
        assert_not_locked(db, owner_for_teacher(teacher), billing=independent, payer=independent)
        return BillingActor(owner_for_teacher(teacher), independent, teacher.name, teacher.phone)
    raise creds_exception
