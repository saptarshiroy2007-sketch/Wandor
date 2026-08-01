"""
One-off CLI to set (or reset) an institute-admin login password.

There's no institute self-signup flow yet - institutes are created directly in the DB
(or by a future super-admin panel), so this script is how an owner's login gets
activated for the first time. Same idea as a teacher running set-password for a
student, just with nobody above the institute level to click a button yet.

Usage (from backend/, with your venv/deps active):
    python -m scripts.set_institute_password --phone 9876543210 --password "some-password"
"""
import argparse

from app.database import SessionLocal
from app.models import Institute
from app.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone", required=True, help="Institute.owner_phone")
    parser.add_argument("--password", required=True, help="New plaintext password to hash and set")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        institute = db.query(Institute).filter(Institute.owner_phone == args.phone).first()
        if not institute:
            print(f"No institute found with owner_phone={args.phone!r}")
            return
        institute.hashed_password = hash_password(args.password)
        db.commit()
        print(f"Password set for institute {institute.name!r} (id={institute.id})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
