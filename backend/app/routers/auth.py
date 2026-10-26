from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import secrets

from ..database import get_db, settings
from ..models import Teacher, Student, Institute, OtpCode
from ..schemas import (
    TeacherLogin, StudentLogin, ParentLogin, InstituteLogin, Token,
    TeacherSignup, InstituteSignup, PasswordChange, TeacherProfile, TeacherJoinInstitute,
    PasswordResetRequest, PasswordResetConfirm, SignupPending, PostSignupVerify,
    TeacherProfileUpdate, _profile_completion_pct,
)
from ..auth import verify_password, hash_password, create_access_token, get_current_teacher, _decode
from ..services.notify import notify
from ..services import subscriptions as subs
from ..ratelimit import rate_limit
from ..models import Batch

router = APIRouter(prefix="/auth", tags=["auth"])

# Generic bearer scheme for the role-agnostic change-password endpoint.
# Does NOT enforce a specific tokenUrl so any role's token is accepted.
_any_bearer = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


_login_limit = [Depends(rate_limit("login", "rate_limit_login_per_min"))]


@router.post("/login", response_model=Token, dependencies=_login_limit)
def login(payload: TeacherLogin, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if not teacher or not verify_password(payload.password, teacher.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    if not teacher.phone_verified:
        # Credentials are right, but this account came from self-signup and never
        # finished OTP verification - see teacher_signup below. Sending a fresh code
        # here (rather than making them go back to the signup form) covers the
        # "signed up, got distracted, came back days later to log in" case smoothly.
        _send_otp(db, "teacher_signup", teacher.phone, "signup_verification")
        raise HTTPException(
            status_code=403,
            detail="Phone not verified yet. We've sent a new code - verify it to activate your account.",
        )
    token = create_access_token(teacher.id, role="teacher")
    return Token(access_token=token)


@router.post("/teacher-signup", response_model=SignupPending)
def teacher_signup(payload: TeacherSignup, db: Session = Depends(get_db)):
    """Self-service signup for an INDEPENDENT teacher (institute_id stays None).
    Students never get an equivalent endpoint - they're only ever created by a
    teacher or institute admin, never self-registering.

    Creates the row immediately but with phone_verified=False and NO token - the
    account exists but can't log in (see login()'s check below) until
    POST /auth/teacher-signup/verify confirms the OTP sent here. If an unverified
    row already exists for this phone (they started signup, got distracted, came
    back), this resends a fresh code against the SAME row instead of 400ing - only
    a phone that's already fully verified blocks a repeat signup."""
    existing = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if existing and existing.phone_verified:
        raise HTTPException(status_code=400, detail="A teacher with this phone already exists")

    if existing:
        teacher = existing
        teacher.name = payload.name
        teacher.hashed_password = hash_password(payload.password)
    else:
        teacher = Teacher(
            institute_id=None,
            name=payload.name,
            phone=payload.phone,
            hashed_password=hash_password(payload.password),
            is_owner=False,
            phone_verified=False,
        )
        db.add(teacher)
    db.commit()

    _send_otp(db, "teacher_signup", payload.phone, "signup_verification")
    return SignupPending(phone=payload.phone)


@router.post("/teacher-signup/verify", response_model=Token)
def teacher_signup_verify(payload: PostSignupVerify, db: Session = Depends(get_db)):
    teacher = db.query(Teacher).filter(Teacher.phone == payload.phone).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="No pending signup for this phone")
    if teacher.phone_verified:
        raise HTTPException(status_code=400, detail="This phone is already verified - just log in")

    _consume_otp(db, "teacher_signup", payload.phone, payload.code, "signup_verification")
    teacher.phone_verified = True
    # Independent teachers pay for themselves, so they get their own trial. (A teacher
    # verifying with an institute_id would be covered by the institute - not possible
    # via self-signup today, but owner_for_teacher handles it correctly either way.)
    subs.start_trial(db, subs.owner_for_teacher(teacher))
    db.commit()

    token = create_access_token(teacher.id, role="teacher")
    return Token(access_token=token)


@router.post("/institute-signup", response_model=SignupPending)
def institute_signup(payload: InstituteSignup, db: Session = Depends(get_db)):
    """Self-service institute signup - creates the Institute row and activates its
    login password in one request, replacing the old manual DB-insert +
    scripts/set_institute_password.py bootstrap. That script still works as a
    fallback/admin tool but is no longer the only way in.

    Same phone_verified gate as teacher_signup above - see that docstring for the
    resend-on-repeat-signup behavior, which works identically here."""
    existing = db.query(Institute).filter(Institute.owner_phone == payload.owner_phone).first()
    if existing and existing.phone_verified:
        raise HTTPException(status_code=400, detail="An institute with this phone already exists")

    if existing:
        institute = existing
        institute.name = payload.name
        institute.hashed_password = hash_password(payload.password)
    else:
        institute = Institute(
            name=payload.name,
            owner_phone=payload.owner_phone,
            hashed_password=hash_password(payload.password),
            phone_verified=False,
        )
        db.add(institute)
    db.commit()

    _send_otp(db, "institute_signup", payload.owner_phone, "signup_verification")
    return SignupPending(phone=payload.owner_phone)


@router.post("/institute-signup/verify", response_model=Token)
def institute_signup_verify(payload: PostSignupVerify, db: Session = Depends(get_db)):
    institute = db.query(Institute).filter(Institute.owner_phone == payload.phone).first()
    if not institute:
        raise HTTPException(status_code=404, detail="No pending signup for this phone")
    if institute.phone_verified:
        raise HTTPException(status_code=400, detail="This phone is already verified - just log in")

    _consume_otp(db, "institute_signup", payload.phone, payload.code, "signup_verification")
    institute.phone_verified = True
    subs.start_trial(db, subs.owner_for_institute(institute))
    db.commit()

    token = create_access_token(institute.id, role="institute_admin")
    return Token(access_token=token)


def _account_label(db: Session, s: Student) -> str:
    """Human label for the 'which account?' picker: who the student studies with, and the batch."""
    if s.institute_id:
        inst = db.query(Institute).filter(Institute.id == s.institute_id).first()
        who = inst.name if inst else "Institute"
    else:
        t = db.query(Teacher).filter(Teacher.id == s.teacher_id).first() if s.teacher_id else None
        who = t.name if t else "Teacher"
    batch = db.query(Batch.name).filter(Batch.id == s.batch_id).scalar() if s.batch_id else None
    return f"{who} - {batch}" if batch else who


def _resolve_student(db: Session, phone: str, secret: str, hash_attr: str,
                     institute_id: str | None, student_id: str | None) -> Student:
    """Student.phone is only unique per tenant, so one phone can match several students (a kid
    with two tutors). The old code took .first() and checked the secret against only that row:
    the second tutor's student could never log in, or - when two PINs happened to match - landed in
    the OTHER tenant's account. Now every matching row is checked; if exactly one accepts the
    secret that's the account, if several do the client gets a 409 + choices and retries with
    student_id. A wrong secret is always the same generic 401."""
    q = db.query(Student).filter(Student.phone == phone)
    if institute_id:
        q = q.filter(Student.institute_id == institute_id)
    if student_id:
        q = q.filter(Student.id == student_id)
    hits = [s for s in q.all()
            if getattr(s, hash_attr) and verify_password(secret, getattr(s, hash_attr))]
    if not hits:
        raise HTTPException(status_code=401, detail="Wrong phone number or password" if hash_attr == "hashed_password"
                            else "Wrong phone number or PIN")
    if len(hits) > 1:
        raise HTTPException(status_code=409, detail={
            "message": "More than one account uses this number and PIN. Pick yours.",
            "choices": [{"student_id": s.id, "label": _account_label(db, s)} for s in hits],
        })
    return hits[0]


@router.post("/student-login", response_model=Token, dependencies=_login_limit)
def student_login(payload: StudentLogin, db: Session = Depends(get_db)):
    """Students log in with phone + the PIN/password their teacher set when adding them
    (see POST /students). If a student was added before login existed and has no
    hashed_password yet, this correctly rejects until a teacher sets one via
    POST /students/{id}/set-password.

    Lenient cross-tenant fix: if institute_id is provided in the payload, the query is
    scoped to that institute so two students at two different institutes sharing a phone
    number don't collide. If institute_id is omitted, the old single-query behaviour
    applies (first DB match wins), which is fine for single-institute deployments."""
    student = _resolve_student(db, payload.phone, payload.password, "hashed_password",
                               payload.institute_id, payload.student_id)
    token = create_access_token(student.id, role="student")
    return Token(access_token=token)


@router.post("/parent-login", response_model=Token, dependencies=_login_limit)
def parent_login(payload: ParentLogin, db: Session = Depends(get_db)):
    """Parents log in with their child's phone + the parent PIN a teacher set via
    POST /students/{id}/set-parent-pin. Same not-yet-activated handling as student
    login: if parent_pin_hash is null, this correctly rejects until a teacher sets one.
    NOTE: student.phone is only unique within an institute (not globally) - provide
    institute_id in the payload to avoid cross-tenant collision (see student_login)."""
    student = _resolve_student(db, payload.student_phone, payload.pin, "parent_pin_hash",
                               payload.institute_id, payload.student_id)
    token = create_access_token(student.id, role="parent")
    return Token(access_token=token)


@router.post("/institute-login", response_model=Token, dependencies=_login_limit)
def institute_login(payload: InstituteLogin, db: Session = Depends(get_db)):
    """Institute-admin login (owner_phone + Institute.hashed_password) - a separate
    credential from any Teacher row. If hashed_password is null, the owner's login
    hasn't been activated yet - see backend/scripts/set_institute_password.py."""
    institute = db.query(Institute).filter(Institute.owner_phone == payload.phone).first()
    if not institute or not institute.hashed_password or not verify_password(payload.password, institute.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong phone number or password")
    if not institute.phone_verified:
        _send_otp(db, "institute_signup", institute.owner_phone, "signup_verification")
        raise HTTPException(
            status_code=403,
            detail="Phone not verified yet. We've sent a new code - verify it to activate your account.",
        )
    token = create_access_token(institute.id, role="institute_admin")
    return Token(access_token=token)


def _teacher_to_profile(teacher: Teacher) -> TeacherProfile:
    return TeacherProfile(
        id=teacher.id, name=teacher.name, phone=teacher.phone, institute_id=teacher.institute_id,
        bio=teacher.bio, photo_url=teacher.photo_url, education=teacher.education, email=teacher.email,
        profile_completion_pct=_profile_completion_pct(teacher.bio, teacher.photo_url, teacher.education, teacher.email),
    )


@router.get("/me", response_model=TeacherProfile)
def get_teacher_profile(teacher: Teacher = Depends(get_current_teacher)):
    """Return the authenticated teacher's own profile data, including the "My
    Profile" fields (bio/photo/education/email) and a completion percentage across
    them. Students/parents/institute-admins each have their own /me endpoints on
    their respective routers — this one is teacher-only (get_current_teacher
    enforces that)."""
    return _teacher_to_profile(teacher)


@router.patch("/me", response_model=TeacherProfile)
def update_teacher_profile(
    payload: TeacherProfileUpdate,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Updates whichever "My Profile" fields were sent - None values are left
    untouched, not cleared, since a partial edit (e.g. just adding a bio) shouldn't
    silently wipe fields the caller didn't mention. To actually clear a field, send
    an empty string, not omit it."""
    if payload.name is not None:
        teacher.name = payload.name
    if payload.bio is not None:
        teacher.bio = payload.bio
    if payload.education is not None:
        teacher.education = payload.education
    if payload.email is not None:
        teacher.email = payload.email
    db.commit()
    db.refresh(teacher)
    return _teacher_to_profile(teacher)


@router.post("/teacher/join-institute", response_model=TeacherProfile)
def join_institute(
    payload: TeacherJoinInstitute,
    db: Session = Depends(get_db),
    teacher: Teacher = Depends(get_current_teacher),
):
    """Reconciles the orphaned-account case: an independent teacher (see TeacherSignup)
    who later needs to join an institute. Teacher.phone is globally unique, so the
    institute admin's POST /institute/teachers can't just create a second row for the
    same phone - it 400s (see the friendlier error there). This is the other side of
    that: the teacher, from their own already-logged-in independent account, attaches
    themselves to an institute by proving they know its login credentials.

    Converts this SAME teacher row in place (institute_id gets set) rather than
    creating a new one, so nothing about the teacher's existing account - their id,
    password, phone - changes. Existing bearer tokens keep working since the token
    only encodes the teacher id and role, not institute_id (that's read fresh from
    the DB on every request)."""
    if teacher.institute_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Your account is already attached to an institute. Ask that institute's "
                   "admin to remove you first if you need to switch.",
        )

    institute = db.query(Institute).filter(Institute.owner_phone == payload.institute_owner_phone).first()
    if not institute or not institute.hashed_password or not verify_password(payload.institute_password, institute.hashed_password):
        raise HTTPException(status_code=401, detail="Wrong institute phone number or password")

    # Billing: after joining, the institute pays and this teacher's own subscription
    # would silently keep charging for nothing - so make them cancel it first. And the
    # teacher takes up a seat on the institute's plan.
    own_sub = subs.get_subscription(db, subs.owner_for_teacher(teacher))
    if own_sub and own_sub.razorpay_subscription_id and own_sub.status in ("active", "past_due") \
            and not own_sub.cancel_at_period_end:
        raise HTTPException(
            status_code=409,
            detail="Cancel your personal subscription in Billing before joining an institute - "
                   "the institute's plan will cover you instead.",
        )
    subs.assert_can_add_teacher(db, subs.owner_for_institute(institute))

    teacher.institute_id = institute.id
    teacher.is_owner = False  # joining an institute never grants ownership - only institute-signup does
    db.commit()
    db.refresh(teacher)

    return TeacherProfile(id=teacher.id, name=teacher.name, phone=teacher.phone, institute_id=teacher.institute_id)


@router.post("/change-password")
def change_password(
    payload: PasswordChange,
    token: str = Depends(_any_bearer),
    db: Session = Depends(get_db),
):
    """Self-service password change for teacher, student, and institute_admin.
    Parent tokens are rejected (parents don't have their own password — their PIN
    is set by a teacher via POST /students/{id}/set-parent-pin).

    The JWT is decoded directly here rather than using a role-specific dependency so
    a single endpoint handles all three writable role types without duplicating the
    route three times. The role claim in the token determines which DB model to update.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    jwt_payload = _decode(token)
    role = jwt_payload.get("role")
    sub = jwt_payload.get("sub")

    if role == "parent":
        raise HTTPException(status_code=403, detail="Parents do not have a self-managed password. Ask a teacher to update your PIN.")

    if role == "teacher":
        user = db.query(Teacher).filter(Teacher.id == sub).first()
    elif role == "student":
        user = db.query(Student).filter(Student.id == sub).first()
    elif role == "institute_admin":
        user = db.query(Institute).filter(Institute.id == sub).first()
    else:
        raise HTTPException(status_code=401, detail="Unrecognised role")

    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.hashed_password or not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}


# ---------- Shared OTP plumbing (password reset AND signup verification) ----------
OTP_TTL_MINUTES = 10
OTP_REQUEST_COOLDOWN_SECONDS = 60  # don't let someone spam-request codes for the same account
MAX_OTP_ATTEMPTS = 5  # wrong-code guesses before an OTP is burned and a fresh one is required

_OTP_MESSAGES = {
    "password_reset": "Your Wandor password reset code is {code}. It expires in {mins} minutes. Don't share this with anyone.",
    "signup_verification": "Your Wandor verification code is {code}. It expires in {mins} minutes. Don't share this with anyone.",
}


def _lookup_account(role: str, phone: str, institute_id: str | None, db: Session):
    """Same role -> model mapping as change_password's JWT-based lookup, but keyed by
    phone (pre-auth, since this is how a locked-out user gets back in, or a not-yet-
    verified signup gets confirmed) instead of a token's sub claim. For role="student",
    institute_id disambiguates - Student.phone isn't globally unique, same as
    StudentLogin/ParentLogin already handle. "teacher_signup"/"institute_signup" are
    just the password-reset roles under a different tag (see _send_otp) - map them
    to the same lookup as "teacher"/"institute_admin"."""
    if role in ("teacher", "teacher_signup"):
        return db.query(Teacher).filter(Teacher.phone == phone).first()
    if role in ("institute_admin", "institute_signup"):
        return db.query(Institute).filter(Institute.owner_phone == phone).first()
    if role == "student":
        q = db.query(Student).filter(Student.phone == phone)
        if institute_id:
            q = q.filter(Student.institute_id == institute_id)
        return q.first()
    return None


def _send_otp(db: Session, role: str, phone: str, purpose: str, institute_id: str | None = None) -> None:
    """Generates, hashes, stores, and sends a fresh OTP - shared by password-reset
    request and both signup-verify flows. Silently no-ops under the cooldown window
    (caller still returns its normal generic/pending response either way, so this
    never leaks whether a cooldown was hit)."""
    recent = db.query(OtpCode).filter(
        OtpCode.role == role, OtpCode.phone == phone, OtpCode.purpose == purpose,
        OtpCode.consumed_at.is_(None),
        OtpCode.created_at >= datetime.utcnow() - timedelta(seconds=OTP_REQUEST_COOLDOWN_SECONDS),
    ).first()
    if recent:
        return

    code = f"{secrets.randbelow(1_000_000):06d}"  # secrets, not random - this gates account access
    db.add(OtpCode(
        role=role, phone=phone, institute_id=institute_id, purpose=purpose,
        code_hash=hash_password(code),
        expires_at=datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES),
    ))
    db.commit()

    msg = _OTP_MESSAGES[purpose].format(code=code, mins=OTP_TTL_MINUTES)
    notify(phone, msg, f"{purpose}_otp")


def _consume_otp(db: Session, role: str, phone: str, code: str, purpose: str) -> None:
    """Verifies a code against the most recent unconsumed, unexpired OTP for this
    role+phone+purpose and marks it used. Raises HTTPException on any failure
    (nothing found/expired, too many attempts, wrong code) - callers just call this
    and then do whatever the successful side-effect is (change password, mark phone
    verified, etc)."""
    otp = db.query(OtpCode).filter(
        OtpCode.role == role, OtpCode.phone == phone, OtpCode.purpose == purpose,
        OtpCode.consumed_at.is_(None), OtpCode.expires_at >= datetime.utcnow(),
    ).order_by(OtpCode.created_at.desc()).first()

    if not otp:
        raise HTTPException(status_code=400, detail="Invalid or expired code. Request a new one.")

    if otp.attempts >= MAX_OTP_ATTEMPTS:
        otp.consumed_at = datetime.utcnow()  # burn it - no more guesses against this code
        db.commit()
        raise HTTPException(status_code=400, detail="Too many incorrect attempts. Request a new code.")

    if not verify_password(code, otp.code_hash):
        otp.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Incorrect code")

    otp.consumed_at = datetime.utcnow()
    db.commit()


@router.post("/password-reset/request")
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)):
    """Sends a 6-digit OTP over WhatsApp (SMS fallback, same as every other
    notification in this app - see services/notify.py) to reset a forgotten password.
    Always returns the same generic message regardless of whether the phone/role
    actually matches an account - this is deliberate, so this endpoint can't be used
    to probe which phone numbers have accounts (account enumeration)."""
    if payload.role not in ("teacher", "student", "institute_admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    generic_response = {"message": "If that account exists, an OTP has been sent."}
    account = _lookup_account(payload.role, payload.phone, payload.institute_id, db)
    if not account:
        return generic_response

    _send_otp(db, payload.role, payload.phone, "password_reset", payload.institute_id)
    return generic_response


@router.post("/password-reset/confirm", response_model=Token, dependencies=_login_limit)
def confirm_password_reset(payload: PasswordResetConfirm, db: Session = Depends(get_db)):
    """Verifies the OTP and, if valid, sets the new password AND logs the user in
    immediately (returns a real access token) - no reason to make someone who just
    proved account ownership go type their brand-new password into a login form too."""
    if payload.role not in ("teacher", "student", "institute_admin"):
        raise HTTPException(status_code=400, detail="Invalid role")

    _consume_otp(db, payload.role, payload.phone, payload.code, "password_reset")

    account = _lookup_account(payload.role, payload.phone, payload.institute_id, db)
    if not account:
        # Account was deleted between requesting and confirming the OTP - vanishingly
        # rare, but the OTP is already consumed by _consume_otp above either way.
        raise HTTPException(status_code=404, detail="Account not found")

    account.hashed_password = hash_password(payload.new_password)
    db.commit()

    token = create_access_token(account.id, role=payload.role)
    return Token(access_token=token)
