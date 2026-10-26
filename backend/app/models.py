import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime, ForeignKey, Text, Enum, Float, UniqueConstraint,
    CheckConstraint,
)
from sqlalchemy import false as sa_false
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
    phone_verified = Column(Boolean, nullable=False, default=True)  # False only for a
    # self-signup (POST /auth/institute-signup) that hasn't completed OTP verification
    # yet - see /auth/institute-signup/verify. Defaults True at the Python/ORM level
    # so nothing else that creates an Institute row needs to think about this; the
    # signup endpoint explicitly overrides it to False. Migration backfills every
    # pre-existing row to True so this never locks out an account that existed
    # before phone verification was added.
    created_at = Column(DateTime, default=datetime.utcnow)
    bio = Column(Text, nullable=True)  # "My Profile" fields - see migration 0012
    photo_url = Column(String, nullable=True)
    email = Column(String, nullable=True)  # profile/contact only - login stays phone-first, this is NOT a credential
    razorpay_account_id = Column(String, nullable=True)  # Razorpay Route linked account (acc_xxx)
    # that student fee payments for this institute are transferred to - see
    # migration 0013 and scripts/set_payout_account.py. Null = online fee collection
    # not set up yet (teachers can still record cash/UPI payments manually).

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
    phone_verified = Column(Boolean, nullable=False, default=True)  # False only for a
    # self-signup (POST /auth/teacher-signup) that hasn't completed OTP verification
    # yet - see /auth/teacher-signup/verify. A teacher added by an institute admin
    # (POST /institute/teachers) is created with the default True, since an already-
    # authenticated admin vouching for the phone number is a different trust model
    # than an anonymous signup form typing in whatever number it wants.
    bio = Column(Text, nullable=True)  # "My Profile" fields - see migration 0012
    photo_url = Column(String, nullable=True)
    education = Column(String, nullable=True)  # e.g. "B.Sc Physics, M.Ed" - free text, not a structured field
    email = Column(String, nullable=True)  # profile/contact only - login stays phone-first, this is NOT a credential
    razorpay_account_id = Column(String, nullable=True)  # Route linked account for an
    # INDEPENDENT teacher's student fees (institute_id is None). Ignored for
    # institute-affiliated teachers - their students pay the institute's account.
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)  # NULL for rows that
    # pre-date migration 0019: they count toward totals but never toward "gained this week".

    institute = relationship("Institute", back_populates="teachers")
    batch_assignments = relationship("TeacherBatchAssignment", back_populates="teacher", cascade="all, delete-orphan")


class Batch(Base):
    """A real, teacher-editable entity - replaces the old free-text batch STRING that
    used to live independently on Student/Test/ClassSession/TeacherBatchAssignment,
    where a typo'd or differently-cased spelling on any one of those silently created
    a mismatch (batch_utils.py's old normalize_batch()/batch_matches() workaround is
    gone now - a plain batch_id equality check replaces all of that). One Batch row
    is the single canonical name for e.g. "Class 10A" within its owner scope; every
    other table just points at its id, so renaming a batch here updates it
    everywhere at once instead of needing a find-and-replace across 4 tables.

    Same owner-scope shape as Student/Test/ClassSession - see app/scoping.py's
    owner_scope(), which works with this model unchanged: institute_id for a batch
    shared institute-wide (any teacher on the team can use it), teacher_id for an
    independent teacher's own private batch."""
    __tablename__ = "batches"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"), nullable=True)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TeacherBatchAssignment(Base):
    """Which batch(es) a non-owner, institute-affiliated teacher may add students to.
    Independent teachers (Teacher.institute_id is None) and institute owners are never
    scoped by this table - they can add students to any batch freely. This table only
    matters for a teacher who (a) belongs to an institute and (b) is not the owner."""
    __tablename__ = "teacher_batch_assignments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=False, index=True)
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batches.id"), nullable=False)

    teacher = relationship("Teacher", back_populates="batch_assignments")
    batch = relationship("Batch")

    __table_args__ = (
        UniqueConstraint("teacher_id", "batch_id", name="uq_teacher_batch_assignment"),
    )


