# Wandor — Skeleton

MVP for solo teachers / 2-3 person coaching centres: scheduling + notifications,
fee tracking, and two test modes (auto-MCQ, locked-document).

## Architecture

**One React web app, wrapped by Capacitor for Android.** Not two separate apps.
The scheduling/payments/test-taking UI is 100% shared code — write it once, it
runs in a browser tab AND as the installed Android app. The only native code is
a single small plugin for the one thing that genuinely requires OS-level access:
the locked-test anti-cheat feature.

```
backend/               FastAPI + Postgres (unchanged from before)
  app/
    models.py, schemas.py, auth.py
    routers/            auth, classes, tests, payments
    services/           notify.py (WhatsApp+SMS), mcq_gen.py

webapp/                 React + Vite + Capacitor — this IS the mobile app once wrapped
  src/
    api/client.ts        talks to the FastAPI backend
    plugins/lockTask.ts   TS interface to the native plugin, no-ops gracefully on web
    pages/
      Login.tsx
      Dashboard.tsx        class list + cancel
      ScheduleClass.tsx
      TakeTest.tsx          MCQ form OR locked-document view depending on test type
      Payments.tsx          fee tracker table
  capacitor.config.ts

  android-plugin-src/    NOT yet inside an actual android/ folder - see setup below
    com/wandor/app/plugins/LockTaskPlugin.kt
```

## Why Capacitor instead of full native

- One codebase for web + mobile UI = way less to maintain for a small/solo team
- You already know Python (backend) and are learning Kotlin — Capacitor lets you
  use that Kotlin exactly where it's actually needed (the lock feature) instead
  of writing an entire parallel Android app
- Downside, to be upfront about it: Capacitor apps feel slightly less "native" than
  fully native ones, and you're trusting a webview for the UI. For this use case
  (forms, lists, a test-taking screen) that tradeoff is fine — this isn't a
  graphics-heavy app.

## Setting up the Android wrapper (do this once webapp/ has real content)

```bash
cd webapp
npm install
npm run build
npx cap add android          # generates the android/ folder from scratch
npx cap sync
```

Then:
1. Copy `android-plugin-src/com/wandor/app/plugins/LockTaskPlugin.kt` into
   `android/app/src/main/java/com/wandor/app/plugins/`
2. Register it in the generated `MainActivity.java` — see the comment block at
   the bottom of `LockTaskPlugin.kt` for the exact two-line override needed
   (`onUserLeaveHint()` isn't exposed to plugins by default, so the host
   Activity needs to forward it)
3. Open `android/` in Android Studio to build/run on a device or emulator

## Fixed in this pass (see HANDOFF.md for full detail)

- Student-facing auth — real JWT login via `POST /auth/student-login`, role-aware tokens
- Students router — was entirely missing; teachers now have `POST/GET/DELETE /students`
- File upload endpoint — `POST /uploads/test-document`, local disk by default, swappable to S3
- Attendance tracking — `AttendanceRecord` model + `/attendance/*` routes
- Real LLM wiring in `mcq_gen.py` — Anthropic call, falls back to placeholder stub if no API key
- Alembic migrations — `alembic/` scaffolded, initial schema hand-written (see HANDOFF.md for why)

## Still not built (unchanged priorities from before)

- Attendance-based dropout-risk flagging, fee-reminder scheduler, rank/percentile,
  adaptive difficulty — planned as deterministic rule-based engines, not LLM calls
