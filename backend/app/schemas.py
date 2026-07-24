from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# ---------- Auth ----------
class LoginRequest(BaseModel):
    phone: str
    password: str


class TeacherRegister(BaseModel):
    institute_name: str
    name: str
    phone: str
    password: str


class StudentRegister(BaseModel):
    name: str
    phone: str
    password: str
    batch: str
    parent_phone: str | None = None
    invite_code: str


class SuperAdminRegister(BaseModel):
    name: str
    phone: str
    password: str
    register_secret: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class CurrentUser(BaseModel):
    role: str
    invite_code: str | None = None


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
    student_name: str | None = None
    amount_due: float
    amount_paid: float
    is_paid: bool
    due_date: datetime
    paid_at: datetime | None = None
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None

    class Config:
        from_attributes = True


class CreateOrderRequest(BaseModel):
    fee_record_id: str


class VerifyPaymentRequest(BaseModel):
    fee_record_id: str
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


class CreateFeeRequest(BaseModel):
    student_id: str
    amount_due: float
    due_date: datetime


class AdminSummary(BaseModel):
    total_institutes: int
    total_teachers: int
    total_students: int
    total_fees: int
    total_paid: float
    total_due: float
    overdue_count: int
    overdue_amount: float


class InstituteAdminOut(BaseModel):
    id: str
    name: str
    owner_phone: str
    plan: str
    created_at: datetime
    total_teachers: int
    total_students: int
    total_fees: int
    total_paid: float
    total_due: float
    overdue_count: int

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    document_url: str


class AttemptReviewOut(BaseModel):
    id: str
    test_id: str
    test_title: str
    test_type: str
    student_id: str
    student_name: str
    flagged: bool
    flag_count: int
    started_at: datetime
    submitted_at: datetime | None = None
    score: float | None = None

    class Config:
        from_attributes = True


class TestOut(BaseModel):
    id: str
    title: str
    test_type: str
    duration_minutes: int
    document_url: str | None = None
    topic: str | None = None
    num_questions: int | None = None

    class Config:
        from_attributes = True
