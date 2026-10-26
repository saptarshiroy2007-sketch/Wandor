# Platform Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A two-founder admin panel (revenue and user counts, grace extension, manual ban/lift) plus the paid -> grace -> ban lifecycle it controls.

**Architecture:** Account access state (`active` / `grace` / `banned`) is derived in one new pure module, `services/access.py`, from the existing `Subscription` row plus two new fields (`grace_until`, `admin_banned`). Enforcement happens in the existing auth dependencies (ban) and in a small guard called by attendance, test and analytics routes (grace). The admin is a separate token role with its own `/admin/*` router and a separate React area.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic (Postgres 16 + SQLite), Pydantic v2, React 18 + Vite + axios, pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-platform-admin-design.md`

## Global Constraints

- Money is integer paise; revenue is `Invoice.base_paise` (GST reported separately, never counted as revenue).
- Timestamps stored naive UTC, serialised with a trailing `Z` via `UtcOut` (see `schemas.py`); input via `UtcIn`. Dashboard windows in Asia/Kolkata (`timeutil.py`).
- Full-features buffer after a period ends = `settings.billing_grace_days` (3). Limited-features grace = 15 days (`settings.limited_grace_days`).
- "This week" = last 7 days. "This month" = calendar month in Asia/Kolkata.
- Alembic must run on an empty Postgres and `alembic check` must show no drift. Current head is `0018`.
- Existing suites keep passing: `tests/test_billing_flow.py` (74) and `tests/test_fixes.py` (11), run from `backend/` with `RATE_LIMIT_ENABLED=true FEE_REMINDER_ENABLED=true python -m pytest tests -q`.
- Error `detail` stays a plain string (every page renders it as text). Account status travels in a response header `X-Account-Status`: `grace` is never sent as a header; locked responses send `banned_payment` or `banned_admin`.
- Founders cannot ban students, parents or teachers inside an institute. Manual ban targets only a paying account (an independent teacher or an institute owner).
- The git repo is not present in the sandbox copy; run commit steps only if the project is under git, otherwise skip them.

## Review Focus

1. `ENFORCEMENT_START` unset: nothing changes for any account (no grace, no ban). Must be the default so a deploy can never ban anyone by accident.
2. A renewal whose webhook arrives late (period ended less than 3 days ago) keeps full features, and a payment that arrives during grace or after a payment-ban returns the account to active with no founder action.
3. A manual ban is not lifted by payment, and a manually banned account cannot be extended.
4. `extend-grace` with a date in the past, earlier than the current ban date, or on an active account returns 400 and changes nothing.
5. Token isolation both ways: an admin token on any teacher/student/institute/billing endpoint is 401; teacher, student, parent and institute tokens on `/admin/*` are 401; `/admin/*` without a token is 401.

---

## File Structure

- Create `backend/app/services/access.py`: the lifecycle (pure function + DB wrapper + lock/grace guards).
- Create `backend/app/routers/admin.py`: admin login and all `/admin/*` endpoints.
- Create `backend/scripts/create_platform_admin.py`: CLI to add a founder login.
- Create `backend/alembic/versions/0019_platform_admin_and_access.py`.
- Modify `backend/app/models.py`, `database.py` (settings), `auth.py`, `schemas.py`, `main.py`, `services/subscriptions.py` (`plan_for_owner`), `routers/attendance.py`, `routers/tests.py`, `routers/billing.py` (status fields), `.env.example`.
- Create `backend/tests/test_access.py`, `tests/test_admin.py`, `tests/test_migration_0019.py`; modify `tests/test_migration_0017.py` (head assertion `"0018"` -> `"0019"`).
- Frontend (`webapp/src/`): modify `api/client.ts`, `main.tsx`, `components/Layout.tsx`; create `pages/AdminLogin.tsx`, `pages/AdminDashboard.tsx`, `pages/AccountLocked.tsx`, `components/AccessBanner.tsx`.

---

### Task 1: Schema, models and settings

**Files:**
- Create: `backend/alembic/versions/0019_platform_admin_and_access.py`, `backend/tests/test_migration_0019.py`
- Modify: `backend/app/models.py`, `backend/app/database.py`, `backend/tests/test_migration_0017.py`, `backend/.env.example`

**Interfaces:**
- Produces (models): `PlatformAdmin(id, phone unique, hashed_password, created_at)`; `AdminAuditLog(id, admin_id FK platform_admins, action str, subscription_id FK subscriptions, old_value str null, new_value str null, note str null, created_at)`; on `Subscription`: `grace_until DateTime null`, `admin_banned Boolean not null default False`, `admin_ban_reason String null`, `admin_banned_at DateTime null`; on `Teacher` and `Student`: `created_at DateTime null, default utcnow` (existing rows stay NULL, so they count toward totals but never toward "gained this week").
- Produces (settings): `enforcement_start: Optional[datetime] = None` (env `ENFORCEMENT_START`, ISO date or datetime, naive UTC), `limited_grace_days: int = 15`.

- [ ] **Step 1: Write the failing migration test** following the pattern in `tests/test_migration_0017.py`: upgrade a fresh SQLite DB to head and assert the new tables and columns exist and that head is `0019`. Also assert `alembic check` is clean.
- [ ] **Step 2: Run** `python -m pytest tests/test_migration_0019.py -q`. Expected: FAIL (revision missing).
- [ ] **Step 3: Add the models, settings and migration `0019`** (down_revision `0018`). Use `postgresql.UUID(as_uuid=False)` for ids and FKs like the rest of the schema, `server_default=sa.false()` on `admin_banned`.
- [ ] **Step 4: Update `.env.example`** with `ENFORCEMENT_START=` (blank, with a comment that blank disables the whole lifecycle) and `LIMITED_GRACE_DAYS=15`. Update the head assertion in `test_migration_0017.py`.
- [ ] **Step 5: Run** the new migration test, then `bash /tmp/claude-0/sbx/pg_alembic.sh` against Postgres. Expected: PASS and `Running upgrade 0018 -> 0019` with no error; `alembic check` clean on both.
- [ ] **Step 6: Commit** `feat: schema for platform admin and account access`.

### Task 2: Access state (the lifecycle)

**Files:**
- Create: `backend/app/services/access.py`, `backend/tests/test_access.py`
- Modify: `backend/app/services/subscriptions.py` (`plan_for_owner` only)

**Interfaces:**
- Consumes: `Subscription` (Task 1), `settings.enforcement_start`, `settings.billing_grace_days`, `settings.limited_grace_days`, `plans.PAID_PLAN_KEYS`, `plans.TRIAL_PLAN`.
- Produces:
  - `@dataclass(frozen=True) class Access: state: str  # "active" | "grace" | "banned"; reason: Optional[str]  # None | "payment" | "admin"; grace_starts_at: Optional[datetime]; ban_at: Optional[datetime]`
  - `access_for_subscription(sub: Optional[Subscription], now: Optional[datetime] = None) -> Access` (pure, no DB)
  - `access_for_owner(db: Session, owner: Owner, now: Optional[datetime] = None) -> Access`
  - `assert_not_locked(db: Session, owner: Owner, *, billing: bool = False) -> None` raises `HTTPException(403)` with header `X-Account-Status`. Payment-ban message: "This account is inactive because the plan wasn't renewed. Please contact your institute." For the payer (`billing=True` callers) payment-ban does not raise. Admin-ban always raises with header `banned_admin` and message "This account has been suspended. Please contact Wandor support."
  - `assert_full_access(db: Session, owner: Owner, what: str) -> None` raises 402 (plain string) "`{what}` is paused because your plan has lapsed. Renew in Billing to turn it back on." when state is `grace`.

- [ ] **Step 1: Write failing tests** in `tests/test_access.py`, table-driven over `access_for_subscription` with a fixed `now` and `enforcement_start` set via `settings` monkeypatch. Assert exactly these outcomes (E = `current_period_end`, R = `enforcement_start`):
  - `enforcement_start` None, any sub, even long lapsed: `active`.
  - paid `active`, E in the future: `active`.
  - paid, E = now - 2 days: `active` (buffer). E = now - 4 days: `grace`, `ban_at == E + 18 days`. E = now - 19 days: `banned`, reason `payment`.
  - expired trial (E long ago, R = now - 1 day): grace starts at `R + 3 days`, `ban_at == R + 18 days` (clock starts at release, not at E).
  - free-tier or no sub row: treated as lapsed since R, same dates.
  - `grace_until` later than the computed ban date: `ban_at == grace_until`; earlier: ignored.
  - `admin_banned=True` overrides everything: `banned`, reason `admin`.
  - `cancelled` with E in the future: `active`; after E: follows the same path.
- [ ] **Step 2: Run** `python -m pytest tests/test_access.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `access_for_subscription` and `access_for_owner`** exactly per the cases above; the lapse base is `max(E or R, R)`, buffer end = base + `billing_grace_days`, computed ban = buffer end + `limited_grace_days`, effective ban = `max(computed, grace_until)`.
- [ ] **Step 4: Implement `assert_not_locked` and `assert_full_access`** as specified above.
- [ ] **Step 5: Change `plan_for_owner`** so that during `grace` it returns `sub.plan` if it is in `PAID_PLAN_KEYS` else `plans.TRIAL_PLAN` (grace turns off only attendance, tests and analytics, not online fee collection or reminders); otherwise unchanged. Leave `effective_plan` untouched.
- [ ] **Step 6: Add DB-level tests**: `access_for_owner` for an independent teacher and an institute; late-webhook case (Review Focus 2): create a paid sub with E = now - 1 hour, assert `active`; then simulate a payment by pushing E forward 30 days on a `grace` and on a `banned/payment` sub and assert `active`; assert a payment does not change an `admin_banned` sub.
- [ ] **Step 7: Run** the new tests and the full suite. Expected: all PASS (billing 74, fixes 11 unchanged).
- [ ] **Step 8: Commit** `feat: account access lifecycle (active/grace/banned)`.

### Task 3: Enforcement in the existing app

**Files:**
- Modify: `backend/app/auth.py`, `backend/app/main.py`, `backend/app/routers/attendance.py`, `backend/app/routers/tests.py`, `backend/app/routers/billing.py`, `backend/app/schemas.py`
- Test: `backend/tests/test_access.py`

**Interfaces:**
- Consumes: `assert_not_locked`, `assert_full_access`, `access_for_owner` (Task 2); `owner_for_teacher`, `owner_for_institute`, `owner_for_student`.
- Produces: `BillingStatus` gains `access_state: str`, `access_reason: Optional[str]`, `ban_at: Optional[UtcOut]` (exact names the frontend reads).

- [ ] **Step 1: Write failing tests** (extend `tests/test_access.py`): with `enforcement_start` set and an institute banned for payment — a teacher, a student and a parent token each get 403 on an ordinary endpoint with header `X-Account-Status: banned_payment`; the institute-admin token gets 403 on `/institute/me` but 200 on `/billing/me`; an independent teacher banned for payment gets 403 on `/students` but 200 on `/billing/me`. With `admin_banned`, every one of them including `/billing/me` is 403 with `banned_admin`. A student/parent token of an account in `grace` can still `GET` past attendance and results.
- [ ] **Step 2: Write failing tests for grace** on an account in `grace`: `POST /attendance/mark`, `POST /tests/mcq`, `POST /tests/document`, `POST /tests/{id}/start`, `GET /tests/{id}/analytics` and `GET /attendance/batch/{id}/analytics` return 402 with the "paused" string; `POST /tests/attempts/{id}/submit` for an attempt already open still succeeds; everything else (classes, students, fees) unaffected.
- [ ] **Step 3: Run** them. Expected: FAIL.
- [ ] **Step 4: Call `assert_not_locked`** at the end of `get_current_teacher`, `get_current_student`, `get_current_parent`, `get_current_institute_admin` (owner from the resolved row), and in `get_billing_actor` with `billing=True`.
- [ ] **Step 5: Add `assert_full_access`** at the top of the six routes named in Step 2 (owner from the teacher, or `owner_for_student` for `/start`; `what` is "Attendance", "Tests" or "Analytics").
- [ ] **Step 6: Add `expose_headers=["X-Account-Status"]`** to the CORS middleware in `main.py`; fill the three new `BillingStatus` fields in `routers/billing.py` from `access_for_owner`.
- [ ] **Step 7: Run** the full suite. Expected: PASS, including the 74 billing tests with `ENFORCEMENT_START` unset.
- [ ] **Step 8: Commit** `feat: enforce ban and grace limits`.

### Task 4: Admin identity

**Files:**
- Create: `backend/scripts/create_platform_admin.py`
- Modify: `backend/app/auth.py`, `backend/app/schemas.py`, `backend/app/routers/admin.py` (create with the login route only), `backend/app/main.py`
- Test: `backend/tests/test_admin.py`

**Interfaces:**
- Produces: `get_current_platform_admin(token, db) -> PlatformAdmin` (role claim `platform_admin`, own `OAuth2PasswordBearer(tokenUrl="/admin/login")`); `POST /admin/login` body `{phone, password}` -> `Token`, rate limited with the existing `login` bucket, 401 "Wrong phone number or password" otherwise; script usage `python -m scripts.create_platform_admin <phone> <password>` (idempotent: updates the password if the phone exists).

- [ ] **Step 1: Write failing tests**: valid login returns a token that `get_current_platform_admin` accepts; wrong password 401; Review Focus 5 both directions (admin token on `/students`, `/institute/me`, `/billing/me`, `/classes` is 401; teacher/student/parent/institute tokens on `/admin/stats` are 401; no token 401). Phone is normalised with the existing `Phone` type.
- [ ] **Step 2: Run** `python -m pytest tests/test_admin.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the dependency, login route, router registration and script.
- [ ] **Step 4: Run** the tests. Expected: PASS.
- [ ] **Step 5: Commit** `feat: platform admin login`.

### Task 5: Admin API (stats, accounts, extend, ban, lift)

**Files:**
- Modify: `backend/app/routers/admin.py`, `backend/app/schemas.py`
- Test: `backend/tests/test_admin.py`

**Interfaces:**
- Consumes: `get_current_platform_admin`, `access_for_subscription` (Task 2), `AdminAuditLog` (Task 1).
- Produces, all behind `get_current_platform_admin`:
  - `GET /admin/stats` -> `{paying_accounts: int, total_users: int, users_gained_week: int, revenue: {total, week, month}}` where each revenue entry is `{base_paise: int, gst_paise: int}`. `paying_accounts` = subscriptions with a paid plan and status in (`active`, `past_due`, `cancelled`) whose access state is `active` or `grace` (not trials, not banned). `total_users` = Teacher + Institute + Student + students with `parent_pin_hash` set. `users_gained_week` counts non-null `created_at` within 7 days on Teacher, Institute, Student (parents are not separately dated; a footnote on the tile says so).
  - `GET /admin/accounts?status=all|active|grace|banned|trial` -> list of `{subscription_id, kind: "institute"|"teacher", name, phone, plan, status, access_state, access_reason, current_period_end, ban_at, admin_banned, admin_ban_reason}`, newest first.
  - `POST /admin/accounts/{subscription_id}/extend-grace` body `{until: UtcIn, note?: str(<=300)}` -> the account row. 400 if the account is `active`, is `admin_banned`, or `until` is not after both now and the current `ban_at`. Sets `grace_until`.
  - `POST /admin/accounts/{subscription_id}/ban` body `{reason: str(1..300)}` and `POST /admin/accounts/{subscription_id}/lift-ban` -> the account row. Ban on an already banned-manual account and lift on a not-banned account are 400.
  - Every change writes an `AdminAuditLog` row (`action` in `extend_grace`, `ban`, `lift_ban`; old/new values as strings; note/reason in `note`).

- [ ] **Step 1: Write failing tests** with seeded subscriptions (trial, paid active, grace, payment-banned, admin-banned) and invoices of known `base_paise`/`gst_paise` issued today, 3 days ago, 40 days ago: assert each stats number exactly; month boundary uses Asia/Kolkata (an invoice at 18:31 UTC on the last day of the previous month counts in the new month); accounts list filters; extend/ban/lift happy paths change state as `access_for_owner` reports; Review Focus 3 and 4 (every invalid case 400 and no DB change, no audit row); each success writes exactly one audit row.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement the endpoints** (response schemas in `schemas.py`, datetimes via `UtcOut`).
- [ ] **Step 4: Run** `python -m pytest tests/test_admin.py -q` then the full suite on SQLite, then on Postgres with `TEST_DATABASE_URL`. Expected: PASS on both.
- [ ] **Step 5: Commit** `feat: admin dashboard API`.

### Task 6: Frontend

**Files:**
- Modify: `webapp/src/api/client.ts`, `webapp/src/main.tsx`, `webapp/src/components/Layout.tsx`
- Create: `webapp/src/pages/AdminLogin.tsx`, `webapp/src/pages/AdminDashboard.tsx`, `webapp/src/pages/AccountLocked.tsx`, `webapp/src/components/AccessBanner.tsx`

**Interfaces:**
- Consumes: the Task 3 and Task 5 endpoints and response shapes above.
- Produces: `adminLogin(phone, password)` (stores role `platform_admin`; extend the `getRole()` union), `getAdminStats()`, `listAdminAccounts(status)`, `extendGrace(subscriptionId, until, note?)`, `banAccount(subscriptionId, reason)`, `liftBan(subscriptionId)`; routes `/admin-login` and `/admin` (not linked from the public role picker); a response interceptor that on 403 with `x-account-status` of `banned_payment` or `banned_admin` navigates to `/account-locked?why=<value>`, except when already on `/billing` for a payer.

- [ ] **Step 1: Add the client functions and the interceptor.** `AccountLocked` shows: for `banned_payment` and a payer role (`institute_admin`, or a `teacher` with no institute — the page cannot know this, so it shows a Billing link to every teacher and institute_admin; Billing already refuses non-payers) the text "Your plan wasn't renewed. Renew in Billing to restore access." with a link to `/billing`; for any other role "Your institute's account is inactive. Please contact your institute."; for `banned_admin` "This account has been suspended. Please contact Wandor support." with no link. All have a Log out button.
- [ ] **Step 2: Build `AdminLogin` and `AdminDashboard`**: six stat tiles (rupees formatted from paise; the users-gained tile has the parents footnote), a status filter, the accounts table with Extend grace (date picker, note), Ban (reason prompt) and Lift ban buttons that call the API and refresh, and API error text shown inline. Guard `/admin` so only role `platform_admin` reaches it.
- [ ] **Step 3: Build `AccessBanner`** (renders nothing when `access_state` is `active`; in `grace` shows "Your plan has lapsed. Attendance, tests and analytics are paused until you renew. Access ends on <ban_at local date>." with a Billing link) from `GET /billing/me`, mounted in `Layout` for roles `teacher` and `institute_admin` only.
- [ ] **Step 4: Run** `npx tsc --noEmit` and `npm run build`. Expected: both clean.
- [ ] **Step 5: Browser check** with the sandbox servers and `ENFORCEMENT_START` set: log in as admin, confirm the six numbers match the seeded data; extend grace on a grace account and see its ban date change; ban an independent teacher and see their next request land on the locked page with no Billing link; lift it; ban nothing else. Capture the observed values in the HANDOFF entry.
- [ ] **Step 6: Commit** `feat: admin panel and lock screens`.

### Task 7: Handoff and release notes

**Files:**
- Modify: `HANDOFF.md`, `backend/.env.example`, `README.md`

- [ ] **Step 1: Append a `## Follow-up session:` entry** to `HANDOFF.md` (what was asked, what changed and where, how verified, what is open) and add `create_platform_admin` and the new tests to its "Rules for whoever continues" test list.
- [ ] **Step 2: Add a release checklist** to the README: create both founder logins with the script, deploy, then set `ENFORCEMENT_START` to the release date (UTC). Until it is set, nothing changes for any account.
- [ ] **Step 3: Final verification**: full suite on SQLite and on Postgres, `alembic upgrade head` on an empty Postgres, `alembic check`, frontend typecheck and build. Expected: all PASS; paste the counts into the HANDOFF entry.
- [ ] **Step 4: Commit** `docs: platform admin handoff`.
