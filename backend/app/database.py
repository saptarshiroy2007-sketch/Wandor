from datetime import date, datetime, timezone
from typing import Optional

from pydantic import field_validator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    display_timezone: str = "Asia/Kolkata"  # zone used when stored UTC times are written into WhatsApp/SMS text (see app/timeutil.py)
    test_max_attempts: int = 1  # submitted attempts allowed per student per test; 0 = unlimited
    test_submit_grace_seconds: int = 120  # slack past duration_minutes before a submit is rejected
    access_token_expire_minutes: int = 1440

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    whatsapp_phone_number_id: str = ""
    whatsapp_access_token: str = ""
    whatsapp_api_version: str = "v20.0"

    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""  # separate secret set in the Razorpay dashboard webhook config - NOT the same as razorpay_key_secret

    # ---- SaaS subscription billing (see app/plans.py + routers/billing.py) ----
    # Razorpay *Plan* ids (create each once in the Razorpay dashboard -> Subscriptions
    # -> Plans, with the matching amount/period from app/plans.py, then paste the
    # plan_xxx ids here). Blank = that plan/cycle can't be purchased yet.
    razorpay_plan_basic_monthly: str = ""
    razorpay_plan_basic_yearly: str = ""
    razorpay_plan_pro_monthly: str = ""
    razorpay_plan_pro_yearly: str = ""
    trial_days: int = 14  # new signups get this many days of Pro; 0 disables trials
    billing_grace_days: int = 3  # keep paid features this long after a failed renewal
    # GST on subscription prices, in basis points (1800 = 18%). Prices in app/plans.py are the
    # BASE price; GST is added on top (owner decision, Phase 4.0), so what a customer is charged -
    # and what the Razorpay Plan amount must be - is base + GST. See services/invoices.py.
    gst_rate_bps: int = 1800
    # Invoice numbers look like WND/2627/000001 (prefix / financial year / sequence). GST rules
    # cap an invoice number at 16 characters, so keep the prefix short (3-4 letters).
    invoice_prefix: str = "WND"
    # Seller details printed on every invoice (a valid GST tax invoice needs them). Shown by
    # GET /billing/seller; empty until the owner sets them in .env.
    seller_legal_name: str = ""
    seller_gstin: str = ""
    seller_address: str = ""

    # ---- Student fee collection via Razorpay Route ----
    # Cut the platform keeps from each student fee payment, in basis points (100 = 1%).
    # 0 = pass the full amount to the institute/teacher's linked account.
    fee_platform_commission_bps: int = 0

    # ---- Rate limiting (see app/ratelimit.py) ----
    rate_limit_enabled: bool = True  # kill switch
    rate_limit_payment_per_min: int = 10  # POST /payments/create-order, per student
    rate_limit_billing_per_min: int = 5  # POST /billing/subscribe + /billing/change-plan, per account
    rate_limit_login_per_min: int = 10  # POST /auth/*login + password-reset/confirm, per client IP (password guessing)
    rate_limit_verify_per_min: int = 20  # POST /payments/verify, /parents/verify, /billing/verify (HMAC check + a Razorpay fetch)

    fee_reminder_enabled: bool = True
    fee_reminder_days_before: int = 3  # send a reminder once a fee's due_date is within this many days
    fee_reminder_hour: int = 9  # server-local hour (0-23) the daily job fires
    # Meta template used for the daily reminder. The original `fee_reminder` template has NO
    # body variables, so WhatsApp users never saw the amount. To fix that, create a template
    # (suggested name `fee_reminder_v2`) with 4 variables, then set FEE_REMINDER_TEMPLATE to its
    # name and FEE_REMINDER_TEMPLATE_VARS=true. Passing variables to a template that has none is
    # rejected by Meta, so the default stays "old template, no variables" until you flip both.
    fee_reminder_template: str = "fee_reminder"
    fee_reminder_template_vars: bool = False

    # ---- Account access lifecycle (see services/subscriptions.py) ----
    # Date from which unpaid accounts are limited/blocked. Blank = the whole lifecycle is off.
    # ENFORCEMENT_START accepts an ISO date (2026-11-01 = midnight UTC) or datetime; stored as naive UTC.
    enforcement_start: Optional[datetime] = None
    limited_grace_days: int = 15  # days of limited access before an unpaid account is blocked

    @field_validator("enforcement_start", mode="before")
    @classmethod
    def _parse_enforcement_start(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            v = v.strip()
            v = datetime.fromisoformat(v[:-1] + "+00:00" if v[-1] in "Zz" else v)
        elif isinstance(v, date) and not isinstance(v, datetime):
            v = datetime(v.year, v.month, v.day)
        if isinstance(v, datetime) and v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v

    storage_backend: str = "local"  # "local" or "s3"
    upload_dir: str = "uploads"  # used when storage_backend == "local"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""  # set for Cloudflare R2/Backblaze B2, leave blank for real AWS S3
    s3_public_base_url: str = ""  # e.g. your CDN/custom domain in front of the bucket
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    # SQLite connections aren't thread-safe by default, but every FastAPI request
    # runs in a threadpool worker thread (same mechanism TestClient uses) - without
    # this, concurrent requests against a local SQLite dev db can corrupt reads in
    # ways that show up as bizarre unrelated-looking errors (found this the hard way
    # verifying the OTP feature: a clean, correctly-typed UUID column read back as a
    # `float` under TestClient, purely from cross-thread SQLite access - vanished
    # once this was added). No-op on Postgres, so this is safe for prod either way.
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
