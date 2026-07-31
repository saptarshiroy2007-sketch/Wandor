# Wandor — HANDOFF

Purpose: paste this into a fresh AI session (or read it yourself later) to pick up
exactly where this session left off, with zero missing context.

> **Standing rule for every AI session working on this repo:** update this file
> before ending your turn on any change — new feature, bug fix, redesign, whatever.
> Append a new `## Follow-up session: <short name>` section (don't rewrite history
> above it) covering: what was asked, what changed and where, how it was verified,
> and what's left open/not done. This file already had one undocumented gap once
> (see the note partway down) — don't let that happen again. If you're an AI reading
> this and about to finish a turn that touched code, updating this file is part of
> finishing the turn, not an optional extra step.

## What this session did: Phase 1 fixes

Starting point was a skeleton with real gaps — this pass closed all of them.

### 1. Students router (was entirely missing)
There was no way for a teacher to add a student at all. Added `app/routers/students.py`:
- `POST /students` — create student, teacher sets an initial PIN/password
- `GET /students`, `GET /students/{id}` — list/fetch, scoped to teacher's institute
- `POST /students/{id}/set-password` — reset PIN, or activate login for students who
  existed before auth was added (their `hashed_password` was null)
- `DELETE /students/{id}`

### 2. Student auth (was stubbed with raw `student_id` param)
- `models.py`: added `Student.hashed_password` (nullable — null means login not activated)
- `auth.py`: `create_access_token` now takes a `role` ("teacher" or "student"), embedded
  in the JWT. Added `get_current_student` dependency, separate from `get_current_teacher`.
  A teacher token cannot be used to authenticate as a student and vice versa, even though
  both use the same signing secret — the `role` claim is checked on every decode.
- `routers/auth.py`: added `POST /auth/student-login` (phone + PIN)
- `routers/tests.py`: `start_attempt`, `submit_attempt`, `flag_attempt` all now require
  `get_current_student` instead of trusting a client-supplied `student_id`. Test lookup
  is scoped to the student's own `institute_id`; attempt lookups are scoped to the
  authenticated student's own attempts.

**Frontend impact:** the webapp/Android app needs a student login screen calling
`POST /auth/student-login`, storing the returned bearer token, and sending it on
`/tests/*` calls (currently `TakeTest.tsx` likely still passes a raw student_id somewhere
— check that file before wiring this up).

### 3. File upload endpoint (was missing — doc-locked tests assumed a pre-existing URL)
- `app/services/storage.py` — new. Abstraction with two backends:
  - `local` (default): saves to disk under `UPLOAD_DIR`, served via `/uploads` static
    mount added in `main.py`. Fine for single-instance dev/MVP only — breaks once you
    run multiple backend instances behind a load balancer (files only exist on one box).
  - `s3`: any S3-compatible store (real AWS, Cloudflare R2, Backblaze B2). Set
    `STORAGE_BACKEND=s3` + fill in `S3_*`/`AWS_*` env vars. Switching backends never
    touches the router — only `.env` changes.
- `app/routers/uploads.py` — new. `POST /uploads/test-document` (teacher-only, PDF/PNG/JPEG,
  25MB cap). Returns a URL to pass straight into `POST /tests/document`.

**Before going to production:** switch `STORAGE_BACKEND` to `s3` — local disk storage is
explicitly a dev-only shortcut.

### 4. Attendance tracking (didn't exist)
- `models.py`: new `AttendanceRecord` table — `class_session_id` + `student_id` +
  `present` + who marked it and when.
- `app/routers/attendance.py` — new:
  - `POST /attendance/mark` (teacher) — bulk upsert attendance for a whole class session
  - `GET /attendance/class/{class_session_id}` (teacher) — roster for one session
  - `GET /attendance/student/{id}/summary` (teacher) — % attendance for one student
  - `GET /attendance/me/summary` (student) — powers the eventual parent/student dashboard

This is intentionally **rule-based, not LLM-backed** — same deterministic-first
philosophy as GymCoach Studio's engines. Attendance %, rank, fee logic etc. should never
route through an LLM call; only `mcq_gen.py` should.

### 5. Real MCQ generation (was a stub returning placeholder text)
- `app/services/mcq_gen.py` — now calls the Anthropic API (`claude-sonnet-4-6`) with a
  strict JSON-only prompt, validates the response shape (drops any malformed question,
  rejects `correct_option` values outside a/b/c/d), and **falls back to the old
  placeholder stub** if `ANTHROPIC_API_KEY` is unset or the call/parse fails for any
  reason — test creation never hard-fails because of this.
