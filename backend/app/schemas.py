import re
from datetime import datetime, timezone
from typing import Annotated, Optional, List
from pydantic import (
    AfterValidator, BaseModel, Field, PlainSerializer, StringConstraints, field_validator, model_validator,
)

from .batch_utils import normalize_batch


# ---------- Shared field types ----------
# Datetimes are stored as NAIVE UTC (see models.py). Two rules keep that consistent end to end:
#  - INPUT: an aware datetime (the web app always sends "...Z") is converted to UTC and made
#    naive, so SQLite (which would otherwise just drop the offset) and Postgres agree.
#  - OUTPUT: instants are serialised with a trailing "Z". A bare "2026-10-27T10:30:00" is parsed by
#    browsers as LOCAL time, which shifted every class by the UTC offset (5.5h in India).
def _to_naive_utc(v: datetime) -> datetime:
    if v.tzinfo is not None:
        v = v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


def _ser_utc(v: Optional[datetime]) -> Optional[str]:
    if v is None:
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcIn = Annotated[datetime, AfterValidator(_to_naive_utc)]
UtcOut = Annotated[datetime, PlainSerializer(_ser_utc, return_type=str, when_used="json")]


def normalize_phone(v: str) -> str:
    """Digits only; drops a +91 / 91 / leading-0 prefix so '+91 98765-43210', '09876543210' and
    '9876543210' are the same login. Raises ValueError on something that can't be a phone number."""
    digits = re.sub(r"\D", "", v or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not 7 <= len(digits) <= 15:
        raise ValueError("Enter a valid phone number")
    return digits


Phone = Annotated[str, AfterValidator(normalize_phone)]
NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
SubjectStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PinStr = Annotated[str, StringConstraints(min_length=4, max_length=128)]


# ---------- Auth ----------
class TeacherLogin(BaseModel):
    phone: Phone
    password: str


class AdminLogin(BaseModel):
    phone: Phone
    password: str


class AdminExtendGrace(BaseModel):
    until: UtcIn
    note: Optional[str] = Field(default=None, max_length=300)


class AdminBan(BaseModel):
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason_len(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 300:
            raise ValueError("reason must be 1-300 characters")
        return v


class AdminMoney(BaseModel):
    base_paise: int
    gst_paise: int


class AdminRevenue(BaseModel):
    total: AdminMoney
    week: AdminMoney
    month: AdminMoney


class AdminStats(BaseModel):
    paying_accounts: int
    total_users: int
    users_gained_week: int
    revenue: AdminRevenue


class AdminAccount(BaseModel):
    subscription_id: str
    kind: str  # "institute" | "teacher"
    name: str
    phone: str
    plan: str
    status: str
    is_paying: bool
    access_state: str
    access_reason: Optional[str] = None
    current_period_end: Optional[UtcOut] = None
    ban_at: Optional[UtcOut] = None
    admin_banned: bool
    admin_ban_reason: Optional[str] = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _profile_completion_pct(*optional_fields: str | None) -> float:
    """Shared by every role's profile response - percentage of the OPTIONAL "My
    Profile" fields (bio, photo, education, email - whichever apply to that role)
    that are actually filled in. Required fields (name, phone) aren't counted since
    they're never empty to begin with; counting them would make every account start
    at a misleadingly high percentage instead of reflecting genuine profile effort."""
    if not optional_fields:
        return 0.0
    filled = sum(1 for f in optional_fields if f)
    return round((filled / len(optional_fields)) * 100, 0)


class TeacherProfile(BaseModel):
    id: str
    name: str
    phone: str
    institute_id: Optional[str] = None
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    education: Optional[str] = None
    email: Optional[str] = None
    profile_completion_pct: float = 0.0


class TeacherProfileUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    education: Optional[str] = None
    email: Optional[str] = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str

    def model_post_init(self, __context: object) -> None:
        if len(self.new_password) < 8:
            raise ValueError("New password must be at least 8 characters")


class PasswordResetRole:
    """Not a pydantic model - just the three roles password reset supports.
    Parent PIN reset isn't included: a parent's PIN is already reset by their
    child's teacher (POST /students/{id}/set-parent-pin), which is simpler and
    doesn't need its own OTP flow since a teacher's already an authenticated actor."""
    TEACHER = "teacher"
    STUDENT = "student"
    INSTITUTE_ADMIN = "institute_admin"


class PasswordResetRequest(BaseModel):
    role: str  # "teacher" / "student" / "institute_admin"
    phone: Phone
    institute_id: Optional[str] = None  # only meaningful for role="student" - phone
    # isn't globally unique for students, same disambiguation StudentLogin already uses


class PasswordResetConfirm(BaseModel):
    role: str
    phone: Phone
    institute_id: Optional[str] = None
    code: str
    new_password: str

    def model_post_init(self, __context: object) -> None:
        if len(self.new_password) < 8:
            raise ValueError("New password must be at least 8 characters")


class SignupPending(BaseModel):
    """Response for teacher-signup/institute-signup while phone verification is still
    outstanding - deliberately NOT a Token, so a self-signup can't skip verification
    just by reading the response shape. See PostSignupVerify below for what actually
    unlocks a Token."""
    phone: str
    message: str = "Verification code sent. Confirm it to activate your account."


class PostSignupVerify(BaseModel):
    phone: Phone
    code: str


class StudentLogin(BaseModel):
    phone: Phone
    password: str
    institute_id: Optional[str] = None  # optional: scope login to a specific institute to avoid cross-tenant collision when two institutes share a student phone
    student_id: Optional[str] = None  # set after the 409 'which account?' picker (see routers/auth.py)


class ParentLogin(BaseModel):
    """Parent logs in as the parent of one specific child, not with their own
    account - avoids inventing a separate multi-child parent identity/table for now.
    A parent with two kids at the institute just logs in twice with each child's phone."""
    student_phone: Phone
    pin: str
    institute_id: Optional[str] = None  # optional: same cross-tenant scoping as StudentLogin
    student_id: Optional[str] = None  # set after the 409 'which account?' picker (see routers/auth.py)


class InstituteLogin(BaseModel):
    """Institute-admin login is owner_phone + Institute.hashed_password - a separate
    credential from any Teacher row, not the teacher login with extra permissions."""
    phone: Phone
    password: str


# ---------- Signup ----------
# Deliberately no StudentSignup - students never self-register. A student's login is
# always created for them, either by a teacher (POST /students) or an institute admin
# (POST /institute/students).
class TeacherSignup(BaseModel):
    """Self-service signup for an INDEPENDENT teacher only - there's no institute_id
    field here on purpose. A teacher can't self-attach to an institute at signup;
    that binding only ever happens the other direction, when an institute admin adds
    them via POST /institute/teachers. A teacher who signs up here and later gets
    added to an institute by an admin needs the reconciliation step in
    TeacherJoinInstitute below - see POST /auth/teacher/join-institute."""
    name: NameStr
    phone: Phone
    password: str


class InstituteSignup(BaseModel):
    """Self-service institute signup - creates the Institute row AND activates its
    login password in one step, replacing the old manual DB-insert +
    scripts/set_institute_password.py bootstrap flow."""
    name: NameStr
    owner_phone: Phone
    password: str


# ---------- Batches ----------
class BatchCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _normalize(cls, v):
        normalized = normalize_batch(v)
        if not normalized:
            raise ValueError("name is required")
        if len(normalized) > 100:
            raise ValueError("name is too long (max 100 characters)")
        return normalized


class BatchRename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _normalize(cls, v):
        normalized = normalize_batch(v)
        if not normalized:
            raise ValueError("name is required")
        if len(normalized) > 100:
            raise ValueError("name is too long (max 100 characters)")
        return normalized


class BatchOut(BaseModel):
    id: str
    name: str

    class Config:
        from_attributes = True


# ---------- Students ----------
class StudentCreate(BaseModel):
    name: NameStr
    phone: Phone
    parent_phone: Optional[Phone] = None
    batch_id: Optional[str] = None  # references an existing Batch - create one first via POST /batches
    password: PinStr  # PIN the teacher sets for the student to log in with (student can change later)


class StudentOut(BaseModel):
    id: str
    name: str
    phone: str
    parent_phone: Optional[str] = None
    batch_id: Optional[str] = None
    batch_name: Optional[str] = None  # denormalized for display - avoids a second lookup per row
    has_login: bool  # true if hashed_password is set - lets the frontend show "activate login" vs not
    has_parent_login: bool = False  # true if parent_pin_hash is set
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    email: Optional[str] = None
    profile_completion_pct: Optional[float] = None  # only populated on the student's
    # own self-view (GET /students/me) - left None on a teacher's roster listing,
    # since a teacher looking at 30 students doesn't need a completion bar per row

    class Config:
        from_attributes = True


class StudentProfileUpdate(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    email: Optional[str] = None


class SetStudentPassword(BaseModel):
    password: PinStr


class SetParentPin(BaseModel):
    pin: PinStr


class StudentBulkImportRow(BaseModel):
    name: str
    phone: str
    parent_phone: Optional[str] = None
    batch: Optional[str] = None  # a NAME, not an id - CSV rows are hand-typed, so the
    # bulk-import endpoint resolves this to an existing Batch (or creates one) by name,
    # same normalize-and-match-case-insensitively behavior the old string batch column
    # used to have, just funneled through get_or_create instead of a live string compare
    password: Optional[str] = None  # if blank, defaults to last 4 digits of phone

    @field_validator("batch")
    @classmethod
    def _normalize_batch(cls, v):
        return normalize_batch(v)


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
    marks: List[AttendanceMarkOne] = Field(min_length=1, max_length=1000)


class AttendanceOut(BaseModel):
    id: str
    class_session_id: str
    student_id: str
    present: bool
    marked_at: UtcOut

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
    batch_id: str
    batch_name: str
    student_count: int
    batch_average_pct: float
    students: List[StudentAttendanceRow]  # sorted lowest attendance first - at-risk students surface immediately


# ---------- Uploads ----------
class UploadOut(BaseModel):
    url: str
    filename: str


# ---------- Classes ----------
class _TimeRange(BaseModel):
    @model_validator(mode="after")
    def _end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("End time must be after the start time")
        return self


class ClassCreate(_TimeRange):
    batch_id: str  # references an existing Batch - create one first via POST /batches
    subject: SubjectStr
    start_time: UtcIn
    end_time: UtcIn


class ClassCancel(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class ClassReschedule(_TimeRange):
    start_time: UtcIn
    end_time: UtcIn
    reason: Optional[str] = Field(default=None, max_length=300)


class ClassOut(BaseModel):
    id: str
    batch_id: str
    batch_name: str
    subject: str
    start_time: UtcOut
    end_time: UtcOut
    status: str

    class Config:
        from_attributes = True


# ---------- Tests ----------
_Q = StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
_OPT = StringConstraints(strip_whitespace=True, min_length=1, max_length=500)


class QuestionIn(BaseModel):
    """One MCQ question as authored by the teacher. Validated server-side:
    correct_option must be one of a/b/c/d."""
    text: Annotated[str, _Q]
    option_a: Annotated[str, _OPT]
    option_b: Annotated[str, _OPT]
    option_c: Annotated[str, _OPT]
    option_d: Annotated[str, _OPT]
    correct_option: str  # "a" / "b" / "c" / "d"


class TestCreateAuto(BaseModel):
    """Teacher-authored MCQ test — the teacher writes every question directly.
    LLM auto-generation was removed; this now accepts the questions payload instead
    of topic/num_questions (see follow-up session in HANDOFF.md)."""
    title: NameStr
    duration_minutes: int = Field(default=30, ge=1, le=600)
    batch_id: Optional[str] = None  # None = visible to all students in the institute/roster; set to restrict to one batch
    questions: List[QuestionIn] = Field(min_length=1, max_length=200)


class TestCreateDocument(BaseModel):
    title: NameStr
    document_url: str
    duration_minutes: int = Field(default=30, ge=1, le=600)

    @field_validator("document_url")
    @classmethod
    def _safe_url(cls, v):
        v = v.strip()
        # Only our own upload path or an http(s) URL: a javascript:/data: URL would run in the
        # student's iframe.
        if not (v.startswith("/uploads/") or re.match(r"^https?://", v, re.I)):
            raise ValueError("document_url must be an uploaded file or an http(s) link")
        return v
    batch_id: Optional[str] = None  # None = visible to all students in the institute/roster; set to restrict to one batch


class AnswerSubmit(BaseModel):
    question_id: str
    chosen_option: str


class TestSubmit(BaseModel):
    answers: List[AnswerSubmit] = Field(max_length=500)


class TestAttemptOut(BaseModel):
    id: str
    test_id: str
    test_title: str
    started_at: UtcOut
    submitted_at: Optional[UtcOut] = None
    score: Optional[float] = None
    max_score: Optional[float] = None
    graded_at: Optional[UtcOut] = None  # for document_locked attempts: null means
    # "submitted, awaiting teacher grading" even though submitted_at is set.
    is_flagged: bool
    flag_count: int


class TestGradeSubmit(BaseModel):
    """Teacher publishing a grade for a document_locked attempt after marking it by hand."""
    score: float
    max_score: float


class TestOut(BaseModel):
    id: str
    title: str
    test_type: str
    duration_minutes: int
    batch_id: Optional[str] = None  # None = all-institute/roster-wide; set = batch-restricted
    batch_name: Optional[str] = None

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
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    email: Optional[str] = None
    profile_completion_pct: float = 0.0

    class Config:
        from_attributes = True


class InstituteUpdate(BaseModel):
    """Name plus the new profile fields - plan is still a billing concern, not
    something the owner self-serves from this dashboard (yet)."""
    name: str
    bio: Optional[str] = None
    email: Optional[str] = None


class TeacherCreate(BaseModel):
    name: NameStr
    phone: Phone
    password: str  # initial password the owner sets for this teacher to log in with
    is_owner: bool = False
    batch_ids: List[str] = []  # ignored if is_owner=True (owners aren't batch-scoped) -
    # must reference existing Batch rows, create them first via POST /batches


class TeacherJoinInstitute(BaseModel):
    """Lets an independent teacher (Teacher.institute_id is None) attach their
    existing account to an institute themselves, instead of an institute admin's
    POST /institute/teachers hitting a dead-end 400 on the phone-uniqueness
    constraint when the phone already belongs to an independent teacher's account.
    Reuses the institute's own login credential as the 'invite code' rather than
    building a separate invite-code system (that's a bigger planned feature, not
    needed for this reconciliation) - the teacher proves the institute authorized
    this by supplying the institute's own login phone + password. Consent lives
    with the teacher (they're the one authenticated), not with whoever happens to
    know the teacher's phone number."""
    institute_owner_phone: Phone
    institute_password: str


class TeacherOut(BaseModel):
    id: str
    name: str
    phone: str
    is_owner: bool
    batches: List[BatchOut] = []  # id+name pairs, not bare strings - the frontend
    # needs the id for the batch-assignment picker, not just a label to display

    class Config:
        from_attributes = True


class BatchAssignmentSet(BaseModel):
    """Full replacement list - PUT semantics, not additive. Send every batch this
    teacher should be assigned to, not just new ones."""
    batch_ids: List[str]


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
    # Omit to pay everything still owed. A smaller amount is only accepted if the teacher
    # allowed part-payments on this fee (FeeRecord.allow_partial).
    amount: Optional[float] = Field(default=None, gt=0, le=10_000_000)


class PaymentOut(BaseModel):
    """One received payment on a fee (pending/abandoned orders are never exposed)."""
    id: str
    amount: float
    refunded_amount: float = 0.0
    status: str  # "paid" | "partially_refunded" | "refunded"
    mode: str  # "online" | "manual"
    paid_by: Optional[str] = None  # "student" | "parent" | "teacher" | None (older record)
    paid_at: Optional[UtcOut] = None
    receipt_no: str


class ReceiptOut(BaseModel):
    receipt_no: str
    issued_to: str  # the student's name
    issued_by: str  # the institute / teacher who received the money
    fee_description: Optional[str] = None
    fee_total: float
    amount: float
    refunded_amount: float = 0.0
    status: str
    mode: str
    paid_by: Optional[str] = None
    paid_at: Optional[UtcOut] = None
    razorpay_payment_id: Optional[str] = None  # online payments only
    fee_balance: float  # still owed on the fee right now


class ManualPaymentRequest(BaseModel):
    """Body for POST /payments/fees/{id}/mark-paid. Leave amount out to record the full balance."""
    amount: Optional[float] = Field(default=None, gt=0, le=10_000_000)


class FeeRecordDetail(BaseModel):
    """Fee row with the human-readable bits the UI actually needs (the older
    FeeRecordOut only carried a student_id, which is a UUID nobody wants to read)."""
    id: str
    student_id: str
    student_name: str
    batch_name: Optional[str] = None
    amount_due: float
    amount_paid: float
    is_paid: bool
    due_date: datetime
    paid_at: Optional[UtcOut] = None
    description: Optional[str] = None
    payment_mode: Optional[str] = None
    duplicate_payment: bool = False  # more money taken than owed - the extra needs refunding
    allow_partial: bool = False
    payments: List[PaymentOut] = []


class MyFee(BaseModel):
    id: str
    amount_due: float
    amount_paid: float
    is_paid: bool
    due_date: datetime
    paid_at: Optional[UtcOut] = None
    description: Optional[str] = None
    payment_mode: Optional[str] = None
    allow_partial: bool = False
    payments: List[PaymentOut] = []


class MyFeesOut(BaseModel):
    fees: List[MyFee]
    online_payment_available: bool  # False -> show "pay your teacher directly"


class FeeCreate(BaseModel):
    """Create the same fee for one/many students, or a whole batch."""
    student_ids: List[str] = []
    batch_id: Optional[str] = None
    amount: float = Field(gt=0, le=10_000_000)
    due_date: datetime
    description: Optional[str] = Field(default=None, max_length=200)
    allow_partial: bool = False  # let payers pay in instalments


class FeeCreateResult(BaseModel):
    created_count: int


class VerifyFeePayment(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class PayoutStatus(BaseModel):
    configured: bool
    online_fee_collection_allowed: bool  # plan permits it
    ready: bool  # configured AND allowed


# ---------- Billing (SaaS subscription) ----------
class PlanOut(BaseModel):
    key: str
    label: str
    price_monthly: int
    price_yearly: int
    max_students: Optional[int] = None
    max_teachers: Optional[int] = None
    online_fee_collection: bool
    fee_reminders: bool = False
    monthly_available: bool
    yearly_available: bool
    # price_monthly / price_yearly above are BASE prices in rupees, EXCLUDING GST. GST is added on
    # top; these give the exact paise so the UI never does float maths on money.
    gst_rate_percent: float = 0
    gst_monthly_paise: int = 0
    total_monthly_paise: int = 0
    gst_yearly_paise: int = 0
    total_yearly_paise: int = 0


class BillingStatus(BaseModel):
    plan: str  # effective plan right now
    plan_label: str
    status: str  # free / trialing / active / past_due / cancelled / expired
    billing_cycle: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = False
    scheduled_plan: Optional[str] = None
    scheduled_cycle: Optional[str] = None
    students_used: int
    students_limit: Optional[int] = None
    teachers_used: int
    teachers_limit: Optional[int] = None
    online_fee_collection: bool
    fee_reminders: bool = False
    can_manage: bool
    owner_kind: str  # "institute" or "teacher"
    # What happened to the NEXT renewal's price after an "upgrade now" in the current period:
    # "scheduled" (renews at the new plan's price), "reauthorise" (the old subscription ends at
    # period end - the owner must subscribe again to continue), "failed" (renews at the OLD price;
    # an operator has been alerted), or None (no upgrade in this period).
    upgrade_renewal: Optional[str] = None
    # Account access lifecycle (services/access.py): "active" | "grace" | "banned"; reason is
    # "payment" / "admin" / None; ban_at is when a lapsed account will be locked (None if not lapsed).
    access_state: str = "active"
    access_reason: Optional[str] = None
    ban_at: Optional[UtcOut] = None


class InvoiceOut(BaseModel):
    """A subscription invoice as the Billing page shows it. Money is integer paise, and
    base_paise + gst_paise == total_paise always (enforced by the database)."""
    id: str
    invoice_number: str
    kind: str  # "subscription" (a renewal/first charge) or "proration" (an upgrade-now)
    plan: str
    plan_label: str
    billing_cycle: Optional[str] = None
    description: Optional[str] = None
    base_paise: int
    gst_rate_percent: float
    gst_paise: int
    total_paise: int
    currency: str
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    issued_at: datetime


class SubscribeRequest(BaseModel):
    plan: str
    cycle: str  # monthly / yearly


class SubscribeResponse(BaseModel):
    subscription_id: str
    key_id: str
    plan: str
    cycle: str
    name: str
    contact: str


class SellerOut(BaseModel):
    """Who the invoices are issued by (from env). Empty strings = not configured yet."""
    legal_name: str = ""
    gstin: str = ""
    address: str = ""


class UpgradeRequest(BaseModel):
    plan: str  # the higher plan to move to now; the billing cycle stays as it is


class UpgradeQuote(BaseModel):
    """What "upgrade now" costs. All money is integer paise. The prorated difference is computed
    on the BASE price and GST is added on top: total_paise = base_paise + gst_paise."""
    from_plan: str
    from_plan_label: str
    to_plan: str
    to_plan_label: str
    cycle: str
    period_start: datetime
    period_end: datetime  # when the current period ends / the next renewal happens
    remaining_days: float
    credit_base_paise: int  # unused part of the current plan, for the rest of the period
    charge_base_paise: int  # the new plan, for the rest of the period
    base_paise: int         # charge - credit: what is billed now, excluding GST
    gst_rate_percent: float
    gst_paise: int
    total_paise: int


class UpgradeOrder(UpgradeQuote):
    """A quote plus what the browser needs to open Razorpay Checkout for it (one-off order)."""
    order_id: str
    key_id: str
    name: str
    contact: str


class VerifyUpgrade(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class VerifySubscription(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str