class Student(Base):
    __tablename__ = "students"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=True)  # only
    # meaningful when institute_id is NULL (an independent teacher's student) - see
    # app/scoping.py. Null for institute-affiliated students (shared institute-wide
    # by institute_id instead) and for students an institute admin added directly.
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)  # WhatsApp notifications go here
    parent_phone = Column(String, nullable=True)  # a LOT of Indian coaching centres notify parents, not just students
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batches.id"), nullable=True)  # None = no batch assigned yet
    batch = relationship("Batch")
    hashed_password = Column(String, nullable=True)  # set when teacher creates the student (default PIN); null = student login not yet activated
    parent_pin_hash = Column(String, nullable=True)  # separate PIN for the read-only parent view - null = parent login not activated for this child
    bio = Column(Text, nullable=True)  # "My Profile" fields - see migration 0012
    photo_url = Column(String, nullable=True)
    email = Column(String, nullable=True)  # profile/contact only - login stays phone-first, this is NOT a credential
    created_at = Column(DateTime, nullable=True, default=datetime.utcnow)  # NULL for rows that
    # pre-date migration 0019 (counted in totals, never in "gained this week")

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
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batches.id"), nullable=False)
    batch = relationship("Batch")
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
    description = Column(String, nullable=True)  # e.g. "March tuition"
    payment_mode = Column(String, nullable=True)  # "online" (Razorpay) or "manual" (teacher marked it paid: cash/UPI/etc.)
    duplicate_payment_id = Column(String, nullable=True)  # a SECOND, different payment arrived for an already-paid fee (e.g. cash
    # recorded while the student's online order was still open) - money taken twice, needs a refund. See services/fee_ledger.capture.
    allow_partial = Column(Boolean, nullable=False, default=False)  # payers may pay this fee in instalments (the teacher can always record a part-payment by hand)
    created_at = Column(DateTime, default=datetime.utcnow)

    student = relationship("Student", back_populates="fee_records")
    # The money ledger for this fee. amount_paid / is_paid above are a cache of it,
    # recomputed by services/fee_ledger.py - never set them by hand.
    payments = relationship(
        "FeePayment", back_populates="fee_record", cascade="all, delete-orphan",
        order_by="FeePayment.created_at", lazy="selectin",
    )


class FeePayment(Base):
    """One payment (or payment attempt) against a fee - the ledger behind FeeRecord.

    status 'pending' = a Razorpay order was created but not (yet) paid; it costs nothing
    and counts for nothing. 'paid' = money received (online, captured; or recorded by hand
    by the teacher). Refunds don't change the status - they accumulate in refunded_paise,
    and what a payment is worth is amount_paise - refunded_paise.

    Amounts are integer paise so sums are exact; FeeRecord keeps rupee floats for the UI.
    """
    __tablename__ = "fee_payments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    fee_record_id = Column(UUID(as_uuid=False), ForeignKey("fee_records.id"), nullable=False, index=True)
    amount_paise = Column(Integer, nullable=False)
    refunded_paise = Column(Integer, nullable=False, default=0)
    mode = Column(String, nullable=False)  # "online" (Razorpay) or "manual" (teacher recorded cash/UPI/etc.)
    status = Column(String, nullable=False, default="pending")  # "pending" | "paid"
    razorpay_order_id = Column(String, nullable=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True)
    paid_by = Column(String, nullable=True)  # who started it: "student" | "parent" | "teacher" (None = unknown/older record)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)

    fee_record = relationship("FeeRecord", back_populates="payments")


class Subscription(Base):
    """A SaaS subscription - what an institute or independent teacher pays US.
    Exactly one owner: institute_id (an institute pays for its whole team) OR teacher_id
    (an independent teacher, who has no Institute row). One row per owner, updated in
    place; app/services/subscriptions.py's effective_plan() is the only thing that
    decides what plan the owner is actually entitled to right now - never read `plan`
    directly for gating.

    status: trialing / active / past_due / cancelled / expired (Razorpay's own statuses
    are mapped onto these - see services/subscriptions.py). No row at all = free plan.
    """
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"), nullable=True)
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=True)
    plan = Column(String, nullable=False, default="free")  # free / basic / pro
    billing_cycle = Column(String, nullable=True)  # monthly / yearly; null for trials + free
    status = Column(String, nullable=False, default="active")
    razorpay_subscription_id = Column(String, nullable=True, unique=True)
    current_period_end = Column(DateTime, nullable=True)  # trial end, or end of the paid period
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    scheduled_plan = Column(String, nullable=True)  # plan-change queued for the next cycle
    scheduled_cycle = Column(String, nullable=True)
    grace_until = Column(DateTime, nullable=True)  # end of the limited-access grace window (see settings.limited_grace_days)
    admin_banned = Column(Boolean, nullable=False, default=False, server_default=sa_false())  # set by a platform admin
    admin_ban_reason = Column(String, nullable=True)
    admin_banned_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("(institute_id IS NULL) <> (teacher_id IS NULL)", name="ck_subscription_one_owner"),
        UniqueConstraint("institute_id", name="uq_subscription_institute"),
        UniqueConstraint("teacher_id", name="uq_subscription_teacher"),
    )


