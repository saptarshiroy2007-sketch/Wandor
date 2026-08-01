from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret: str
    jwt_algorithm: str = "HS256"
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

    fee_reminder_enabled: bool = True
    fee_reminder_days_before: int = 3  # send a reminder once a fee's due_date is within this many days
    fee_reminder_hour: int = 9  # server-local hour (0-23) the daily job fires

    anthropic_api_key: str = ""  # used for real MCQ generation - falls back to placeholder stub if empty

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
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