- This is the **one** intentionally non-deterministic/LLM piece in Wandor, mirroring
  GymCoach's "Trainer Review stays on Gemini, everything else goes deterministic" split.

### 6. Alembic migrations (didn't exist)
- Scaffolded `alembic/` via `alembic init`, wired `env.py` to import `app.database.Base`
  and `app.models` so `target_metadata` is populated and autogenerate works going
  forward, and pulls `DATABASE_URL` from `.env`/`Settings` instead of hardcoding in
  `alembic.ini`.
- `alembic/versions/0001_initial_schema.py` — **hand-written**, not autogenerated,
  because no live Postgres instance was reachable in the sandbox this was built in.
  It mirrors `models.py` exactly as of this commit (including the new
  `hashed_password` column and `attendance_records` table). **Run `alembic check` or
  diff it against a real DB before trusting it blindly in production** — hand-written
  migrations are more error-prone than autogenerated ones.
- `main.py` still calls `Base.metadata.create_all()` on startup for fast local dev —
  comment added clarifying migrations are the source of truth for anything
  staging/production (`alembic upgrade head`).

### Also fixed
- Confirmed `admin.py`/`students.py` stale `.pyc` files (flagged in a prior session)
  were **not** a live bug — `main.py` never imported them, they were just leftover
  compiled artifacts from an earlier version. `students.py` now exists for real as
  part of this fix pass; `admin.py` remains genuinely not built (see roadmap below).

## Verified working
- All modified/new `.py` files compile cleanly (`python -m py_compile`)
- Full app imports successfully end-to-end (`from app.main import app`) with sqlite
  swapped in for a quick smoke test — all 7 routers (auth, classes, tests, payments,
  students, attendance, uploads) register correctly, plus the `/uploads` static mount
- Not tested: an actual Postgres instance, real Anthropic API call, real S3 upload —
  none of these were reachable from the sandbox. Test all three before deploying.