class Invoice(Base):
    """A tax invoice for one charge on a SaaS subscription - what the platform billed an
    institute / independent teacher. (Student fee receipts are a different thing: FeePayment.)

    Money is integer paise, and base + GST = total is enforced by the database itself, so an
    invoice can never disagree with itself. GST is added ON TOP of the base price (owner
    decision); gst_rate_bps is the rate that applied when the invoice was issued, so later rate
    changes never rewrite history. Invoices are append-only - a correction is a new invoice,
    never an edit.

    razorpay_payment_id is unique: it is what makes issuing idempotent when Razorpay redelivers
    a webhook or the browser and webhook race. `kind` lets later phases add other invoice types
    (e.g. a prorated upgrade) without a schema change. Numbers come from services/invoices.py.
    """
    __tablename__ = "invoices"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    invoice_number = Column(String, nullable=False, unique=True)
    subscription_id = Column(UUID(as_uuid=False), ForeignKey("subscriptions.id"), nullable=False, index=True)
    kind = Column(String, nullable=False, default="subscription")
    plan = Column(String, nullable=False)  # plan this charge was for (basic / pro)
    billing_cycle = Column(String, nullable=True)  # monthly / yearly
    description = Column(String, nullable=True)
    base_paise = Column(Integer, nullable=False)
    gst_rate_bps = Column(Integer, nullable=False)
    gst_paise = Column(Integer, nullable=False)
    total_paise = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    razorpay_payment_id = Column(String, nullable=True, unique=True)
    period_start = Column(DateTime, nullable=True)
    period_end = Column(DateTime, nullable=True)
    issued_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        CheckConstraint("total_paise = base_paise + gst_paise", name="ck_invoice_total"),
        CheckConstraint("base_paise >= 0 AND gst_paise >= 0", name="ck_invoice_non_negative"),
    )


class InvoiceCounter(Base):
    """Last invoice sequence number handed out per financial year (one row per year).
    Locked while a number is allocated so numbers are consecutive with no gaps and no
    duplicates, which Indian GST invoice rules expect."""
    __tablename__ = "invoice_counters"

    fy = Column(String, primary_key=True)  # e.g. "2627" = April 2026 - March 2027
    last_seq = Column(Integer, nullable=False, default=0)



class PlanUpgrade(Base):
    """One "upgrade now" attempt: the customer pays the prorated difference for the rest of the
    CURRENT billing period through a one-off Razorpay Order (not through the subscription, so it
    works for UPI Autopay subscriptions, which Razorpay will not let us edit), and moves to the
    higher plan immediately.

    A row is created when the order is (status "pending"), and is applied exactly once - by the
    browser's verify call or by the payment webhook, whichever lands first (status "applied").
    "refund_needed" means money was taken but the upgrade could not be applied (the period
    renewed first, or an earlier upgrade already covered it); `note` says why and an operator
    must refund the payment by hand. While an applied upgrade's period is still running,
    services/subscriptions.py keeps the upgraded plan even though Razorpay still reports the old
    plan_id - see held_plan(). Amounts are integer paise; the invoice is a kind="proration" row.

    renewal: what happened to the NEXT renewal's price - "scheduled" (Razorpay accepted the plan
    change for the next cycle), "reauthorise" (Razorpay refused, e.g. a UPI subscription: the old
    subscription is cancelled at period end and the customer must subscribe again to continue),
    "failed" (neither worked - it will renew at the old price; see the logs), or null.
    """
    __tablename__ = "plan_upgrades"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    subscription_id = Column(UUID(as_uuid=False), ForeignKey("subscriptions.id"), nullable=False, index=True)
    razorpay_order_id = Column(String, nullable=False, unique=True)
    razorpay_payment_id = Column(String, nullable=True, unique=True)
    from_plan = Column(String, nullable=False)
    to_plan = Column(String, nullable=False)
    billing_cycle = Column(String, nullable=False)
    base_paise = Column(Integer, nullable=False)    # prorated, excluding GST
    gst_paise = Column(Integer, nullable=False)
    total_paise = Column(Integer, nullable=False)   # what the Razorpay Order asks for
    period_start = Column(DateTime, nullable=True)  # the billing period being prorated
    period_end = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending / applied / refund_needed
    renewal = Column(String, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    applied_at = Column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("total_paise = base_paise + gst_paise", name="ck_plan_upgrade_total"),
        CheckConstraint("base_paise >= 0 AND gst_paise >= 0", name="ck_plan_upgrade_non_negative"),
    )

