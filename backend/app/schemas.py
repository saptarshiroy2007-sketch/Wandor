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


class StudentLogin(BaseModel):
    phone: str
    password: str


class ParentLogin(BaseModel):
    """Parent logs in as the parent of one specific child, not with their own
    account - avoids inventing a separate multi-child parent identity/table for now.
    A parent with two kids at the institute just logs in twice with each child's phone."""
    student_phone: str
    pin: str


class InstituteLogin(BaseModel):
    """Institute-admin login is owner_phone + Institute.hashed_password - a separate
    credential from any Teacher row, not the teacher login with extra permissions."""
    phone: str
    password: str


# ---------- Students ----------
class StudentCreate(BaseModel):
    name: str
    phone: str
    parent_phone: Optional[str] = None
    batch: Optional[str] = None
    password: str  # PIN the teacher sets for the student to log in with (student can change later)


class StudentOut(BaseModel):
    id: str
    name: str
    phone: str
    parent_phone: Optional[str] = None
    batch: Optional[str] = None
    has_login: bool  # true if hashed_password is set - lets the frontend show "activate login" vs not
    has_parent_login: bool = False  # true if parent_pin_hash is set

    class Config:
        from_attributes = True


class SetStudentPassword(BaseModel):
    password: str


class SetParentPin(BaseModel):
    pin: str


class StudentBulkImportRow(BaseModel):
    name: str
    phone: str
    parent_phone: Optional[str] = None
    batch: Optional[str] = None
    password: Optional[str] = None  # if blank, defaults to last 4 digits of phone


class StudentBulkImportResult(BaseModel):
    created: List[StudentOut]
    skipped: List[dict]  # [{"row": int, "phone": str, "reason": str}]
    total_rows: int
    created_count: int
    skipped_count: int


# ---------- Attendance ----------
class AttendanceMarkOne(BaseModel):
    student_id: str
    present: bool


class AttendanceMarkBulk(BaseModel):
    class_session_id: str
    marks: List[AttendanceMarkOne]


class AttendanceOut(BaseModel):
    id: str
    class_session_id: str
    student_id: str
    present: bool
    marked_at: datetime

    class Config:
        from_attributes = True


class AttendanceSummary(BaseModel):
    student_id: str
    total_classes: int
    present_count: int
    attendance_pct: float


class StudentAttendanceRow(BaseModel):
    student_id: str
    student_name: str
    total_classes: int
    present_count: int
    attendance_pct: float


class BatchAttendanceAnalytics(BaseModel):
    batch: str
    student_count: int
    batch_average_pct: float
    students: List[StudentAttendanceRow]  # sorted lowest attendance first - at-risk students surface immediately


# ---------- Uploads ----------
class UploadOut(BaseModel):
    url: str
    filename: str


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


class TestAttemptOut(BaseModel):
    id: str
    test_id: str
    test_title: str
    started_at: datetime
    submitted_at: Optional[datetime] = None
    score: Optional[float] = None
    is_flagged: bool
    flag_count: int


class TestOut(BaseModel):
    id: str
    title: str
    test_type: str
    duration_minutes: int
    topic: Optional[str] = None

    class Config:
        from_attributes = True


class QuestionStat(BaseModel):
    question_id: str
    text: str
    attempts: int
    correct_count: int
    correct_pct: float
    is_weak: bool  # true if correct_pct falls below the weak-question threshold


class TestAnalytics(BaseModel):
    test_id: str
    title: str
    attempt_count: int  # submitted attempts only
    average_score: float
    average_score_pct: float
    weak_question_count: int
    questions: List[QuestionStat]  # sorted worst-performing first


class FlagEvent(BaseModel):
    """Sent by the Android app the instant it detects a screen-lock break / app switch."""
    attempt_id: str
    event_type: str  # "app_switch", "screen_off", "split_screen_attempt"
    timestamp: datetime


# ---------- Institute (institute-admin dashboard) ----------
class InstituteOut(BaseModel):
    id: str
    name: str
    owner_phone: str
    plan: str
    created_at: datetime

    class Config:
        from_attributes = True


class InstituteUpdate(BaseModel):
    """Only the institute name is editable here - plan is a billing concern, not
    something the owner self-serves from this dashboard (yet)."""
    name: str


class TeacherCreate(BaseModel):
    name: str
    phone: str
    password: str  # initial password the owner sets for this teacher to log in with
    is_owner: bool = False


class TeacherOut(BaseModel):
    id: str
    name: str
    phone: str
    is_owner: bool

    class Config:
        from_attributes = True


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
