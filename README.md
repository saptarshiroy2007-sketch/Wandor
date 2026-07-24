# Wandor — Skeleton

MVP for solo teachers / 2-3 person coaching centres: scheduling + notifications,
fee tracking, and two test modes (auto-MCQ, locked-document).

## Structure

```
backend/               FastAPI + Postgres
  app/
    models.py          Institute, Teacher, Student, ClassSession, Test, FeeRecord, etc.
    schemas.py          Pydantic request/response shapes
    auth.py             JWT + password hashing
    routers/
      auth.py           phone+password login
      classes.py        schedule/cancel -> fans out WhatsApp/SMS to the batch
      tests.py           create+take MCQ or locked-document tests, anti-cheat flag endpoint
      payments.py        Razorpay order creation + webhook (signature-verified)
    services/
      notify.py          WhatsApp Cloud API primary, Twilio SMS fallback
      mcq_gen.py          stub — wire up an LLM call here for real generation

android/                Kotlin skeleton
  .../test/LockedTestActivity.kt   the actual "locks the screen" feature (Lock Task Mode)
  .../api/ApiClient.kt             Retrofit client hitting the backend
```

## Key architecture calls (and why)

- **Institute-scoped multi-tenancy**: every table hangs off `institute_id`. This is
  the whole SaaS model — one deployment, many independent coaching centres, zero
  data leakage between them if you're disciplined about filtering every query by it.
- **Phone-first auth, not email**: your users are teachers who may not check email
  regularly. Phone + password (or later, OTP) matches how WhatsApp/UPI already works
  for this demographic.
- **WhatsApp primary, SMS fallback**: WhatsApp Cloud API is free-ish for
  session messages but requires pre-approved templates outside a 24h window
  (that's why `notify()` takes a `template_name`). Twilio SMS as the safety net
  when a number isn't on WhatsApp or delivery fails.
- **Two-tier anti-cheat**: v1 uses Android's plain Lock Task Mode (screen pinning) —
  works with zero extra setup, catches app-switches via `onUserLeaveHint()`/`onPause()`,
  flags rather than auto-fails (teacher makes the final call — false positives happen).
  v2 upgrade path noted in code: device-owner/MDM provisioning makes the lock
  genuinely unbreakable, but that requires the institute to enroll the tablet/phone,
  which is a bigger ask — don't build it until a paying customer needs it.
- **Razorpay over Stripe**: UPI support. Non-negotiable for this market.

## Not built yet (intentionally, for you to prioritize)

- Student-facing auth (attempts currently take a raw `student_id` — fine for MVP,
  needs a real login before launch)
- File upload endpoint for test documents (assumes you already have a URL from S3/GCS)
- Attendance tracking (you mentioned it in the pitch but not the feature breakdown —
  flag if you want a model+router for it)
- Actual LLM wiring in `mcq_gen.py`
- Alembic migrations (right now `Base.metadata.create_all` on startup — fine for dev,
  swap to Alembic before you have real user data you can't afford to nuke)

## Running it

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your keys
uvicorn app.main:app --reload
```