- Multi-tenant white-label branding config
- (Parent login now exists: a parent signs in with the child's phone + parent PIN, sees fees/attendance/results and can pay fees. See HANDOFF.md.)
- Tier-2 device-owner/MDM lock (current lock is screen-pinning, exitable via a
  long-press gesture that gets logged — be upfront with institutes that this is
  "flags attempted cheating," not "physically impossible to cheat," unless you
  build the MDM tier later)

## Running the backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head    # applies migrations - do this instead of relying on create_all in prod
uvicorn app.main:app --reload
```

## Running the web app

```bash
cd webapp
npm install
npm run dev   # http://localhost:5173
```

## Billing and fee payments

Subscriptions (what institutes/teachers pay Wandor), online fee payment by students and parents
(Razorpay Route), part-payments, receipts, refund handling and fee notices are built. Status, setup
steps, open decisions and the remaining phases are in **HANDOFF.md -> "WHAT TO DO NEXT (billing)"**.
Backend tests (run from `backend/`): `python -m tests.test_billing_flow`, `python -m tests.test_migration_0015`, `python -m tests.test_migration_0016` and `python -m tests.test_migration_0017`.

Subscription prices in `backend/app/plans.py` are **base prices excluding GST**; GST (`GST_RATE_BPS`, 18% default) is added on top. Create each Razorpay Plan at base + GST - `GET /billing/plans` returns the exact paise to use.

Every successful subscription charge (Razorpay `subscription.charged` webhook) becomes a numbered tax invoice (`WND/2627/000001`); the account's billing manager lists them with `GET /billing/invoices` and opens one with `GET /billing/invoices/{id}`.

**Upgrade now (prorated).** An active paid subscription can move to a higher plan immediately and pay only for the rest of the current period: `POST /billing/upgrade/quote` (read-only price), `POST /billing/upgrade` (creates a one-off Razorpay Order), Checkout in the browser, then `POST /billing/upgrade/verify` (the payment webhook applies it too). Proration runs on the base price, GST is added on top, and the charge becomes a `kind="proration"` invoice. It uses an Order rather than Razorpay's subscription-update API, so it also works for UPI Autopay subscriptions. Only upgrades on the same billing cycle; downgrades and cycle changes stay on `POST /billing/change-plan` (effective at renewal). Rules and failure modes: `backend/app/services/upgrades.py` and HANDOFF.md, Phase 4.3.

**Billing UI (4.4).** The Billing page shows prices as base + GST, an "Upgrade now" panel (quote -> Checkout -> verify), a "subscribe again" card when an upgrade needs re-authorising, and an Invoices list with a printable page at `/billing/invoice/:id`. Set `SELLER_LEGAL_NAME`, `SELLER_GSTIN` and `SELLER_ADDRESS` in `backend/.env` so invoices carry the seller details.

**This copy ships without Razorpay credentials.** Online payment features are off until you add
`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (and plan ids) to `backend/.env`. Everything
else, including recording cash/UPI payments by hand, works without them. See HANDOFF.md.

## Platform admin

A founder-only panel at **`/admin-login`** (not linked from anywhere in the app) shows paying/total/gained numbers, revenue, and every account with controls to extend grace, ban and lift a ban. It also drives the account lifecycle: paid/trial period ends -> 3-day buffer -> 15 days of limited grace (no attendance marking, test creation, new test attempts or analytics) -> ban. A payment restores access; a manual ban is separate and is not lifted by payment. Details: HANDOFF.md, "platform admin + account lifecycle".

**Release checklist** (in this order; the founder script needs the tables from migration 0019)
1. Deploy the backend and webapp.
2. `cd backend && alembic upgrade head` (migration 0019 creates `platform_admins`, so this must come before step 3).
3. Create both founder logins: `cd backend && python -m scripts.create_platform_admin <phone> <password>` (run once per founder; re-running updates the password).
4. Set `ENFORCEMENT_START` in `backend/.env` to the release date (UTC, e.g. `2026-11-01`) and restart. Until it is set, nothing changes for any account.

**What happens at that date:** accounts already unpaid or on the free tier get a 3-day buffer from `ENFORCEMENT_START`, then 15 days of limited grace, and are banned 18 days after the release date unless they pay (or a founder extends their grace).

With `TRIAL_DAYS=0` a brand-new account has no trial (it gets a free/active row) and, once enforcement is on and `ENFORCEMENT_START` + 18 days has passed, is banned until it subscribes.