class WebhookEvent(Base):
    """Razorpay redelivers webhooks (retries, and at-least-once delivery), so every
    event id we've processed is recorded here and duplicates are acknowledged without
    being re-applied."""
    __tablename__ = "webhook_events"

    event_id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow)


class TestType(str, enum.Enum):
    mcq_auto = "mcq_auto"       # auto-generated MCQ test
    document_locked = "document_locked"  # PDF/image opened in locked/kiosk mode


class Test(Base):
    __tablename__ = "tests"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    institute_id = Column(UUID(as_uuid=False), ForeignKey("institutes.id"))
    teacher_id = Column(UUID(as_uuid=False), ForeignKey("teachers.id"), nullable=True)  # only
    # meaningful when institute_id is NULL (an independent teacher's test) - see
    # app/scoping.py. Same pattern as Student.teacher_id.
    title = Column(String, nullable=False)
    test_type = Column(Enum(TestType), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    document_url = Column(String, nullable=True)  # for document_locked type - PDF/image in S3/GCS
    batch_id = Column(UUID(as_uuid=False), ForeignKey("batches.id"), nullable=True)  # None = all students in institute/teacher's roster see this; set = only that batch sees it
    batch = relationship("Batch")

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
    max_score = Column(Float, nullable=True)  # total possible marks. For mcq_auto this equals
    # len(questions), set automatically on submit. For document_locked there's no Question
    # count to derive it from, so it's set by the teacher at grading time alongside score.
    graded_at = Column(DateTime, nullable=True)  # when a teacher published a grade for a
    # document_locked attempt. mcq_auto attempts are auto-graded on submit, so this stays
    # null for them - it exists specifically to distinguish "not yet graded" (None) from
    # "graded with a score of 0" for document_locked attempts, where score used to be
    # force-set to 0 on submit before any human had actually looked at the answer sheet.
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


class OtpCode(Base):
    """A one-time password reset code sent over WhatsApp/SMS. Purpose-built for
    password reset only right now (not signup verification - accounts are still
    created with no phone/email verification step, a separate planned feature).

    code_hash stores the OTP through the same hash_password() used for real account
    passwords - never store the raw 6-digit code. role + phone (+ institute_id for
    student/parent, where phone isn't globally unique - see student_login's existing
    disambiguation pattern in auth.py) identify which account this OTP authorizes a
    reset for, without needing a foreign key into three different tables."""
    __tablename__ = "otp_codes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    role = Column(String, nullable=False)  # "teacher" / "student" / "institute_admin"
    phone = Column(String, nullable=False, index=True)
    institute_id = Column(UUID(as_uuid=False), nullable=True)  # disambiguates a
    # student/parent phone that isn't globally unique - optional, same as student_login
    code_hash = Column(String, nullable=False)
    purpose = Column(String, nullable=False, default="password_reset")
    attempts = Column(Integer, default=0)  # wrong-code guesses against this specific OTP
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)  # set once successfully used - an
    # OTP is single-use, this is the flag that enforces that
    created_at = Column(DateTime, default=datetime.utcnow)


class PlatformAdmin(Base):
    """A platform operator (us) - separate from every Teacher/Institute login. Phone-first like the
    rest of the app; created out of band, never through signup."""
    __tablename__ = "platform_admins"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    phone = Column(String, nullable=False, unique=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AdminAuditLog(Base):
    """Append-only record of what a platform admin did to a subscription (ban, unban, grace, ...)."""
    __tablename__ = "admin_audit_log"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    admin_id = Column(UUID(as_uuid=False), ForeignKey("platform_admins.id"), nullable=False, index=True)
    action = Column(String, nullable=False)
    subscription_id = Column(UUID(as_uuid=False), ForeignKey("subscriptions.id"), nullable=False, index=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
