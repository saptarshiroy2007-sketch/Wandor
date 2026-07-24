from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ---------- Auth ----------
class TeacherLogin(BaseModel):
    phone: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------- Classes ----------
class ClassCreate(BaseModel):
    batch: str
    subject: str
    start_time: datetime
    end_time: datetime


class ClassCancel(BaseModel):
    reason: Optional[str] = None


class ClassOut(BaseModel):
    id: str
    batch: str
    subject: str
    start_time: datetime
    end_time: datetime
    status: str

    class Config:
        from_attributes = True


# ---------- Tests ----------
class TestCreateAuto(BaseModel):
    title: str
    topic: str
    num_questions: int = 10
    duration_minutes: int = 30


class TestCreateDocument(BaseModel):
    title: str
    document_url: str
    duration_minutes: int = 30


class AnswerSubmit(BaseModel):
    question_id: str
    chosen_option: str


class TestSubmit(BaseModel):
    answers: List[AnswerSubmit]


class FlagEvent(BaseModel):
    """Sent by the Android app the instant it detects a screen-lock break / app switch."""
    attempt_id: str
    event_type: str  # "app_switch", "screen_off", "split_screen_attempt"
    timestamp: datetime


# ---------- Payments ----------
class FeeRecordOut(BaseModel):
    id: str
    student_id: str
    amount_due: float
    amount_paid: float
    is_paid: bool
    due_date: datetime

    class Config:
        from_attributes = True


class CreateOrderRequest(BaseModel):
    fee_record_id: str