## requirements.txt / .env.example additions
- `anthropic==0.39.0`, `boto3==1.35.36`, `alembic==1.13.3` added to requirements.txt
- `.env.example` documents `ANTHROPIC_API_KEY`, `STORAGE_BACKEND`, `UPLOAD_DIR`,
  `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_PUBLIC_BASE_URL`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`

## What's NOT done yet (per the earlier roadmap discussion)
Phase 1 fixes are complete. Still ahead, roughly in priority order:
- **Phase 2**: multi-tenant `institute_id` scoping is already present on all models
  (good — was built in from the start), but white-label branding config isn't. WhatsApp
  notify (`notify.py`) exists but should be extended. Parent-specific read-only role
  doesn't exist yet (student role does now). Real payment gateway webhook handling
  needs checking — `Payments.tsx` + `routers/payments.py` weren't touched this session.
- **Phase 3**: topic-wise wrong-answer analytics, batch-relative rank/percentile,
  adaptive difficulty — all planned as deterministic rule-based logic, not LLM calls.
  None built yet.
- **Phase 4**: admin panel per institute, tiered plan gating (the `Institute.plan` field
  exists in the model but nothing reads it to gate features yet).
- **Phase 5**: local language toggle, live class embed (Jitsi), further polish.

## Frontend note
This entire session was backend-only. `webapp/` (React) has not been touched — Login.tsx,
TakeTest.tsx etc. still need wiring to the new student-auth flow and file upload flow
described above. Per the earlier plan (vertical-slice, not backend-then-frontend), the
next session should wire student auth into `Login.tsx`/`TakeTest.tsx` before moving to
the next backend feature.

---

## Follow-up session: frontend student-auth wiring (time-boxed, small scope)

Done, given limited time remaining:

- `api/client.ts`: added `studentLogin()`, `logout()`, `getRole()`. Fixed
  `startTestAttempt()` — it used to pass a raw `student_id` as a query param, which the
  **backend no longer accepts** since `start_attempt` now requires a student bearer token
  (`get_current_student`). This would have been a live break against the new backend if
  left unfixed. Also added `createStudent`, `listStudents`, `uploadTestDocument`,
  `markAttendance`, `getClassAttendance`, `myAttendanceSummary` client functions for the
  new backend endpoints (not yet wired into any page UI — just available to call).
- `pages/StudentLogin.tsx`: new page, phone + PIN form, calls `studentLogin()`.
- `pages/TakeTest.tsx`: removed the `wandor_student_id` localStorage hack, now calls
  `startTestAttempt(testId)` with no second argument — the token carries identity.
- `main.tsx`: added `/student-login` route. `/test/:testId` was previously **completely
  unprotected** (any visitor, logged in or not, could hit it) — now gated by a
  `StudentProtected` wrapper that checks both `isLoggedIn()` and `getRole() === 'student'`,
  so a teacher's token being present doesn't grant access (the backend would reject it
  anyway, but the frontend now fails fast with the right redirect instead of a confusing
  401 after the page half-loads).

### Not done yet in the frontend (next session should pick up here)
- No student signup/self-registration screen — students are still only created by a
  teacher via `POST /students` (by design, per the model), but there's no teacher-facing
  UI for that yet. `Dashboard.tsx` doesn't have an "add student" form.
- `uploadTestDocument()` client function exists but isn't wired into any "create document
  test" UI yet — a teacher currently has no screen to upload a PDF and get the
  `document_url` to pass into test creation.
- Attendance client functions (`markAttendance`, `getClassAttendance`,
  `myAttendanceSummary`) exist but have zero UI — no attendance-marking screen for
  teachers, no "my attendance %" view for students.
- `Dashboard.tsx` wasn't touched — still teacher-only, no student-facing dashboard exists
  (student login currently only unlocks `/test/:testId`, nothing else).
- Not tested against a running dev server (no network access to npm registry beyond
  what's allow-listed, and no backend running in this sandbox) — TypeScript syntax was
  checked with `tsc --noEmit -p tsconfig.json`, which passed cleanly on all edited files
  (one pre-existing, unrelated `import.meta.env` type error on line 5 of `client.ts`,
  present before this session's changes too - not something introduced here).

### Suggested next step
Wire `uploadTestDocument` + `createStudent`/`listStudents` into `Dashboard.tsx` (or a new
`ManageStudents.tsx` page) so a teacher has a real workflow: add students → schedule
class → mark attendance → create test (MCQ or upload+document). That's the minimum to
demo one full teacher-side loop end to end.

---

## Note: undocumented gap before the next session below

The zip handed into the next session already contained `ManageStudents.tsx`,
`MarkAttendance.tsx`, `StudentHome.tsx`, `ParentLogin.tsx`, `ParentDashboard.tsx`, a
`parents.py` router, `Student.parent_pin_hash`, and `uploadTestDocument` wired into
`CreateTest.tsx` — all of which cover most of the "Not done yet" list right above this
note. None of that work is documented anywhere above. Whoever picks this up next should
be aware the written history has a gap: real feature work happened between the last
entry above and the session below, with no handoff notes for it. Read the actual code,
not just this file, before assuming you know the full state.

---

## Follow-up session: role-select landing page + logout fix

**Problem reported:** opening the site always dropped straight into the teacher login
screen, with no way to choose teacher/student/parent up front.

- `pages/RoleSelect.tsx` — new. Landing page with **Teacher** / **Institute owner**
  buttons, and a **Student** button that reveals **Student login** / **Parent login**
  as a sub-choice.
- `main.tsx`:
  - Root `/` no longer renders `Dashboard` directly. New `HomeRoute` component: if
    logged out, renders `RoleSelect`; if logged in, redirects straight to whichever
    dashboard matches the stored role (teacher → `Dashboard`, student → `/home`,
    parent → `/parent`, institute_admin → `/institute`) — so an already-logged-in
    visitor doesn't see the picker every time.
- `components/Layout.tsx` — `handleLogout()` used to `navigate()` back to the
  role-specific login page (e.g. teacher logout → `/login`), which reproduced the
  original bug one click later. Now logout always sends everyone back to `/` (the
  picker), regardless of role.

Verified: `tsc --noEmit -p tsconfig.json` clean on all edited/new files.

---

## Follow-up session: institute-admin login + dashboard

**Feature requested:** an institute-owner dashboard/login, separate from teacher
login — for managing the institute's own settings and teacher roster. (Confirmed with
the user first: no platform-wide super-admin role exists anywhere in this codebase —
this is institute-owner scope only, one level up from `Teacher.is_owner`, not a
cross-institute admin panel.)

### Backend
- `models.py` — `Institute.hashed_password` (nullable; null = institute-admin login
  not yet activated — same pattern as `Student.hashed_password` /
  `Student.parent_pin_hash`). Deliberately a **separate credential from any Teacher
  row**, not the teacher login with extra permissions unlocked.
- `auth.py` — new `institute_oauth2_scheme` + `get_current_institute_admin`
  dependency, isolated the same way `get_current_parent` is: an institute token's
  `role` claim is `institute_admin`, so it can never be swapped in as a teacher/
  student/parent token or vice versa.
- `schemas.py` — `InstituteLogin`, `InstituteOut`, `InstituteUpdate`,
  `TeacherCreate`, `TeacherOut`.
- `routers/auth.py` — `POST /auth/institute-login` (owner_phone + password).
- `routers/institute.py` — new. All endpoints scoped to the authenticated institute:
  - `GET /institute/me`, `PATCH /institute/me` (name only — plan is a billing
    concern, not self-serve from here)
  - `GET /institute/teachers`, `POST /institute/teachers`,
    `DELETE /institute/teachers/{id}`
- `main.py` — registered the new router.
- `alembic/versions/0003_add_institute_admin_password.py` — adds
  `institutes.hashed_password`.
- `scripts/set_institute_password.py` — **there's still no institute self-signup
  flow**, so this CLI is the only way to activate (or reset) an institute-admin
  password right now: `python -m scripts.set_institute_password --phone <owner_phone>
  --password <new_password>`. The institute row itself also has to already exist in
  the DB (created directly, e.g. via a one-off `Institute(...)` insert) — there's no
  endpoint that creates one yet.

### Frontend
- `pages/InstituteLogin.tsx` — phone + password form, same shape as `Login.tsx`.
- `pages/InstituteDashboard.tsx` — edit institute name, add/remove teachers (list +
  create form + remove button), same visual conventions as `ManageStudents.tsx`.
- `api/client.ts` — `instituteLogin`, `getInstitute`, `updateInstitute`,
  `listInstituteTeachers`, `createTeacher`, `deleteTeacher`. `getRole()`'s return
  type now includes `'institute_admin'`.
- `main.tsx` — `/institute-login`, `/institute` (protected) routes.
- `RoleSelect.tsx` — added "Institute owner" as a third top-level button.

**Verified:** backend `py_compile` on all edited/new files, full `from app.main import
app` smoke test with SQLite confirming all routes register (including the two new
`/institute/*` and `/auth/institute-login` routes), and an end-to-end test of the
bootstrap script against a throwaway SQLite DB (create institute row → set password →
confirms it persists). Frontend: `tsc --noEmit -p tsconfig.json` clean. Confirmed
working end to end against the user's real local dev setup (SQLite, not Postgres) in
this session — migration applied (`alembic stamp 0002` then `alembic upgrade head`,
since the DB predated `alembic_version` tracking), institute row created, password set,
login confirmed working by the user.

### Not done yet
- No nav links for the `institute_admin` role in `Layout.tsx` — only a Logout button.
  Fine while `InstituteDashboard` is the only institute-admin page, but add nav entries
  here if more institute-admin pages get built (billing, plan management, etc.).
- No institute self-signup flow — institutes and their admin passwords are both
  currently created by hand (DB insert + the CLI script). Whoever builds a real signup
  flow should retire `scripts/set_institute_password.py`'s role as the only path in.
- Plan (`Institute.plan`) is still not gated anywhere — `InstituteUpdate` deliberately
  excludes it (billing concern), but nothing reads it to restrict features either, same
  gap noted in the original Phase 4 roadmap below.
- Not tested against a real production Postgres instance, only SQLite.

### Suggested next step
Either build the institute self-signup flow (create `Institute` + set
`hashed_password` in one request) to retire the manual DB/CLI bootstrap, or move on to
the original Phase 3/4 roadmap below (analytics, plan gating) — both are still open.

---

## Follow-up session: attendance % badge on the teacher's student roster

**Feature requested:** quick add-on, teacher-facing. No backend changes needed — this
reused the existing `GET /attendance/student/{id}/summary` endpoint that already backed
the student/parent dashboards.

- `api/client.ts` — new `studentAttendanceSummary(studentId)`.
- `pages/ManageStudents.tsx` — after the roster loads, fires one summary request per
  student and renders an attendance-% badge next to the existing login-status badge
  (muted/grey styling if under 75%, reusing the existing `.badge-muted` CSS class — no
  new styles added).

**Known limitation, intentional for now:** this is N+1 requests (one per student in the
roster), not a bulk call. Fine for typical coaching-centre roster sizes. If this ever
needs to scale to a roster of hundreds shown on one screen, add a bulk
`GET /attendance/summary?institute_id=...` endpoint instead of looping per-student calls
from the frontend — flagged inline in the code with a comment at the call site.

**Verified:** `tsc --noEmit -p tsconfig.json` clean. Not manually click-tested by the
user yet in this session — worth confirming a student with zero marked attendance
renders `0% attendance` correctly rather than silently showing no badge.

---

## Follow-up session: frontend visual design pass ("the roll-call register")

**Requested:** a real design pass on the existing pages (colors/layout/polish), not new
pages/screens — user plans to keep upgrading the frontend incrementally as more
features land, starting from this visual baseline.

**Direction:** grounded in the physical attendance ledgers/marksheets Indian tuition
centres already keep, not a generic SaaS look. Deliberately avoided the three
AI-design-default clusters (cream+serif+terracotta, near-black+neon accent, broadsheet
hairline-rule layout).

- **Color:** warm register-paper background (`--paper`), deep chalkboard-green nav bar
  (`--chalkboard`), stamp-red (`--stamp-red`) used sparingly for alerts/margin-rule/
  active-tab-underline, muted olive-brown for secondary text.
- **Type:** Zilla Slab for headers (official-document/register feel), IBM Plex Sans for
  body/UI, IBM Plex Mono for anything data-like — phone numbers, ids, dates, and
  especially the attendance-% badges added last session. Loaded via Google Fonts in
  `index.html`.
- **Signature element:** status badges (`.badge`) render as rotated rubber ink-stamps —
  border instead of fill, uppercase spaced mono type, slight rotation — rather than flat
  pills. Cards (`.card`) carry a faint ruled-paper background (repeating horizontal
  lines) and a red left-margin rule, like a notebook page.

**Files changed:**
- `index.css` — full rewrite (token system + every shared class: card, badge, button,
  nav, table, form controls).
- `index.html` — added the three Google Fonts.
- `components/Layout.tsx` — wrapped nav content in a new `.nav-inner` div so it stays
  centered inside the now-full-width chalkboard bar; fixed the logout button's contrast
  against the dark nav (it inherited the light-background ghost-button style before).

**Why so few files:** every page (`Dashboard`, `ManageStudents`, `Login`,
`InstituteDashboard`, etc.) already consumes the shared classes above rather than
one-off styles, so the whole app re-skins from this one CSS pass. No page component
logic changed.

**Verified:** `tsc --noEmit -p tsconfig.json` and `vite build` both clean. **Not
visually eyeballed by either the user or this session** — there's no way to screenshot
the user's live browser from here. The user was told to run `npm run dev` and look
before building more on top of this baseline.

### Not done yet
- No actual screenshot/visual QA happened. If contrast, spacing, or the ruled-card
  look reads badly in a real browser, that needs to be reported back and fixed before
  more features get styled to match it.
- Page-specific layout choices (e.g. `RoleSelect.tsx`'s inline `style={{ background:
  'var(--surface)', ... }}` overrides for its secondary buttons) still exist as inline
  styles rather than shared classes — harmless today since the token values they
  reference still resolve correctly, but worth folding into proper classes if that
  pattern gets repeated elsewhere.

### Suggested next step
Get visual confirmation from the user first. After that, either keep going down the
Phase 3/4 roadmap (analytics, plan gating, institute self-signup), or do page-specific
design polish now that the shared token system exists (e.g. a more tailored empty-state
illustration/copy per page, per the frontend-design skill's guidance on treating
emptiness as a moment for direction).

---

## Follow-up session: CSV bulk import, fee reminder scheduler, analytics endpoints

Picked up 3 items from "Not done yet"/Phase 3 roadmap. All backend changes tested
end-to-end with FastAPI TestClient against a temp SQLite file DB.

### 1. CSV bulk student import
- `routers/students.py`: `POST /students/bulk-import` (teacher-only, multipart CSV).
  Columns: `name`, `phone` (required), `parent_phone`, `batch`, `password` (optional,
  defaults to last 4 digits of phone). Dedupes against existing institute students AND
  within the same file, by phone. Never partial-fails a whole request — bad/duplicate
  rows are skipped and reported per-row, good rows still get created.
- `schemas.py`: `StudentBulkImportRow`, `StudentBulkImportResult`.
- Frontend: `api/client.ts` → `bulkImportStudents()`; wired into `ManageStudents.tsx`
  with a file input + result summary (created/skipped counts + per-row skip reasons).

### 2. Fee reminder scheduler
- `app/services/fee_reminders.py` — new. `send_due_fee_reminders()` finds every unpaid
  `FeeRecord` due within `FEE_REMINDER_DAYS_BEFORE` days (default 3) or already overdue,
  notifies the student (+ parent if `parent_phone` set) via the existing `notify()`
  service, and dedupes so the same fee is never reminded twice in one calendar day.
- `models.py`: new `FeeRecord.last_reminder_sent_at` column (dedupe marker) —
  **migration `0004_add_fee_reminder_sent_at.py` added, needs `alembic upgrade head`**.
- `database.py`: new settings — `fee_reminder_enabled` (default True, kill switch),
  `fee_reminder_days_before` (default 3), `fee_reminder_hour` (default 9, UTC).
- `main.py`: `BackgroundScheduler` (APScheduler, already in requirements.txt) started/
  stopped on FastAPI startup/shutdown events, cron-triggered daily at
  `fee_reminder_hour`.
- Not yet exposed as an API endpoint (no manual "send reminders now" trigger, no way
  to view reminder history from the dashboard) — pure background job for now.

### 3. Analytics endpoints (Phase 3 item)
- `GET /attendance/batch/{batch}/analytics` (teacher) — per-student attendance % for
  every student in a batch, sorted lowest-first so at-risk students surface
  immediately, plus a batch average. 404s if the batch has no students.
- `GET /tests/{test_id}/analytics` (teacher) — per-question correct-rate breakdown
  across submitted attempts only, `is_weak` flag on any question under 50% correct
  (`WEAK_QUESTION_THRESHOLD_PCT` in `routers/tests.py`), average score/pct, sorted
  worst-question-first. Malformed/legacy `TestAttempt.answers` JSON is skipped rather
  than 500ing the whole report.
- `schemas.py`: `StudentAttendanceRow`, `BatchAttendanceAnalytics`, `QuestionStat`,
  `TestAnalytics`.
- Frontend: `api/client.ts` → `batchAttendanceAnalytics()`, `testAnalytics()`.
  `batchAttendanceAnalytics` wired into `ManageStudents.tsx` (enter a batch name, view
  sorted attendance list). `testAnalytics` client function added but **not yet wired
  into any test-results page** — no UI surfaces weak questions or score breakdown yet.

### Not done yet
- Migration `0004` not yet run against the user's real dev DB — run
  `alembic upgrade head` before the fee reminder feature will work (the column doesn't
  exist yet without it).
- Remaining Phase 3/4 items untouched: batch-relative rank/percentile, adaptive
  difficulty, plan gating, white-label branding, institute self-signup.
- `tsc --noEmit` clean on all edited/new frontend files. Not visually eyeballed in a
  real browser by either the user or this session.

---

## Follow-up session: test-analytics UI + manual fee-reminder trigger

Closed the two gaps left open at the end of the last session.

- `pages/CreateTest.tsx`: each mcq_auto test in the list now has a "View analytics"
  toggle (document tests don't get one - no `Question` rows to analyze). Expands a
  panel showing attempt count, average score, weak-question count, and a per-question
  correct-rate breakdown (worst first), using the existing `GET /tests/{id}/analytics`
  endpoint via the new `testAnalytics()` client function.
- `routers/payments.py`: `POST /payments/send-reminders-now` (teacher-only) - manual
  trigger for the daily cron job. **Scoped to the calling teacher's own institute** -
  `services/fee_reminders.py`'s `send_due_fee_reminders()` now takes an optional
  `institute_id` filter (`None` = global sweep, used by the cron job; a specific id =
  scoped sweep, used by this endpoint) so triggering it can never touch another
  institute's fee records. Verified with a two-institute test: triggering from
  institute A's teacher token only checked institute A's fee record, not institute B's.
- `api/client.ts`: added `testAnalytics()`, `sendFeeRemindersNow()`.
- `send-reminders-now` client function exists but **isn't wired into any UI yet** - no
  button on `Payments.tsx` to trigger it manually. Next session could add one there.

Verified: all four backend TestClient scripts from the previous session re-ran clean
(bulk import, fee reminder dedupe, batch attendance analytics, test analytics), plus a
new cross-institute scoping test for the manual trigger. `tsc --noEmit -p tsconfig.json`
clean on all edited files.

### Not done yet
- No UI button for `sendFeeRemindersNow()` - client function only.
- Migration `0004` still not run against the user's real dev DB (see above, unchanged).
- Same remaining Phase 3/4 roadmap items as before (rank/percentile, plan gating,
  white-label branding, institute self-signup), plus none of the new UI has been
  visually eyeballed in a real browser yet.



