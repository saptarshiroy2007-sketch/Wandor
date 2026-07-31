import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Text, Enum, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID

from .database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Institute(Base):
    """A coaching centre / individual teacher's 'org'. Everything is scoped to this."""
    __tablename__ = "institutes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    owner_phone = Column(String, nullable=False, unique=True)  # login is phone-first, not email
    hashed_password = Column(String, nullable=True)  # institute-admin login, separate from any Teacher row - null = not yet activated (see backend/scripts/set_institute_password.py to bootstrap)
    plan = Column(String, default="free")  # free / basic / pro - your SaaS tiers
    created_at = Column(DateTime, default=datetime.utcnow)

    teachers = relationship("Teacher", back_populates="institute")
    students = relationship("Student", back_populates="institute")
    classes = relationship("ClassSession", back_populates="institute")


class Teacher(Base):
    __tablename__ = "teachers"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    is_owner = Column(Boolean, default=False)  # owner vs added-teacher (2-3 person team)

    institute = relationship("Institute", back_populates="teachers")


class Student(Base):
    __tablename__ = "students"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)  # WhatsApp notifications go here
    parent_phone = Column(String, nullable=True)  # a LOT of Indian coaching centres notify parents, not just students
    batch = Column(String, nullable=True)  # e.g. "Class 10 - Batch A"
    hashed_password = Column(String, nullable=True)  # set when teacher creates the student (default PIN); null = student login not yet activated
    parent_pin_hash = Column(String, nullable=True)  # separate PIN for the read-only parent view - null = parent login not activated for this child

    institute = relationship("Institute", back_populates="students")
    fee_records = relationship("FeeRecord", back_populates="student")
    attendance_records = relationship("AttendanceRecord", back_populates="student")


class ClassStatus(str, enum.Enum):
    scheduled = "scheduled"
    cancelled = "cancelled"
    completed = "completed"


class ClassSession(Base):
    """A single scheduled class instance. Cancelling this fires notifications."""
    __tablename__ = "class_sessions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"))
    batch = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(Enum(ClassStatus), default=ClassStatus.scheduled)
    cancel_reason = Column(String, nullable=True)

    institute = relationship("Institute", back_populates="classes")


class FeeRecord(Base):
    """Payment / fee tracker ledger entry."""
    __tablename__ = "fee_records"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id"))
    amount_due = Column(Float, nullable=False)
    amount_paid = Column(Float, default=0.0)
    due_date = Column(DateTime, nullable=False)
    razorpay_order_id = Column(String, nullable=True)
    razorpay_payment_id = Column(String, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    is_paid = Column(Boolean, default=False)
    last_reminder_sent_at = Column(DateTime, nullable=True)  # dedupe: the daily fee-reminder job sends at most once per calendar day per fee record

    student = relationship("Student", back_populates="fee_records")


class TestType(str, enum.Enum):
    mcq_auto = "mcq_auto"       # auto-generated MCQ test
    document_locked = "document_locked"  # PDF/image opened in locked/kiosk mode


class Test(Base):
    __tablename__ = "tests"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    title = Column(String, nullable=False)
    test_type = Column(Enum(TestType), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    document_url = Column(String, nullable=True)  # for document_locked type - PDF/image in S3/GCS
    topic = Column(String, nullable=True)  # for mcq_auto - what to generate questions on
    num_questions = Column(Integer, default=10)  # for mcq_auto

    questions = relationship("Question", back_populates="test")


class Question(Base):
    __tablename__ = "questions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    test_id = Column(UUID(as_uuid=False), ForeignKey("tests.id"))
    text = Column(Text, nullable=False)
    option_a = Column(String)
    option_b = Column(String)
    option_c = Column(String)
    option_d = Column(String)
    correct_option = Column(String)  # "a" / "b" / "c" / "d"

    test = relationship("Test", back_populates="questions")


class TestAttempt(Base):
    """One student's attempt at a test. This is where the anti-cheat flag lives."""
    __tablename__ = "test_attempts"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    test_id = Column(UUID(as_uuid=False), ForeignKey("tests.id"))
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id"))
    started_at = Column(DateTime, default=datetime.utcnow)
    submitted_at = Column(DateTime, nullable=True)
    score = Column(Float, nullable=True)
    is_flagged = Column(Boolean, default=False)  # set True if app-switch detected
    flag_count = Column(Integer, default=0)  # how many times they left the app
    answers = Column(Text, nullable=True)  # JSON blob of {question_id: chosen_option}


class AttendanceRecord(Base):
    """One student's attendance mark for one class session. Unique per (class_session, student)."""
    __tablename__ = "attendance_records"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    class_session_id = Column(UUID(as_uuid=False), ForeignKey("class_sessions.id"))
    student_id = Column(UUID(as_uuid=False), ForeignKey("students.id"))
    present = Column(Boolean, default=False)
    marked_at = Column(DateTime, default=datetime.utcnow)
    marked_by_teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=True)

    student = relationship("Student", back_populates="attendance_records")


class NotificationLog(Base):
    """Audit trail - useful for debugging Twilio/WhatsApp delivery + billing your own SaaS usage."""
    __tablename__ = "notification_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    recipient_phone = Column(String, nullable=False)
    channel = Column(String)  # "whatsapp" or "sms"
    message = Column(Text)
    status = Column(String)  # "sent" / "failed"
    sent_at = Column(DateTime, default=datetime.utcnow)
