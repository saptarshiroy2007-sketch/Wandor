from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db, settings
from .models import Teacher, Student, Institute

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


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject_id: str, role: str = "teacher") -> str:
    """role is 'teacher', 'student', 'parent', or 'institute_admin' - embedded in the
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
    return teacher


def get_current_student(token: str = Depends(student_oauth2_scheme), db: Session = Depends(get_db)) -> Student:
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    payload = _decode(token)
    if payload.get("role") != "student":
        raise creds_exception
    student = db.query(Student).filter(Student.id == payload["sub"]).first()
    if student is None:
        raise creds_exception
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
    return institute
