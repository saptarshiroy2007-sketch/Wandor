from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Teacher
from ..schemas import TeacherLogin, Token
from ..auth import verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=Token)
def login(payload: TeacherLogin, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if not teacher or not verify_password(payload.password, teacher.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    token = create_access_token(teacher.id)
    return Token(access_token=token)
