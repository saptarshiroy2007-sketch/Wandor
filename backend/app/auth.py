from datetime import datetime, timedelta
from typing import Any
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db, settings
from .models import Teacher, Student, SuperAdmin

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> tuple[Any, str]:
    creds_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id: str | None = payload.get("sub")
        role: str | None = payload.get("role")
        if user_id is None or role not in {"teacher", "student", "superadmin"}:
            raise creds_exception
    except JWTError:
        raise creds_exception

    if role == "teacher":
        user = db.query(Teacher).filter(Teacher.id == user_id).first()
    elif role == "superadmin":
        user = db.query(SuperAdmin).filter(SuperAdmin.id == user_id).first()
    else:
        user = db.query(Student).filter(Student.id == user_id).first()

    if user is None:
        raise creds_exception
    return user, role


def get_current_superadmin(current: tuple[Any, str] = Depends(get_current_user)) -> SuperAdmin:
    user, role = current
    if role != "superadmin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin access required")
    return user


def get_current_teacher(current: tuple[Any, str] = Depends(get_current_user)) -> Teacher:
    user, role = current
    if role != "teacher":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Teacher access required")
    return user


def get_current_student(current: tuple[Any, str] = Depends(get_current_user)) -> Student:
    user, role = current
    if role != "student":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Student access required")
    return user
