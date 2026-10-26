"""
Create a platform admin (or reset its password if the phone already exists).

Usage (from backend/):
    python -m scripts.create_platform_admin <phone> <password>
"""
import argparse

from app.database import SessionLocal
from app.models import PlatformAdmin
from app.auth import hash_password
from app.schemas import normalize_phone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phone")
    parser.add_argument("password")
    args = parser.parse_args()
    try:
        phone = normalize_phone(args.phone)
    except ValueError as e:
        raise SystemExit(f"Invalid phone number: {e}")

    db = SessionLocal()
    try:
        admin = db.query(PlatformAdmin).filter(PlatformAdmin.phone == phone).first()
        if admin:
            admin.hashed_password = hash_password(args.password)
            msg = f"Updated password for platform admin {phone}"
        else:
            db.add(PlatformAdmin(phone=phone, hashed_password=hash_password(args.password)))
            msg = f"Created platform admin {phone}"
        db.commit()
        print(msg)
    finally:
        db.close()


if __name__ == "__main__":
    main()
