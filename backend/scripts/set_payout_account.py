"""
Operator CLI: link a Razorpay Route "linked account" to an institute or an independent
teacher, so their students' fee payments settle to that account.

Deliberately NOT a self-serve API endpoint: whoever can set this controls where fee
money is paid out, so it's an operator action until a proper KYC onboarding flow
exists. Steps:
  1. In the Razorpay dashboard (Route -> Linked Accounts) create + KYC the institute's
     or teacher's linked account. You get an id like acc_XXXXXXXXXXXXXX.
  2. Run this script with that id. It first checks the account exists on your Razorpay
     account, so a typo can't route fee money into the void.

Usage (from backend/, with your venv/deps active):
    python -m scripts.set_payout_account --institute-phone 9876543210 --account-id acc_XXXX
    python -m scripts.set_payout_account --teacher-phone 9876543210 --account-id acc_XXXX
    python -m scripts.set_payout_account --institute-phone 9876543210 --clear

(--teacher-phone is for INDEPENDENT teachers only; a teacher who belongs to an institute
is covered by the institute's account.)
"""
import argparse

import httpx

from app.database import SessionLocal, settings
from app.models import Institute, Teacher


def _verify_account(account_id: str) -> str:
    """Returns the account's Razorpay status, or raises RuntimeError."""
    if not (settings.razorpay_key_id and settings.razorpay_key_secret):
        raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET aren't set - can't verify the account")
    r = httpx.get(
        f"https://api.razorpay.com/v2/accounts/{account_id}",
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret), timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Razorpay says {r.status_code} for {account_id}: {r.text[:200]}")
    return r.json().get("status", "unknown")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--institute-phone", help="Institute.owner_phone")
    who.add_argument("--teacher-phone", help="Phone of an INDEPENDENT teacher")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--account-id", help="Razorpay Route linked account id (acc_...)")
    what.add_argument("--clear", action="store_true", help="Unlink the payout account")
    parser.add_argument("--skip-verify", action="store_true", help="Don't check the account with Razorpay first")
    args = parser.parse_args()

    if args.account_id and not args.account_id.startswith("acc_"):
        raise SystemExit("Account ids look like acc_XXXXXXXX - that doesn't")

    db = SessionLocal()
    try:
        if args.institute_phone:
            row = db.query(Institute).filter(Institute.owner_phone == args.institute_phone).first()
            label = "institute"
            if not row:
                raise SystemExit(f"No institute with owner_phone={args.institute_phone!r}")
        else:
            row = db.query(Teacher).filter(Teacher.phone == args.teacher_phone).first()
            label = "teacher"
            if not row:
                raise SystemExit(f"No teacher with phone={args.teacher_phone!r}")
            if row.institute_id is not None:
                raise SystemExit("That teacher belongs to an institute - set the payout account on the institute instead")

        if args.clear:
            row.razorpay_account_id = None
            db.commit()
            print(f"Cleared payout account for {label} {row.name!r}")
            return

        if not args.skip_verify:
            try:
                status = _verify_account(args.account_id)
            except RuntimeError as e:
                raise SystemExit(f"Not saved: {e}")
            print(f"Razorpay reports {args.account_id} as: {status}")
            if status != "activated":
                print("WARNING: the account isn't 'activated' yet - transfers to it will fail until KYC completes.")

        row.razorpay_account_id = args.account_id
        db.commit()
        print(f"Payout account set for {label} {row.name!r}: {args.account_id}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
