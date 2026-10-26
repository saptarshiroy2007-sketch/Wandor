# Wandor — HANDOFF

> **Billing/payments work: start at the last section, "WHAT TO DO NEXT (billing)".** It is the
> single up-to-date list of what is done, what is open, and what only the owner can decide.
> Older "still open" lists further up are annotated where later phases superseded them.

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




---

## Follow-up session: signup feature (teacher + institute self-signup, batch-scoped student adding)

**Feature requested:** replace the login-only flow (all accounts previously created by
direct DB insert or by another role) with real signup for teachers and institutes.
Students and parents deliberately still have no self-signup path - only a teacher or
institute admin can create those logins. Also: institute-affiliated non-owner teachers
should only be able to add students to a batch they're explicitly assigned to;
independent teachers and institute owners stay unrestricted.

### Backend
- `models.py` - new `TeacherBatchAssignment` table (`teacher_id`, `batch`). Independent
  teachers (`Teacher.institute_id is None`) and owners (`Teacher.is_owner`) are never
  scoped by it - the table only matters for a non-owner, institute-affiliated teacher.
- `schemas.py` - `TeacherSignup`, `InstituteSignup`, `BatchAssignmentSet`; `TeacherCreate`
  gained `batches: List[str] = []`, `TeacherOut` gained `batches: List[str]`.
- `routers/auth.py`:
  - `POST /auth/teacher-signup` - creates an INDEPENDENT teacher (`institute_id=None`,
    `is_owner=False`). No institute field on the schema on purpose - a teacher can't
    self-attach to an institute here; that binding only ever happens the other
    direction (an institute admin adding them).
  - `POST /auth/institute-signup` - creates the `Institute` row and activates its
    password in one request. Replaces the old manual DB-insert +
    `scripts/set_institute_password.py` bootstrap as the primary path in - the script
    still works as an admin fallback but isn't the only way in anymore.
- `routers/institute.py`:
  - `POST /institute/teachers` now accepts `batches` and creates
    `TeacherBatchAssignment` rows for non-owner teachers (ignored, not rejected, when
    `is_owner=True`).
  - `PUT /institute/teachers/{id}/batches` - full-replacement reassignment.
  - `POST /institute/students`, `GET /institute/students` - institute admin can add/
    list students directly, unscoped by batch (unlike a non-owner teacher).
- `routers/students.py` - new `_assert_can_add_to_batch(teacher, batch, db)` helper,
  called from both `create_student` and per-row inside `bulk_import_students` (bad-batch
  rows are skipped-and-reported, same pattern as other bad rows, not a hard 403 for the
  whole file).
- `alembic/versions/0005_add_teacher_batch_assignments_and_signup.py` - new table only;
  no column changes needed on existing tables (`Teacher.institute_id` and
  `Institute.hashed_password` were already nullable, which is what makes independent
  teachers and self-service institute signup possible without a schema change there).

### Frontend
- `api/client.ts` - `teacherSignup()`, `instituteSignup()`, `setTeacherBatches()`,
  `listInstituteStudents()`, `createInstituteStudent()`; `createTeacher()`'s payload
  type gained `batches?: string[]`.
- `pages/TeacherSignup.tsx`, `pages/InstituteSignup.tsx` - new, same visual conventions
  as `Login.tsx`/`InstituteLogin.tsx`.
- `main.tsx` - `/teacher-signup`, `/institute-signup` routes.
- `Login.tsx` / `InstituteLogin.tsx` - added "sign up" links.

**Verified:**
- Backend: `py_compile` clean on all edited files; full `FastAPI TestClient` script
  covering the whole matrix - institute signup (+ duplicate-phone rejection),
  independent teacher signup + free student-add to any batch, institute-created
  non-owner teacher blocked from an unassigned batch and allowed into an assigned one,
  institute owner teacher unrestricted, institute admin direct student-add, and batch
  **reassignment taking effect immediately** (old batch blocked, new batch allowed
  right after a `PUT .../batches` call). All assertions passed.
- Frontend: `tsc --noEmit -p tsconfig.json` and `npm run build` both clean.
- Not tested: real Postgres (migration 0005 only verified by inspection against the
  0004 pattern, not run against a live DB), and none of the new UI has been visually
  eyeballed in a browser.

### Not done yet / open questions for next session
- **Password change / settings feature is intentionally NOT part of this pass** -
  explicitly deferred by the user to be designed together as its own "settings"
  feature later. `SetStudentPassword`/`SetParentPin` already let a *teacher* reset a
  *student's* password, but there's still no self-service "change my own password"
  for teachers, students, or institute admins.
- **No teacher-facing UI for `batches`** - `TeacherCreate`'s `batches` field and
  `setTeacherBatches()` exist and are tested at the API level, but `InstituteDashboard.tsx`'s
  "add teacher" form doesn't have a batch-picker input yet, and there's no UI to view/
  edit an existing teacher's assigned batches. Next session should wire this in.
- **No UI for institute-direct student adding** - `createInstituteStudent()` /
  `listInstituteStudents()` exist as client functions only; `InstituteDashboard.tsx`
  has no "add student" section yet (mirrors the teacher-side `ManageStudents.tsx` gap
  that existed for institute students specifically).
- **Independent teacher who later joins an institute isn't reconciled** - if a teacher
  signs up independently (`institute_id=None`) and an institute admin later wants to
  bring them on board, there's no merge/claim flow - the admin would have to create a
  brand-new `Teacher` row via `POST /institute/teachers` with a different phone,
  leaving the original independent account orphaned. Flagged, not solved.
- **Batch names are free-text strings everywhere** (`ClassSession.batch`,
  `Student.batch`, `TeacherBatchAssignment.batch`) - a typo when assigning a teacher to
  "Class 10A" vs typing "class 10 a" elsewhere silently creates a mismatch with no
  validation catching it. Worth considering a real `Batch` model with an id, at some
  point, instead of matching on raw strings.
- No self-signup for students/parents was added, by design, per the user's explicit
  requirement.

---

## Follow-up session: theme redesign — "the question paper"

**Why:** the previous theme ("the admit card," navy/amber) read as bland/generic
corporate palette despite the ticket-concept details in the CSS comments — the
personality was too subtle to register at a glance. Also caught: HANDOFF.md's
"roll-call register" description didn't match what was actually live in `index.css`
("the admit card") — theme got swapped at some point without a log entry. This entry
is that log.

**New direction:** "the question paper" — grounded in the fact that Wandor runs real
MCQ tests, not decoration bolted on. Pale exam-paper background with a faint ruled-line
texture, exam-board ink-blue (`#1f3f8f`) as the working accent, highlighter-yellow
(`#f2c94c`) used ONLY for flag states (overdue fees, weak questions, unmarked
attendance) so it stays meaningful instead of decorative.

**Signature element:** the OMR bubble (`.omr-option` / `.omr-bubble` in `index.css`) -
a real answer-sheet fill-in-the-circle control wrapping a visually-hidden native
radio/checkbox (keeps keyboard nav + screen readers working). Square variant
(`.omr-bubble.square`) for binary present/absent marks so it doesn't read as
"pick one of many" the way the round MCQ bubble does. Applied to:
- `pages/TakeTest.tsx` - MCQ answer options (was plain `<input type=radio>`)
- `pages/MarkAttendance.tsx` - present/absent checkbox (was plain `<input type=checkbox>`)

**Logo/brand mark:** "W" set in Castellar (`.brand-mark`, `.brand-word` in
`index.css`), a Roman-inscriptional-capitals face - fits the exam-board gravitas
concept well. Castellar is Monotype-owned and NOT on Google Fonts (a request to add it
was filed and closed) - no legit free CDN hosts it. It's referenced first in the font
stack so it renders correctly for the many people who already have it system-installed
(ships with Windows/MS Office), falling back to a small-caps serif that apes the same
look for everyone else - never looks broken either way. If guaranteed identical
rendering across every device matters later, that means buying a Castellar license or
picking a genuinely-free lookalike (checked: "Kastellar" is one option, not verified
for quality/license terms here).

Applied the wordmark across `components/Layout.tsx` (in-app nav) and all 7 pre-login
pages (`RoleSelect`, `Login`, `TeacherSignup`, `InstituteSignup`, `InstituteLogin`,
`StudentLogin`, `ParentLogin`).

**Other CSS changes worth knowing:**
- Font stack swapped: `Space Grotesk`/`Inter` → `Archivo` (headings) + `IBM Plex Sans`
  (body) + `IBM Plex Mono` (kept, for data - roll numbers, dates, table cells).
- `--line` var renamed to `--rule` throughout (ruled-paper metaphor). One inline usage
  in `TakeTest.tsx` (`var(--line)` on the locked-test iframe border) updated to match -
  would've silently fallen back to browser default border color otherwise.
- Card corners went from `border-radius: 8px` → `3px` (`--radius`) - sharp, like an
  official document, not a soft app card.
- New `.instructions-box` component - the boxed "INSTRUCTIONS" header pattern real
  exam papers open with. Not yet applied to any page - available for empty
  states/page intros next session.

**Verified:** `tsc --noEmit` clean, `vite build` clean (6.39kB CSS, no errors). Not
verified: actually rendered in a browser. No screenshot/browser tool was available this
session - don't trust this is visually right until someone runs `npm run dev` and
looks.

### Not done yet
- `.instructions-box` pattern built but unused - candidate for `Dashboard.tsx` and
  other pages' empty states.
- OMR bubble styling only applied to the two spots above - other binary/choice UI in
  the app (if any exists elsewhere, e.g. role toggles) wasn't audited for consistency.
- No favicon/app-icon file generated from the new "W" mark yet - `.brand-mark` is
  in-page only, `index.html`'s `<link rel="icon">` (if any) wasn't touched.

---

## Follow-up session: WhatsApp notification coverage

**Context:** `services/notify.py` (WhatsApp Cloud API + Twilio SMS fallback) and the
daily fee-reminder job already existed. This session covered every remaining piece
that was either half-wired (backend done, no UI) or missing outright.

### 1. "Send reminders now" button — was dead code, now wired
`POST /payments/send-reminders-now` already existed backend-side with zero UI
hookup (a known gap from an earlier HANDOFF entry). Added the button to
`pages/Payments.tsx` - shows a "checked X, sent Y" summary after firing. No backend
changes needed here at all.

### 2. Class reschedule (cancellation alerts already existed)
Cancellation notifications were ALREADY implemented (`POST /classes/{id}/cancel` +
`_notify_batch`) - just no reschedule equivalent existed at all, and neither cancel
nor the class list had any frontend UI.
- Backend: new `POST /classes/{id}/reschedule` (`schemas.ClassReschedule`) - notifies
  the batch with BOTH old and new time in one message (a bare "new time" is easy to
  skim past). Rejects rescheduling a class that isn't currently `scheduled` (can't
  reschedule something already cancelled/completed - 400).
- Frontend: `pages/ScheduleClass.tsx` rewritten - now lists upcoming classes with
  Cancel and Reschedule buttons (was create-only before, no visibility into existing
  classes at all).
- No new DB columns - reuses `ClassSession.start_time`/`end_time`, no migration
  needed.

### 3. New notification types: attendance + test results
Neither existed before this session - `routers/attendance.py` and `routers/tests.py`
had zero notify() calls.
- **Attendance:** `POST /attendance/mark` now notifies a PARENT (only, not the
  student - they already know they were absent) whenever a mark comes in as
  `present: false`, if `parent_phone` is set. Runs as a background task, same
  fire-and-forget pattern as `_notify_batch`.
  **Known limitation:** fires on every absent mark including RE-marks (upsert calling
  `/mark` again for the same class/student still re-notifies if still absent) - could
  spam a parent if a teacher re-submits the same attendance sheet. Not fixed this
  session - would need to only notify on a present→absent transition, which means
  diffing against the existing record before overwriting it.
- **Test results:** `POST /tests/attempts/{id}/submit` now notifies the student AND
  parent (if set) with score/total/percent immediately after an `mcq_auto` test is
  scored. **Only fires for `mcq_auto`** - a `document_locked` test has no instant
  score (a teacher grades it manually, whenever that happens on their own timeline),
  so there's no natural moment to notify at submit time for that test type. Worth
  designing a separate "teacher publishes grade" trigger for document tests later.

**Verified:** `py_compile` clean; a `FastAPI TestClient` script with `notify()` mocked
(so no real WhatsApp/Twilio calls happen in tests) covering all three - reschedule
fires the right message and blocks on non-scheduled classes, attendance fires to the
parent phone specifically (not the student), test submission notifies both student and
parent with the right score. All assertions passed. Frontend: `tsc --noEmit` and
`npm run build` both clean.

### Not done this session
- Attendance re-mark spam (see limitation above).
- No "publish grade" flow/notification for `document_locked` tests.
- `TestAnalytics`'s UI hookup is a SEPARATE known gap (not WhatsApp-related, from an
  earlier HANDOFF entry) - still not done, wasn't in scope here.
- No notification preferences/opt-out anywhere - every parent with a phone on file
  gets every applicable alert, no per-institute or per-parent toggle.
- WhatsApp template names used (`class_rescheduled`, `attendance_absent`,
  `test_result`) are new on top of the existing `class_scheduled`/`class_cancelled`/
  `fee_reminder` ones - these need to actually exist as APPROVED templates in Meta's
  WhatsApp Business dashboard before they'll work outside the 24h free-form window.
  Nothing in code checks whether a template is actually approved - `notify()` will
  just fail silently (falls back to SMS) if it isn't.

---

## Follow-up session: pre-fixes + MCQ→teacher-authored + batch-scoped tests

**Tasks asked for:** (A1 delete, A2 lenient, A3 all) — the scope-decisions session's
items 0, 0b, partial-1, partial-4, plus four pre-existing bugs from the audit session.

### Pre-fix 1: commit floating uncommitted work — DONE
The entire "WhatsApp notification coverage" session had never been committed
(`attendance.py`, `classes.py`, `tests.py`, `schemas.py`, `client.ts`, `Payments.tsx`,
`ScheduleClass.tsx`, `HANDOFF.md`). Committed as-is before touching anything else,
as the audit session instructed. Commit: `fdeaa2cb`.

### Pre-fix 2 / Item 1 partial: cross-tenant login collision — DONE (lenient)
`student_login()` and `parent_login()` now accept an optional `institute_id` field in
their request payload. When provided, the DB query is scoped to that institute — fixes
the collision. When omitted, old behaviour applies (first row wins), which is fine for
single-institute deployments. Non-breaking API change. Files: `schemas.py`
(`StudentLogin.institute_id`, `ParentLogin.institute_id`), `routers/auth.py` (both
login functions now build a query object and conditionally `.filter` by institute_id).
The strict version (require institute_id) was not implemented per A2.

### Pre-fix 3: pydantic exact pin — DONE
`pydantic==2.10.0` → `pydantic>=2.10.0,<3.0` in `requirements.txt`. Third time this
regression has been fixed. Root cause (likely a branch merge source) still not
identified — whoever next merges a partner branch should grep for `pydantic==` before
committing.

### Pre-fix 4: Protected wrapper role check — DONE
`main.tsx`'s generic `Protected` component now checks `getRole() === 'teacher'` in
addition to `isLoggedIn()`, matching the pattern `StudentProtected`/`ParentProtected`/
`InstituteProtected` already used. A logged-in student/parent/institute-admin no
longer loads teacher-only page shells at `/schedule`, `/students`, `/create-test`,
`/attendance`, `/payments`; they redirect to `/login` instead.

### Item 0: MCQ generation → teacher-authored questions — DONE
The `mcq_auto` test type is kept. The LLM call is gone.

**What changed:**
- `backend/app/services/mcq_gen.py` — **deleted**.
- `backend/app/routers/tests.py` — `create_mcq_test` now accepts
  `{title, duration_minutes, batch, questions: [{text, option_a, option_b, option_c, option_d, correct_option}]}`
  from the teacher directly. Server-side validates `correct_option ∈ {a,b,c,d}` and
  returns 400 on any invalid question (no silent bad data). `questions_created` in
  response (was `questions_generated`). Removed `generate_mcqs` import.
- `backend/app/schemas.py` — new `QuestionIn` schema. `TestCreateAuto` rewritten
  (dropped `topic`, `num_questions`; added `questions: List[QuestionIn]`, `batch`).
  `TestOut` dropped `topic`, gained `batch`. `TestCreateDocument` gained `batch`.
- `backend/app/models.py` — `Test.topic` and `Test.num_questions` columns removed;
  `Test.batch` (nullable) added.
- `webapp/src/api/client.ts` — new exported `QuestionIn` interface; `createMcqTest()`
  payload type updated to match; `createDocumentTest()` gains optional `batch`.
- `webapp/src/pages/CreateTest.tsx` — MCQ form is now a question-builder: add/remove
  questions, text + 4 options per question, OMR radio bubble marks correct answer.
  "MCQ (auto-generated)" tab label is now just "MCQ". Both forms have an optional
  `batch` field. Analytics panel preserved, unchanged.

### Item 0b: Remove anthropic_api_key — DONE
- `database.py` — `anthropic_api_key` field removed from `Settings`.
- `requirements.txt` — `anthropic==0.39.0` removed.
- `.env.example` — `ANTHROPIC_API_KEY` block removed.

### Item 4 partial: Test batch-scoping bug — DONE
`list_available_tests` now filters by `Test.batch IS NULL OR Test.batch == student.batch`.
Tests with `batch=NULL` remain visible to all students (institute-wide). A test with a
batch set is only shown to students whose `Student.batch` matches. Teachers can set
`batch` on both MCQ and document tests at creation time. The `Test.batch` column is
new (migration 0006).

**Migration 0006** (`0006_remove_topic_num_questions_add_batch_delete_llm_tests.py`):
- Drops `tests.topic` and `tests.num_questions`.
- Captures IDs of `mcq_auto` tests with non-null `topic` (i.e. LLM-generated), deletes
  their `Question` rows, their `TestAttempt` rows, then the `Test` rows themselves —
  per A1 (delete, not keep).
- Adds `tests.batch` (nullable).
- **Run `alembic upgrade head` before starting the backend** — without it, SQLAlchemy
  will fail on the missing/extra columns at startup.

### Verified
- `py_compile` clean on all changed/new backend Python files.
- Full `from app.main import app` smoke test with SQLite: all 51 routes registered
  correctly, no import errors.
- `tsc --noEmit -p tsconfig.json` clean — zero errors.
- `vite build` clean — 6.39kB CSS, 262.70kB JS, no build errors.

### Not done / open items for next session
- **Run `alembic upgrade head`** on the real dev DB (migration 0006 not yet applied).
- No visual QA of the new question-builder UI — `npm run dev` and check the MCQ form
  in a real browser before building more test-authoring features on top.
- Pre-fix 2's lenient fix protects single-institute deployments fully; the strict
  version (requiring `institute_id` always) and the full email-auth migration (HANDOFF
  scope-decisions item 1) are still deferred.
- `TestAnalytics` shows `attempt_count`/`average_score` correctly, but now that the
  MCQ form is the teacher-authored question-builder, the existing analytics `questions`
  list will correctly show per-question text from the teacher's own authored questions
  (not placeholder text anymore) — worth a manual check once a real test is created.
- The remaining scope-decisions items (2 OTP subsystem, 3 My Profile, 5 scheduling
  robustness/recurrence, 6 iOS) are all still open.
- The subscription/billing model - implemented in the "subscriptions + student fee payments" session at the bottom of this file.
- Manual Intervention Required items at the top of this file remain unresolved.

## Failed approaches
*(No new failed approaches this session. The only non-trivial stumble was writing
`CreateTest.tsx` via PowerShell here-strings, which mangled single-quote escaping
throughout the file and caused 100+ tsc errors. Fixed by writing via the editor tool
directly instead. The broken intermediate state was replaced before commit.)*

---

## Follow-up session: design system + nav shell

**Tasks asked for:** Implement the UI Design & Layout Spec (approved sections 1, 2, 4, 5).
Section 3 (content layout) explicitly rejected/deferred — not touched.

### What changed

#### `webapp/index.html`
- Added **Cinzel** (wght@400;700) to Google Fonts (Castellar dropped — Monotype trademark).
- Added inline `<script>` before React loads that reads `localStorage.getItem('wandor_theme')`
  and applies `data-theme="dark"` to `<html>` if set — prevents white flash on dark users.

#### `webapp/src/index.css` — full rewrite
- **New core tokens:** `--paper #eee9e0`, `--ink #141414`, `--signal-red #c1272d`,
  `--ink-blue #1f3f8f`, `--surface #f7f4ec`, `--paper-line #d8d2c4`, `--muted #6b6656`.
- **`--radius: 0`** throughout (hard edges, no soft border-radius anywhere).
- **`--accent` is now `--signal-red`** (was `--ink-blue`). Primary buttons are red.
- **Dark mode block** (`[data-theme="dark"]`): flips all palette tokens. Nav vars are
  NOT in this block — nav is always `#141414` regardless of mode.
- **Nav is now always dark.** Added `--nav-bg: #141414`, `--nav-text`, `--nav-text-active`,
  `--nav-text-hover` as separate non-flipping tokens.
- **Bottom tab bar** (`.bottom-tab-bar`): new CSS, `display: none` on desktop, `display: block`
  on `<640px`. Signal-red top border, active tab gets red `border-top` and red text.
- **Backward-compat aliases:** `--rule → --paper-line`, `--stamp-red → --signal-red`,
  `--ink-blue-deep`, `--highlight`, `--highlight-ink` kept so existing page classes still work.
- **Button hierarchy:** primary=red fill, `.btn-secondary`=ink fill (new), `.btn-ghost`=transparent,
  `.btn-danger`=red outline (fills on hover, distinct from solid primary).
- **OMR bubble** fill updated to `--signal-red` (was `--ink-blue`). Border transitions to red
  on check. Focus ring is red.
- **WCAG touch targets:** `min-height: 44px` on buttons, `52px` on bottom-tab.

#### `webapp/src/components/Layout.tsx` — full rewrite
- Removed `useNavigate` (unused after logout path changed to `window.location.href`).
- `TEACHER_LINKS` — 5 entries with explicit `end` prop. Same routes as before.
- `INSTITUTE_LINKS` (new) — 4 entries: Institute + Teachers (both `/institute` for now,
  distinct routes planned for a future session), Students + Analytics (disabled, `to: null`).
- `NavItem` union type enforces that disabled items have `to: null`, enabled items have `to: string`.
- Desktop: `<nav className="nav">` with dark bar, brand mark left, `.nav-links` centered,
  `.nav-logout` button right. Disabled tabs render as `<span className="nav-tab-disabled">`.
- Phone: same top bar shows only brand mark (wordmark hidden via CSS). Below content,
  `.bottom-tab-bar` renders role tabs. Disabled tabs rendered as non-interactive `<span>`.
- Student and Parent roles: `getLinks()` returns `[]`, so no tab bar renders at all.
  Top bar shows only brand mark + logout.

#### `webapp/src/pages/TakeTest.tsx`
- Removed all `className="page"` from outer divs — TakeTest is now truly full-bleed.
- Loading/submitted states use inline flex centering, no `.page` cap.
- MCQ variant has its own modest 720px cap inline — wider than the content-layout column
  since answer options benefit from more width during reading.

#### `webapp/src/api/client.ts`
- Added `setTheme(dark: boolean)` and `isDarkTheme(): boolean` exports.
  `setTheme` writes to `localStorage` AND sets the `data-theme` attribute live.
  Ready for the Settings page to call — no other wiring needed.

### Dark-mode toggle approach
The toggle lives in a future Settings page (not yet built). The mechanism is already
complete: `setTheme(true/false)` in client.ts + index.html flash-prevention script +
`[data-theme="dark"]` CSS block. When Settings ships, it calls `setTheme` on a toggle flip.

### Institute admin disabled tabs
Students and Analytics tabs shown greyed out (`opacity ~20%`, `cursor: not-allowed`).
Both Institute and Teachers currently point to `/institute` (one page). This is a known
limitation documented in the Layout comment — each tab gets its own route as features land.

### Verified
- `tsc --noEmit` clean.
- `vite build` clean — 8.70kB CSS (up from 6.39kB, new CSS), 263.56kB JS.

### Not done / still open after this session
- **Section 3 (content layout)** — explicitly deferred. The `.page` 640px cap is still in
  place as a stopgap. Needs a fresh proposal before implementation.
- **Ribbon component** — mentioned in spec section 4, not built. No concrete screen to attach
  it to yet. Build it when a page with a "topper" or "overdue" hero moment ships.
- Visual QA in a real browser — `npm run dev`, resize window, check: dark top bar, red underline
  on active link, phone width shows bottom tab bar not desktop links, teacher only sees 5 tabs,
  institute admin sees Institute + Teachers active + Students + Analytics greyed out.
- All previous open items from the prior session remain open.

---

## Follow-up session: Settings page + password change

**Commit:** `52efb022`
**Tasks asked for:** Settings page (dark mode toggle, profile display, change password). Teacher profile display confirmed to include name + phone via a new GET /auth/me endpoint.

### What changed

#### `backend/app/routers/auth.py`
- **New imports:** `OAuth2PasswordBearer` (for the generic bearer scheme), `_decode` and `get_current_teacher` from `auth.py`, `PasswordChange` and `TeacherProfile` from `schemas.py`, `settings` from `database`.
- **`_any_bearer`** — a generic `OAuth2PasswordBearer(auto_error=False)` used by the change-password endpoint so it accepts tokens from any role without committing to a specific `tokenUrl`.
- **`GET /auth/me`** — teacher-only (enforced by `get_current_teacher`). Returns `{ id, name, phone, institute_id }`. Students/parents/institute-admins each have their own `/me` endpoints elsewhere.
- **`POST /auth/change-password`** — role-agnostic. Decodes the JWT directly via `_decode` to get `(sub, role)`, then looks up the right DB model (`Teacher`/`Student`/`Institute`). Verifies `old_password`, hashes and saves `new_password`. Returns `{"ok": true}`. Parent tokens get a 403 (parents have no self-managed password — PIN is teacher-set).

#### `backend/app/schemas.py`
- **`TeacherProfile`** — response model for `GET /auth/me`: `id`, `name`, `phone`, `institute_id`.
- **`PasswordChange`** — request body for `POST /auth/change-password`: `old_password`, `new_password`. `model_post_init` validator rejects `new_password` shorter than 8 chars at the Pydantic layer (before the handler runs).

#### `webapp/src/api/client.ts`
- **`getMyProfile()`** — `GET /auth/me`, teacher-only. Returns `{ id, name, phone, institute_id }`.
- **`changePassword(old, new)`** — `POST /auth/change-password`. Void return; throws on error (caller catches and surfaces the `detail` string).

#### `webapp/src/pages/Settings.tsx` — NEW
Three sections, all behind `<Layout>` (so the dark nav bar and gear button are present):
1. **Appearance** — checkbox styled as a pill toggle. `checked` reads `isDarkTheme()`. `onChange` calls `setTheme(next)` and syncs local `dark` state. The CSS transition on the checkbox background (paper-line → signal-red) is handled entirely inline.
2. **Profile** — teacher: fetches `getMyProfile()` on mount, shows name + phone in read-only fields. Student: "coming soon" placeholder. Institute admin: links to `/institute`. Parent: "linked to child's record" message.
3. **Change password** — hidden for parent role. Three inputs (current / new / confirm). Client validates: new ≥ 8 chars, new === confirm. On submit calls `changePassword()`. Success: clears form + shows "✓ Password changed." error: surfaces backend `detail` string.

#### `webapp/src/components/Layout.tsx`
- Added `useNavigate` to the import (was removed last session — needed for future use; harmless now).
- Added `<NavLink to="/settings" className="nav-logout" title="Settings">⚙</NavLink>` left of the logout button. Uses the same `.nav-logout` style so it sits quietly in the dark bar.

#### `webapp/src/main.tsx`
- Added `import Settings from './pages/Settings'`.
- Added **`LoggedInOnly`** guard: redirects to `/` if `!isLoggedIn()`, passes through for any role.
- Added `<Route path="/settings" element={<LoggedInOnly><Settings /></LoggedInOnly>} />`.

### Verified
- `py_compile` clean on `auth.py` and `schemas.py`.
- Backend smoke test: `/auth/me` and `/auth/change-password` both appear in route list (53 routes total).
- `tsc --noEmit` clean.
- `vite build` clean — 107 modules, 267.97kB JS.

### NOT tested (untested changes — verify manually before relying on)
- **Dark mode toggle visual** — the checkbox pill toggle uses `appearance: none` + inline styles. It renders correctly in modern browsers but has not been visually confirmed. Check: does the pill slide and colour change on toggle? Does the page actually go dark?
- **`GET /auth/me` against real Postgres** — smoke test only confirmed the route registers. Not tested with a live DB or a real teacher JWT.
- **`POST /auth/change-password` against real Postgres** — same. Confirmed route registers; end-to-end (wrong password rejection, correct password acceptance, hash update persisted) not tested live.
- **Settings page for non-teacher roles** — the student/parent/institute_admin branches in the Profile section are placeholders. They render but haven't been logged in as those roles and verified.
- **Gear button on phone** — `⚙` appears in the top strip (always visible). Haven't confirmed it doesn't overflow or crowd the brand mark on small screens.

### Still open
- All items from the design system session remain open.
- My Profile screen with photo upload and completion progress bar (deferred — needs storage design).
- Content layout (section 3) — still rejected/pending rework.


## Follow-up session: subscriptions + student fee payments

Two separate money flows, deliberately kept apart:
1. **SaaS subscription** - institutes and independent teachers pay the platform (Razorpay Subscriptions).
2. **Student fees** - students pay their own institute/teacher (Razorpay Orders + Route transfers).

### Subscription model (backend/app)
- `plans.py` is the ONLY place limits/features/prices live. Tiers: free (25 students, 1 teacher, no online fee collection), basic, pro (unlimited students). **Prices are placeholders** and only affect what the UI displays - the charge amount comes from the Razorpay Plan.
- `Subscription` table: exactly one owner - `institute_id` OR `teacher_id` (CHECK constraint + unique per owner). An institute-affiliated teacher is never their own payer. No row = Free.
- `services/subscriptions.py::effective_plan()` decides entitlement in one place: trialing/active/past_due/cancelled rules + `BILLING_GRACE_DAYS`. Never read `Subscription.plan` directly for gating.
- Limits only block ADDING (students via POST /students, bulk import [skips + reports rows over cap], POST /institute/students, POST /institute/teachers, join-institute). Over-limit existing data is never touched. Plan-limit errors are HTTP 402 with a plain-string `detail`, so every existing page already displays them.
- New signups get a `TRIAL_DAYS` (14) Pro trial at OTP verification (`start_trial`). Existing accounts have no row -> Free (grandfathered, nothing removed).
- `routers/billing.py`: GET /billing/plans (public), /billing/me, POST /billing/subscribe | verify | cancel | change-plan. Only an independent teacher or institute admin can manage; an institute's teachers see the plan read-only (`get_billing_actor` in auth.py).
- Cancel = at cycle end. Change-plan = at next renewal only (no mid-period proration/upgrade-now yet).
- Subscribing during a trial (or after cancelling paid time) sets `start_at` so nobody is charged for time they already have.
- Ownership of a Razorpay subscription comes from the `notes` we attach at creation, never from client input; /billing/verify also checks the signature AND that the notes match the caller.

### Student fees (routers/payments.py, rewritten)
- Before this session NOTHING created a FeeRecord and students had no fee UI. Now: POST /payments/fees (whole batch or specific students), GET /payments/records (with student names), POST /payments/fees/{id}/mark-paid (cash/UPI), DELETE (unpaid only), GET /payments/payout-status; student side: GET /payments/my-fees, POST /payments/create-order, POST /payments/verify.
- Money routing: `create-order` adds a Route `transfers` entry to the owner's linked account (`Institute.razorpay_account_id`, or `Teacher.razorpay_account_id` for independent teachers), minus `FEE_PLATFORM_COMMISSION_BPS`. **Fee money is never routed to the platform account** - with no linked account (or a plan without `online_fee_collection`) online payment is refused with 409 and the student sees "pay your teacher directly".
- Linking an account is an operator action: `python -m scripts.set_payout_account --institute-phone ... --account-id acc_...` (verifies the account with Razorpay first). Not self-serve on purpose - whoever can set it controls where fee money goes.
- Open orders are reused instead of minting a new order per tap.
- ONE webhook (`POST /payments/webhook`) handles both `subscription.*` and `payment.captured`/`order.paid`. Signature-verified; **refuses (503) if RAZORPAY_WEBHOOK_SECRET is empty** (an empty HMAC key is forgeable); `webhook_events` table makes redelivery idempotent. Subscription events re-fetch the current state from Razorpay rather than trusting the payload snapshot.

### Migration / env / packages
- Migrations `0013` (subscriptions, webhook_events, `razorpay_account_id` on institutes+teachers, fee_records.description/payment_mode/created_at) and `0014` (fee_records.duplicate_payment_id). Verified on a real PostgreSQL 16: up -> down -> up, `alembic check` reports zero drift vs models.py, and the one-owner CHECK constraint is enforced. NOT yet run on your production DB. **See the warning below about the older migration chain.**
- New env: RAZORPAY_PLAN_{BASIC,PRO}_{MONTHLY,YEARLY}, TRIAL_DAYS, BILLING_GRACE_DAYS, FEE_PLATFORM_COMMISSION_BPS (see .env.example).
- requirements.txt: added `setuptools<81` (razorpay 1.4.2 imports pkg_resources).

### Frontend (webapp/src)
- New `pages/Billing.tsx` at /billing (teacher + institute_admin; linked from Settings and the institute dashboard). New `lib/razorpay.ts` Checkout helper.
- `Payments.tsx` rewritten: add fees to a batch/student, names instead of UUIDs, paid/unpaid filter, mark paid, delete, payout-status banner. `StudentHome.tsx` gained a Fees section with Pay now.

### To go live (checklist)
1. Razorpay dashboard: create 4 Plans (amount/period matching plans.py), paste the plan_ ids into env; blank = not purchasable.
2. Razorpay dashboard: webhook -> `<backend>/payments/webhook`, events: payment.captured, order.paid, **refund.processed** (added in Phase 3 - without it refunds never update the app), subscription.activated/charged/pending/halted/cancelled/completed. Set RAZORPAY_WEBHOOK_SECRET.
3. Enable **Route** on the Razorpay account, then create + KYC each institute's/teacher's linked account and run set_payout_account.
4. `alembic upgrade head` on production.
5. Decide real prices/limits in plans.py.
6. **(added Phase 3)** Meta Business Manager: create + get approved the WhatsApp templates `fee_created` (4 variables) and `payment_receipt` (4 variables) - exact variables in the Phase 3 entry. Until approved, fee/receipt notices fall back to SMS (costs money).
7. **(added Phase 1)** Set `FEE_PLATFORM_COMMISSION_BPS` (0 = every online fee payment costs you Razorpay's fee; a startup warning logs this). Rate limits: `RATE_LIMIT_*` in `.env.example`.
8. `alembic upgrade head` now also applies `0015` (fee payment ledger + backfill) - see Phase 3.

### Verification actually done
- `python -m tests.test_billing_flow` - 13 end-to-end tests with a FAKE Razorpay client, passing on both SQLite and PostgreSQL 16 (`TEST_DATABASE_URL=postgresql+psycopg://... python -m tests.test_billing_flow`). Covers trial, caps, subscribe/verify/webhook/idempotency, cancel, change-plan, fee routing payload, cross-tenant access, odd webhooks. Deliberate mutations (remove student cap, wrong payout account, grant access on pending) each made the suite fail, and the 4 review-round gaps below each FAILED before their fix.
- Frontend: `tsc --noEmit` clean, `vite build` succeeds.
- **NOT verified**: any call to the real Razorpay API (Subscriptions, Route transfers, `subscription.edit` with `schedule_change_at`), the Checkout popup, or a real webhook. First test-mode run against real Razorpay keys is the next step.

### Still open / known gaps
- Route onboarding is manual (no self-serve KYC flow / bank-detail capture).
- No proration or "upgrade now"; no invoice list; no GST invoices for subscription charges. **[STILL OPEN - billing Phase 4]**
- No platform-admin panel (payout accounts, comps/overrides are CLI/DB only).
- A teacher who joins an institute must cancel their personal subscription first (enforced), but their old Subscription row is left in place.
- Partial fee payments aren't supported (a fee is paid in full or not at all). **[DONE in billing Phase 3]**


### Review round 2 (gap audit) - found, reproduced with a failing test, then fixed
1. **Double subscription during a trial.** Subscribing mid-trial defers the first charge (Razorpay status `authenticated`), which was not recorded, so the UI showed nothing and the customer could subscribe again = two live subscriptions. Now the pending subscription is linked (shown as "starts after trial", cancellable, a second subscribe is a 409).
2. **Old subscription kept charging.** When a new subscription activated over an old one, the old Razorpay subscription was never cancelled. Now cancelled best-effort after commit (`cancel_superseded`; failure logs `SUPERSEDED_SUBSCRIPTION_NOT_CANCELLED` - cancel it in the Razorpay dashboard).
3. **Failed-payment dead end.** A halted (past_due) subscription blocked re-subscribing and the UI offered nothing. Now allowed ("Start new subscription"); cancelling a past_due/pending subscription cancels immediately.
4. **Orphaned fee payments.** Two open orders for one fee (double-tap / two devices) left the earlier order's payment unmatched. Webhook + verify now fall back to the order's `receipt` (= fee id), guarded so a non-UUID receipt can't crash Postgres.
5. **Silent double payment.** Cash recorded while the student's online order was still open -> second payment ignored. Now stored in `fee_records.duplicate_payment_id`, logged as `DUPLICATE_FEE_PAYMENT`, and shown to the teacher as "Paid twice - refund needed" (**Phase 3: now "Overpaid - refund needed", covers any money beyond what is owed, and clears itself when the refund completes**).
6. Billing UI no longer claims "You're on Pro" when Razorpay hasn't confirmed the charge yet (UPI lag).

### WARNING: the older migration chain does not run on an empty PostgreSQL
`alembic upgrade head` from scratch fails at 0001 (enum `classstatus` created twice; needs `create_type=False`) and again at 0005 (UUID/String foreign-key mismatch), and there are probably more. It only "works" on SQLite. Production must have been created some other way (`create_all` + stamp?). I did not repair history. Do NOT rely on a from-scratch `alembic upgrade head` on a new Postgres until that is fixed; for an existing DB at 0012, `alembic upgrade head` applies 0013+0014 (verified above).

### Decisions still yours (business/planning, not code bugs)
- **Gateway cost on fee payments.** Razorpay's fee on each student fee payment is charged to the PLATFORM, and with `FEE_PLATFORM_COMMISSION_BPS=0` the institute gets 100% - so every fee payment costs you money. Set a commission (or pass the fee on) before enabling online fees. Refunds also come out of the platform's Razorpay balance unless refunded with `reverse_all`.
- **GST.** Subscription prices should be GST-inclusive or GST added on top; decide, and issue invoices. Note UPI Autopay debits above Rs 15,000 need the customer's PIN each time (Razorpay docs), so a GST-inclusive yearly price over that will see more failed renewals; the Pro yearly placeholder (Rs 14,990) sits just under it.
- **[DONE in billing Phase 2]** **Parents can't pay.** The parent portal shows fees but has no Pay button, and for minors the parent is usually the payer. Adding it = reuse create-order/verify behind `get_current_parent`. Recommended next.
- **[DONE in billing Phase 3: refund webhook, receipts, fee-created notice, partial payments. Refunds are still ISSUED from the Razorpay dashboard.]** **Refund handling is manual** (no refund webhooks / status reversal), and there are no fee receipts, no notification when a fee is created, no partial payments.
- **[DONE in billing Phase 1]** **Free plan still sends fee-reminder WhatsApps** (each costs money) - gate it if that matters.
- **[DONE in billing Phase 1 for create-order, subscribe, change-plan; verify endpoints and the rest of the app are still unlimited]** No rate limiting on create-order / subscribe (project-wide gap, not specific to billing).
- Deleting an unpaid fee while a student's order is open would orphan that payment (logged as `ORPHAN_FEE_PAYMENT`).


---

## Follow-up session: billing Phase 1 - harden what exists

**Plan:** billing work is split into 5 phases (1 harden, 2 parent pays, 3 fee lifecycle,
4 subscription completeness, 5 go live). This entry is Phase 1. Each phase ends with tests,
`tsc`, `vite build` and a HANDOFF entry.

**Asked for:** rate limit `create-order` and `subscribe`; gate fee-reminder WhatsApps on Free;
decide the platform commission.

### 1. Rate limiting - DONE
- New `app/ratelimit.py`: sliding-window limiter, keyed by the caller's **verified JWT subject**
  (falls back to client IP only when there is no valid token). Per person, so a whole coaching
  centre behind one IP is never throttled together. Over limit -> HTTP 429, `Retry-After` header,
  plain-string `detail` (existing pages already render it).
- Applied to: `POST /payments/create-order` (10/min per student), `POST /billing/subscribe` and
  `POST /billing/change-plan` (5/min per account, separate bucket each). `change-plan` was added
  beyond the ask because it also calls Razorpay.
- Settings (`database.py`, `.env.example`): `RATE_LIMIT_ENABLED` kill switch,
  `RATE_LIMIT_PAYMENT_PER_MIN`, `RATE_LIMIT_BILLING_PER_MIN`. `0` = unlimited for that bucket.
- **Limitation:** counters live in process memory. N workers/instances = up to N x the limit.
  Fine on one instance; move to Redis before scaling out. Memory is bounded (stale keys purged
  past 20k keys).
- Not covered: `/billing/verify` and `/payments/verify` (signature-checked, no Razorpay create
  call), and every non-billing endpoint (login, OTP) - project-wide rate limiting is still open.

### 2. Free-plan fee reminders gated - DONE
- `plans.py`: new feature flag `fee_reminders` (Free = False, Basic/Pro = True; trial = Pro so
  trialing owners get them). Exposed as `fee_reminders` on `GET /billing/plans` and
  `GET /billing/me`.
- `services/fee_reminders.py`: per fee, resolve the owner and check the flag (one lookup per
  owner per pass). Skipped fees are NOT touched (`last_reminder_sent_at` unchanged), so they
  resume the day the owner upgrades. Summary gained `skipped_plan`. A student with no owner
  is treated as not entitled.
- `POST /payments/send-reminders-now`: Free owner now gets HTTP 402 with a plain message
  instead of a silent "sent 0". The daily cron just skips them.
- Frontend: `Payments.tsx` shows the 402/429 message next to the button (the old handler had
  no catch, so an error would have shown nothing) plus a "skipped" count; `Billing.tsx` shows
  "Fee reminders on/off" and per-plan reminder line; `client.ts` types updated.
- Behaviour change to know about: existing Free-plan users stop receiving reminders on deploy.

### 3. Commission - NOT DECIDED, left at 0
- You did not give a number, so `FEE_PLATFORM_COMMISSION_BPS` stays 0. Razorpay's fee on every
  online fee payment is charged to the platform, so at 0 each online payment costs money.
- Added: a startup WARNING log when a Razorpay key is set and commission is 0, and a comment
  in `.env.example`. Verified it fires at 0 and stays silent at 200.
- **Open decision:** pick a value covering Razorpay's fee + GST on that fee before enabling
  online fees for real institutes. Code already clamps to 0-5000 bps.

### Verified
- `python -m tests.test_billing_flow`: 19 pass (13 old + 6 new, SQLite, fake Razorpay).
  New: create-order limit (per-user, kill switch, 0 = unlimited), blocked call makes no
  Razorpay request, subscribe/change-plan limits with separate buckets, forged tokens don't
  get private buckets, Free skipped then reminded after upgrade + dedupe + trial + institute
  mix, plan catalog exposes the flag.
- Mutation-checked: removing the limiter from create-order, removing it from subscribe,
  removing the reminder gate, removing the manual-endpoint 402 each made the suite fail.
- `tsc --noEmit` clean, `vite build` clean. `py_compile` clean on all edited backend files.
- No migration needed (no schema change).
- **NOT verified:** Postgres run of the new tests (only SQLite this session), real
  WhatsApp/Razorpay, or the UI in a browser.

### Still open after Phase 1
Phases 2-5 and the commission decision. (Phase 2 is the next entry below.)


---

## Follow-up session: billing Phase 2 - parents can pay

**Asked for:** let a parent pay their child's fees from the parent portal (the biggest gap in
the original handoff: a parent was the likeliest payer but had no Pay button).

### What was built - DONE
- **No duplicated payment logic.** `routers/payments.py` now has three shared helpers that
  take the `Student` the caller is scoped to: `my_fees_for`, `create_order_for`,
  `verify_payment_for`. The student routes (`/payments/my-fees`, `/create-order`, `/verify`)
  are thin wrappers over them - behaviour unchanged (all 19 earlier tests still passed right
  after the refactor, before any parent code existed).
- **New parent routes** in `routers/parents.py`, parent token only:
  - `GET  /parents/my-fees` - fees (with description/paid-on) + `online_payment_available`
  - `POST /parents/create-order` - own rate-limit bucket `parent-create-order`, same
    `RATE_LIMIT_PAYMENT_PER_MIN` setting
  - `POST /parents/verify`
  - The old `GET /parents/fees` is kept untouched for compatibility; the dashboard no longer
    uses it.
- **Who can touch what:** a parent token resolves (via `get_current_parent`) to exactly one
  child, so only that child's fees are reachable. A student/teacher/no token on parent routes
  -> 401; a parent token on the student's `/payments/*` routes -> 401.
- Money flow is identical to a student paying: Route transfer to the institute/teacher's linked
  account minus commission, same idempotent mark-paid, same webhook, same duplicate-payment
  flag. Parent and child tapping Pay on the same fee reuse the one open order.
- **Frontend:** new shared `components/PayableFees.tsx` (fee cards + Checkout flow) used by BOTH
  `StudentHome.tsx` and `ParentDashboard.tsx`. Parent Checkout description is prefixed with the
  child's name. `client.ts`: `getChildFeesPayable`, `createParentPaymentOrder`,
  `verifyParentFeePayment`.
- UI changes you will notice: the parent fee list is now cards (same as the student's), not a
  table, so the separate "Amount paid" column is gone; offline hint reads "Pay the teacher
  directly" (was "Pay your teacher directly" on the student page).

### Verified
- `python -m tests.test_billing_flow`: **25 pass** (19 + 6 new, SQLite, fake Razorpay). New:
  full parent pay flow incl. webhook-after and no duplicate flag; cross-family isolation (can't
  create an order for or verify a payment against another child's fee, even a validly signed
  one); wrong-role matrix; Free plan / no payout account -> 409 and `online_payment_available`
  false; separate rate-limit bucket; legacy `/parents/fees` still works.
- Mutation-checked: removing the ownership check in verify, dropping the student filter in
  create_order_for, removing the parent rate limit, and swapping parent auth for student auth
  each made the suite fail.
- `tsc --noEmit` clean, `vite build` clean. No migration (no schema change).
- **NOT verified:** UI in a browser; a real Razorpay Checkout opened from the parent page;
  Postgres run of the new tests.

### Known limits / left for later
- No record of WHO paid (parent vs student) - `payment_mode` is just "online". Phase 3 receipts
  would be the place to add it if wanted.
- Parent still cannot see receipts, or pay part of a fee (Phase 3).
- The parent's phone is not prefilled in Checkout (kept identical to the student flow rather
  than add an unverified Razorpay field).

### Still open after Phase 2
Phases 3-5 and the commission decision. (Phase 3 is the next entry below.)


---

## Follow-up session: billing Phase 3 - fee lifecycle

**Asked for:** fee-created notice, receipts, refund webhooks, partial payments (all four in
one phase; partial payments was the big one).

### The foundation: a payment ledger - DONE
- New table `fee_payments` (model `FeePayment`): one row per payment or payment attempt.
  `status` pending|paid, `amount_paise` and `refunded_paise` (integers, exact), `mode`
  online|manual, Razorpay order/payment ids, `paid_by` student|parent|teacher.
- `FeeRecord.amount_paid / is_paid / paid_at` are now a **cache** of the ledger. The ONLY code
  allowed to change them is `services/fee_ledger.py` (`capture`, `record_manual`,
  `apply_refund`, `recompute`). Do not set them by hand anywhere else.
- Every Razorpay order we create now gets a `pending` ledger row, so the amount and who opened
  it are known when the payment lands. `_payment_for_order` finds it (row locked on Postgres);
  orders with no row (made before this deploy) fall back to the order's `receipt` = fee id.
- Overpayment is never swallowed: if net received exceeds what is owed (stale order paid,
  online payment after cash, etc.) `duplicate_payment_id` is set; it **clears itself** when
  refunds bring the net back down. UI label is now "Overpaid - refund needed".
- **Migration `0015`** adds the table and `fee_records.allow_partial` (default false) and
  backfills one `paid` ledger row per fee that has money on it. A fee already flagged duplicate
  keeps the flag but gets no ledger row (the extra amount was never recorded); a refund of that
  payment still clears the flag.

### 1. Partial payments - DONE
- Teacher sets "Let them pay in instalments online" per fee (`allow_partial`). Default is
  pay-in-full, exactly as before.
- `POST /payments/create-order` and `/parents/create-order` take optional `amount`. Rules: only
  if `allow_partial`; <= balance; >= Rs.1; and the leftover must be 0 or >= Rs.1 (Razorpay's
  minimum, so no unpayable crumbs). Open orders are reused only for the same amount. The Route
  transfer and commission are computed per instalment.
- Teacher can ALWAYS record a part-payment by hand: `POST /payments/fees/{id}/mark-paid` takes
  optional `{amount}` (no body = whole balance, unchanged).
- Fees with money received can't be deleted (400). Abandoned checkout rows go with the fee.
- Reminders keep working: a part-paid fee is still unpaid, reminded for the remaining amount.

### 2. Receipts - DONE
- `GET /payments/receipts/{id}` (teacher, own students), `/payments/my-receipts/{id}` (student),
  `/parents/receipts/{id}` (parent's child). 404 for anyone else and for unpaid attempts.
- Receipt number is derived from the payment id (`R-` + 10 chars), nothing extra stored.
  New printable page `/receipt/:paymentId` (print / save as PDF). Receipt links appear on the
  student, parent and teacher fee lists. Fee lists now show each payment, who paid
  (`paid_by` = whoever completed Checkout, not whoever opened the order), and refunds.

### 3. Refund webhook - DONE
- Handles `refund.processed`. Takes the payment's **cumulative** `amount_refunded` from Razorpay
  (`payment.fetch`) rather than adding the event amount, so replays and multiple partial
  refunds converge. If Razorpay can't be reached it answers **503** (nothing committed, so
  Razorpay retries). Refund total is clamped to the payment amount.
- A refund puts the fee back to unpaid if it drops below what is owed (`paid_at` cleared,
  reminders resume, payer can pay again). Refunds are still ISSUED from the Razorpay dashboard;
  there is no refund button in the app.
- **You must add `refund.processed` to the events ticked on the Razorpay webhook.**

### 4. Fee-created notice + receipts by message - DONE (gated, unverified live)
- `services/fee_notices.py`: "new fee" notice on fee creation, receipt message on every received
  payment (online or recorded by hand), to student and parent. Runs as FastAPI background tasks
  after the response and commit, in its own DB session: a failing provider can never fail or slow
  a payment (tested). Receipts are sent once per payment even though verify and webhook both
  report it.
- Paid plans only, same `fee_reminders` flag as Phase 1 (label now "reminders & notices").
  **Free users get none.**
- `notify()` gained `template_params` (fills WhatsApp template body variables).
- **ACTION REQUIRED in Meta Business Manager** - create and get approved, with exactly these
  body variables, or WhatsApp rejects the message and it falls back to **SMS (costs money)**:
  - `fee_created`: {{1}} student {{2}} amount {{3}} due date {{4}} description or "-"
  - `payment_receipt`: {{1}} student {{2}} amount {{3}} receipt no {{4}} balance note

### Verified
- `python -m tests.test_billing_flow`: **36 pass** (25 old + 11 new). New cover: student then
  parent part-paying one fee, part-payment rules, manual part-payments + delete rules,
  abandoned orders, stale-order overpayment + flag clearing, refund idempotency/partial/full,
  refund edge cases (unknown payment, Razorpay down -> 503 then retry works, clamp, legacy flag),
  receipt content + isolation across student/parent/teacher, notices (Free silent, paid plan
  student+parent, exactly once, failing provider harmless), `paid_by`, and a messy mixed sequence
  where the cached totals are checked against the ledger after every step.
- `python -m tests.test_migration_0015` (SQLite): schema, backfill of online/manual/no-mode/
  duplicate fees, ledger == cached totals, downgrade, re-upgrade.
- Mutation-checked (each break made a test fail): capture idempotency, refunds in net, refund
  clamp, flag clearing, partial rule, leftover-under-Rs.1 rule, receipt scoping, delete-with-
  payments, refund 503, notice plan gate, verify ownership, `paid_by`; and in the migration
  the unpaid-fee filter, online/manual detection, paise conversion.
- `tsc --noEmit` clean, `vite build` clean.
- **NOT verified:** a real Razorpay order/refund; real WhatsApp/SMS; Postgres (the migration and
  `with_for_update` were only run on SQLite); the UI in a browser (Pay with amount box, receipt
  page, teacher "Record payment" prompt).

### Known limits / watch for
- Existing daily overdue reminder sends template `fee_reminder` with NO variables, so WhatsApp
  users see only that template's fixed text; amounts appear only in the SMS fallback. Not
  changed here.
- `/payments/verify` and `/parents/verify` still have no rate limit (Phase 1 note).
- Two payers racing partial orders can overpay; that is flagged, not prevented.
- Pending (abandoned) ledger rows accumulate; harmless, could be pruned later.
- Teacher "Record payment" uses a browser prompt box - functional, not pretty.

### Still open (next: Phase 4 - subscription completeness)
Upgrade-now/proration, invoice list, GST decision (inclusive vs on top). Then Phase 5 go-live
(migration chain on empty Postgres, real Razorpay test-mode run, checklist), plus the commission
decision from Phase 1.


---

## Follow-up session: billing Phase 4.0 - cheap fixes before Phase 4 proper

Phase 4 (subscription completeness) is being delivered in parts so a session that runs out of
budget still leaves a consistent repo + HANDOFF. Plan: **4.0** cheap fixes (this entry) -> **4.1**
GST + invoice table/migration -> **4.2** invoice list API (from `subscription.charged` webhook)
-> **4.3** upgrade-now with proration (backend) -> **4.4** Billing UI (invoices, upgrade-now,
"+ GST" copy). Each part ends with tests and its own entry here.

### Owner decisions recorded (from the planning chat; confirm if either has changed)
- **GST is added on top**: price shown as "Rs X + 18% GST". Store base, GST and total as separate
  columns on each invoice; proration runs on the BASE, GST is computed after.
- **Commission stays 0 for v1.** Razorpay's fee on each Route fee payment then comes out of the
  platform's side. Check the real deduction in the Phase 5 test-mode run before launch; a small
  `FEE_PLATFORM_COMMISSION_BPS` (e.g. 50) is the lever if it hurts.
- "Free plan" for reminder gating means trial expired / no paid plan (gating already goes through
  `effective_plan()`/`has_feature`, never a plan name).

### What changed
1. **Rate limit on the three verify endpoints** (`POST /payments/verify`, `POST /parents/verify`,
   `POST /billing/verify`). New setting `RATE_LIMIT_VERIFY_PER_MIN` (default 20, 0 = unlimited,
   covered by the existing `RATE_LIMIT_ENABLED` kill switch). Each endpoint has its own bucket, keyed
   by user id. Blocked calls never reach Razorpay. NOTE: the limiter falls back to
   `request.client.host` only for unauthenticated calls; these endpoints are all authenticated so
   Render's proxy IP is not an issue here, but it WILL be for login/OTP limiting (not done yet) -
   run uvicorn with `--proxy-headers --forwarded-allow-ips='*'` (or equivalent) when that is added.
2. **Overdue reminder amount** (`services/fee_reminders.py::reminder_template`). The old
   `fee_reminder` template has no variables, so WhatsApp users never saw the amount (SMS did). Now
   two settings: `FEE_REMINDER_TEMPLATE` (default `fee_reminder`) and `FEE_REMINDER_TEMPLATE_VARS`
   (default `false`). Default behaviour is unchanged on purpose - Meta rejects variables sent to a
   template that has none. **To actually fix it:** create+approve a Meta template (suggested
   `fee_reminder_v2`) with 4 body variables `{{1}} student {{2}} amount owed {{3}} due date
   {{4}} "was due"/"is due"`, then set `FEE_REMINDER_TEMPLATE=fee_reminder_v2` and
   `FEE_REMINDER_TEMPLATE_VARS=true`.
3. README: parent-login line was stale, fixed. (The other HANDOFF/README staleness reported earlier
   - `refund.processed` in the checklist, partial payments, "Overpaid", billing section - was already
   corrected in the Phase 3 files; re-checked.)

### Verified
- `python -m tests.test_billing_flow`: 38 pass on SQLite (36 before + 2 new). The older reminder
  test's notify stub was widened to accept the new `params` argument.
- Mutation checks, each restored and diffed afterwards: removing the parent-verify limit fails
  `test_verify_endpoints_are_rate_limited_...`; always sending template variables fails
  `test_overdue_reminder_whatsapp_variables_only_when_template_has_them`.
- NOT verified: a real WhatsApp send of the v2 template (needs Meta approval), Postgres run.

### Heads-up found while reading Razorpay docs (affects 4.3 and the EXISTING change-plan)
Razorpay's "Update a Subscription" API errors with "Subscriptions cannot be updated when payment
mode is UPI". `POST /billing/change-plan` calls `subscription.edit(...)`, so for customers who
authorised UPI Autopay it will currently return 502. Phase 4.3 must not depend on `subscription.edit`
succeeding; Phase 5's test-mode run must try change-plan with a UPI-authorised subscription.

### Stale copy in the zip
`wandor/wandor/` inside the uploaded zip is an OLDER duplicate of the whole repo (937-line HANDOFF).
It was not touched. Work happens in the outer `wandor/`; delete the inner copy when convenient.

---

## Follow-up session: billing Phase 4.1 - GST + invoice table, migration 0016, numbering

Foundations for invoices. **Nothing calls the new code yet** - no endpoint creates or lists invoices;
Phase 4.2 wires `issue_invoice()` to the `subscription.charged` webhook and adds the list API.
Owner decision applied: **GST is added on top** (18%), base/GST/total stored separately.

### What changed
1. **`services/invoices.py` (new)** - all the money rules in one place:
   - `gst_on_top(base)` -> (gst, total); `split_inclusive(total)` -> (base, gst); `price_breakdown(plan, cycle)`.
     Integer paise only. Rounding is half-up on the GST amount, so base + GST == total exactly. Backing GST
     out of a total returns the original base for every whole-paisa amount (checked for 0, 5, 12, 18, 28%).
   - `financial_year_label()` - April-March decided in **IST** (18:30 UTC on 31 Mar is already 1 Apr).
   - `next_invoice_number()` - `WND/2627/000001` (prefix/FY/6-digit seq, <= 16 chars as GST rules require).
     One row-locked counter per financial year; consecutive, restarts each FY, and a rolled-back issue gives
     its number back (number + invoice insert share one savepoint).
   - `issue_invoice(db, sub, plan=, cycle=, total_paise= | base_paise=, razorpay_payment_id=...)` - idempotent
     on `razorpay_payment_id` (webhook redelivery / webhook-vs-verify race returns the existing invoice, burns
     no number). **Pass `total_paise=` for a real Razorpay charge** (the invoice then matches the money that moved,
     even if prices or the rate change later). Pass `base_paise=` only for amounts WE compute (4.3 proration:
     proration on the BASE, GST after). Flushes, does not commit - the caller commits.
2. **`models.py`: `Invoice`, `InvoiceCounter`.** DB-level CHECKs: `total = base + gst`, amounts >= 0; UNIQUE
   `invoice_number` and `razorpay_payment_id`. Each invoice snapshots `gst_rate_bps`. `kind` (default
   `subscription`) lets 4.3 add `proration` invoices without a schema change. Invoices are append-only.
3. **Migration `0016_invoices_and_gst.py`** - two new tables, nothing altered, nothing backfilled. Charges made
   before this migration have **no invoice**.
4. **Plan catalog (`GET /billing/plans`)**: existing `price_monthly` / `price_yearly` are unchanged and are now
   documented as BASE rupees excluding GST. New fields: `gst_rate_percent`, `gst_monthly_paise`,
   `total_monthly_paise`, `gst_yearly_paise`, `total_yearly_paise`. Frontend untouched (new fields are additive;
   `Billing.tsx` still shows the base price with no "+ GST" - that copy is Phase 4.4).
5. **Settings**: `GST_RATE_BPS` (default 1800), `INVOICE_PREFIX` (default `WND`) in `database.py` + `.env.example`.
6. Tests: `test_migration_0015.py` now also drops the 0016 tables before replaying (the models include them) and
   no longer pins head to 0015. README: test list + GST pricing note.

### !! Razorpay Plans must now be created at base + GST
The charge amount comes from the Razorpay Plan, not from `plans.py`. With GST on top, the placeholder prices mean:
Basic Rs 588.82/mo (58882 paise), Rs 5,888.20/yr; Pro Rs 1,768.82/mo, Rs 17,688.20/yr. Use the `total_*_paise`
values from `GET /billing/plans` when creating the 4 Plans. **Pro yearly (Rs 17,688.20) is above Rs 15,000**, the
UPI Autopay no-PIN limit noted in section A - decide: lower the Pro yearly base to <= Rs 12,711 (so total <= Rs 15,000),
or accept a PIN on each yearly debit. Not changed, prices are placeholders.

### Verified
- `python -m tests.test_billing_flow`: **49 pass on SQLite** (38 before + 11 new). `python -m tests.test_migration_0015`
  and `python -m tests.test_migration_0016`: pass.
- **PostgreSQL 16.2** (real server): all 11 new tests pass, including a real-thread test
  (`test_concurrent_issuers_get_gap_free_unique_numbers_postgres_only`): 8 simultaneous issuers on a brand-new
  financial year get exactly 1..8, and 6 racing on the same payment produce one invoice and use one number.
  Migration 0016 up -> down -> up on Postgres, `alembic check` = "No new upgrade operations detected".
  Skipped automatically on SQLite. Run: `TEST_DATABASE_URL=postgresql+psycopg://... python -m tests.test_billing_flow`.
- Mutation checks (one guard broken at a time, originals restored and diffed): round-down GST, round-down split,
  ignoring IST, one global counter, re-raising on a lost race, no savepoint (number leaks), accepting a >16-char
  number, dropping the total CHECK, dropping UNIQUE on payment id - each made a test fail.
- NOT verified: `tsc` / `vite build` (frontend untouched), anything against real Razorpay.

### Found while running the suite on PostgreSQL (PRE-EXISTING, not caused by 4.1)
The untouched Phase 4.0 code fails **2 tests on Postgres** and passes them on SQLite:
`test_parent_cannot_touch_another_childs_fee` and `test_receipts_content_and_isolation`. Both send a malformed id
(`"nope"`) where a UUID is expected; SQLite just finds no row (404) but Postgres raises `DataError`, so the app
returns **500 instead of 404** for a malformed fee/payment id (seen on `POST /parents/create-order` and the receipt
route; other id-taking routes likely behave the same). Harmless to data, but fix it in Phase 5 (validate the id as a
UUID before querying, or catch `DataError` -> 404) and re-run the suite on Postgres. Everything else passes there.

### Stale copy in the zip (update)
The `wandor-phase3.zip` handed over contained a nested `wandor/wandor/` (an older duplicate repo, 83 files). The
`wandor-phase4_0.zip` did not. The 4.1 zip does not contain it either. If you ever see it again, delete it.

---

## Follow-up session: billing Phase 4.2 - invoices from the charge webhook + invoice list API

Every successful subscription charge now becomes an invoice, and the Billing owner can list them. Backend
only; the frontend is untouched (4.4).

### What changed
1. **`subscription.charged` webhook creates the invoice** (`routers/payments.py` -> `services/invoices.py::issue_for_charge`).
   Razorpay's docs confirm this event carries BOTH a subscription entity (with `current_start`/`current_end`) and a
   payment entity. Rules, each pinned by a test:
   - Built from the amount **actually charged** (`payment.amount`, `total_paise=`); GST is backed out of it.
   - Dated and numbered by the **payment's own `created_at`** (not when the webhook arrived), so a delayed delivery
     around 31 March still lands in the right financial year.
   - **Plan/cycle and period come from the event's own subscription snapshot**, not the later `subscription.fetch`
     the handler uses for subscription STATE - so a renewal that switched plans is invoiced for the plan billed.
   - Skipped (acknowledged with 200, and logged) when there is nothing to invoice: no payment entity
     (`CHARGED_EVENT_WITHOUT_PAYMENT`), payment not `captured` (`CHARGE_NOT_CAPTURED`), zero/non-integer/bool amount
     (`CHARGE_BAD_AMOUNT`), non-INR (`CHARGE_NOT_INR`).
   - Row lookup: by Razorpay subscription id, then by the owner stamped in `notes` - so a late charge on a
     subscription the customer has since replaced is still invoiced to them. No notes / two owners = not guessed at.
   - **`INVOICE_AMOUNT_MISMATCH` warning** when the charge differs from catalog base + GST. This is how a Razorpay Plan
     created at the base price (forgetting GST) shows up. The invoice is still issued for what was really charged.
   - Idempotent per payment: webhook redelivery, a new event id for the same payment, or two racing deliveries give one
     invoice and burn one number.
2. **A failing invoice can never fail the webhook** (`_issue_charge_invoice`, runs in a savepoint). All Razorpay events
   share one endpoint and Razorpay disables an endpoint that keeps erroring, which would also stop fee-payment events.
   On any error the subscription update still lands, Razorpay gets 200, and `INVOICE_NOT_ISSUED payment=pay_xxx ...` is
   logged at ERROR level. **Watch the logs for `INVOICE_NOT_ISSUED`** - each one is a charge with no tax invoice. To fix one:
   ```
   python -c "from app.database import SessionLocal; from app.models import Subscription; from app.services import invoices; \
     db=SessionLocal(); sub=db.query(Subscription).filter_by(razorpay_subscription_id='sub_...').one(); \
     invoices.issue_invoice(db, sub, plan='basic', cycle='monthly', total_paise=58882, razorpay_payment_id='pay_...'); db.commit()"
   ```
   (Redelivering the event from the Razorpay dashboard also works once the cause is fixed - issuing is idempotent.)
3. **`GET /billing/invoices`** (`limit` 1-200 default 50, `offset`; newest first) and **`GET /billing/invoices/{id}`**.
   Response model `InvoiceOut`: number, kind, plan + label, cycle, description, `base_paise`, `gst_rate_percent`,
   `gst_paise`, `total_paise`, currency, period start/end, `issued_at`. **Managers only** - the institute admin or an
   independent teacher; a teacher who belongs to an institute gets 403. Scoped through the caller's one Subscription row;
   another owner's invoice is a 404, and **a malformed id is a 404 too** (validated as a UUID first - on Postgres a
   non-UUID string would otherwise raise a 500; see the PRE-EXISTING note in the 4.1 entry).
4. `plans.py`: `PAID_PLAN_KEYS`, `CYCLE_KEYS`. No migration (0016 already has everything).

### Verified
- `python -m tests.test_billing_flow`: **58 pass on SQLite** (49 + 9 new). Migration tests 0015 and 0016 pass.
- **PostgreSQL 16.2**: all 9 new tests pass; the only 2 failures are the same pre-existing malformed-id 500s as before
  (`test_parent_cannot_touch_another_childs_fee`, `test_receipts_content_and_isolation`). With the UUID guard removed the
  new scoping test fails on Postgres (and, as expected, not on SQLite) - so the guard is genuinely needed.
- Mutation checks (one guard at a time, originals restored and diffed): 12 of 13 caught - not-captured / bad amount / non-INR
  accepted, receipt-time dating, no owner-notes fallback, no mismatch warning, plan from fetch instead of snapshot,
  invoice failure failing the webhook, unscoped list, unscoped detail, members allowed, wrong ordering. The 1 miss is the
  `db.flush()` before the row lookup: it is belt-and-braces (the notes lookup finds the row anyway), no test can tell.
- NOT verified: a real Razorpay `subscription.charged` delivery. The code reads `payment.entity.id/amount/currency/status/
  created_at` (Razorpay's standard payment entity) and `subscription.entity.current_start/current_end/plan_id/notes`; the docs
  show both entities and the period fields, but the payment fields come from the standard entity, not a captured live payload.
  Phase 5 test-mode run: fire a real charge and look at the invoice + the logs for `INVOICE_AMOUNT_MISMATCH`.

### Known limits (not bugs)
- `/billing/verify` (the browser right after Checkout) does NOT create an invoice - only the webhook does, so the first
  invoice appears when the webhook lands (normally seconds), not instantly.
- A subscribe-during-trial charge happens at trial end and arrives as a normal `subscription.charged` then; the earlier
  `authenticated` event moves no money and creates no invoice.
- **No credit notes.** A refunded subscription payment keeps its invoice; Indian GST expects a credit note for a refund. The app
  has no refund flow for subscriptions yet, so this is parked with the other refund items.
- The invoice is JSON only: no printable page/PDF, and no seller details (GSTIN, legal name, address) or buyer details. Both are 4.4
  (the GSTIN is an owner input - see section A).
- Scoped through the owner's CURRENT Subscription row: an independent teacher who later joins an institute no longer sees their
  own old invoices (the old row is kept, there is just no screen for it).

## Follow-up session: billing Phase 4.3 - upgrade now (prorated), migration 0017

Backend only; the frontend is untouched (4.4). Adds an immediate, prorated plan upgrade that also
works for UPI Autopay subscriptions. Tests: 72 pass on SQLite (58 old + 14 new); on PostgreSQL 16 70 of 72 pass
(the same 2 pre-existing malformed-id 500s from 4.1); migration 0017 up/down/up and `alembic check` clean on PG 16;
`tsc --noEmit` and `vite build` clean.

### How it works (all rules live in `services/upgrades.py`)
- `POST /billing/upgrade/quote {plan}` - read-only price. `POST /billing/upgrade {plan}` - creates a one-off **Razorpay
  Order** for the prorated amount (receipt `upg_<hex>`, notes `kind=plan_upgrade`) and a `plan_upgrades` row (`pending`).
  `POST /billing/upgrade/verify {order_id, payment_id, signature}` - the browser's confirmation after Checkout.
  Billing managers only; create and verify are rate-limited like the other billing writes.
- **Why an Order and not `subscription.edit`:** Razorpay refuses to edit UPI subscriptions (see the 4.0 heads-up), an Order
  works for every payment method.
- **Maths:** `base = (new_base - old_base) x remaining / period`, integer paise, rounded half-up once, on the BASE price;
  GST is added on top afterwards (same rule as every invoice). The period start is derived (one cycle before
  `current_period_end`, we only store the end). A quote under Razorpay's Rs 1 minimum is refused ("too close to renewal").
- **Allowed only when:** active paid subscription, not `cancel_at_period_end`, no scheduled change, higher plan, SAME cycle,
  target plan has a Razorpay plan id. Downgrades and cycle changes stay on `POST /billing/change-plan` (effective at renewal).
- **Applying is idempotent.** The browser's verify and the payment webhook (`payment.captured` / `order.paid`, routed by
  order id BEFORE the student-fee path) both call `upgrades.apply_paid` under a row lock; the row moves pending -> applied
  once. Only a captured payment counts; verify re-fetches the payment from Razorpay and checks order id, status and amount.
- **The paid plan is held:** after an upgrade Razorpay's subscription still reports the OLD plan_id, so
  `subscriptions.held_plan()` keeps the upgraded plan while `current_period_end` still equals the upgrade's `period_end`.
  When the period rolls over the hold releases and Razorpay's plan wins (tested both ways).
- **Next renewal's price:** after the commit, `switch_renewal` tries `subscription.edit(plan_id=new, schedule_change_at="cycle_end")`.
  If refused (UPI) it cancels the old subscription at cycle end and sets `cancel_at_period_end`; the customer then does an
  ordinary `POST /billing/subscribe`, which starts the new subscription at the period end (no double charge). The outcome is
  `plan_upgrades.renewal` = `scheduled` / `reauthorise` / `failed`, shown as `upgrade_renewal` on `GET /billing/me`. It never
  raises (a webhook must still answer 200), runs once per upgrade, and a webhook redelivery retries it if it was missed.
- **Invoice:** a `kind="proration"` invoice via `issue_invoice(total_paise=<amount actually paid>)`. NOTE: this differs from the
  4.2 plan, which said `base_paise=`; passing the real charged amount keeps the invoice equal to the money that moved.
  A failing invoice is logged (`INVOICE_NOT_ISSUED`) and never undoes a paid upgrade.

### Money taken but the upgrade cannot be applied -> manual refund
Status `refund_needed` + an ERROR log `UPGRADE_NEEDS_REFUND order=... payment=... - <reason>` when: the amount differs from the
order, the period changed (renewed/ended) before the payment arrived, the plan is already at or above the target (two paid
orders for one upgrade), or the subscription is gone. **An operator refunds that payment in the Razorpay dashboard by hand.**
The customer is told so on verify (409). There is no refund button or alert yet.

### Files
New: `alembic/versions/0017_plan_upgrades.py` (pure addition, UNIQUE order and payment ids, CHECK total = base + GST),
`app/services/upgrades.py`, `tests/test_migration_0017.py`. Changed: `models.py` (`PlanUpgrade`), `schemas.py` (upgrade schemas,
`BillingStatus.upgrade_renewal`), `routers/billing.py`, `routers/payments.py` (webhook routing), `services/subscriptions.py`
(`held_plan`), `README.md`, the 0015/0016 migration tests (drop the new table / no longer pin head to 0016), `tests/test_billing_flow.py`.

### Known gaps (4.4 / 5)
- No UI yet (4.4): quote dialog, Checkout call, a "subscribe again to continue" prompt when `upgrade_renewal == "reauthorise"`.
- The EXISTING `change-plan` still uses `subscription.edit` and still returns 502 for UPI subscriptions (Phase 5).
- A customer with a scheduled change cannot upgrade now until it takes effect (409).
- No upgrade-now for a billing-cycle change.
- Nothing has run against real Razorpay; the fake client mimics `order.create`, `payment.fetch` and `subscription.edit/cancel`.
- Watch the logs for `UPGRADE_NEEDS_REFUND` and `UPGRADE_RENEWAL_NOT_SWITCHED` (renews at the OLD price - fix in the dashboard).

---

## Follow-up session: billing Phase 4.4 - billing UI (invoices, upgrade now, GST copy) + seller endpoint

Mostly frontend. Tests: 73 pass on SQLite (72 + 1 new); `tsc --noEmit` and `vite build` clean. NOT run: PostgreSQL, a browser,
real Razorpay, and no mutation-check of the new guard (one tiny endpoint). No UI has been seen rendered yet (Phase 5).

### What changed
- **Backend (small):** `GET /billing/seller` -> `{legal_name, gstin, address}` from new env `SELLER_LEGAL_NAME`, `SELLER_GSTIN`,
  `SELLER_ADDRESS` (use `\n` for line breaks; empty until the owner sets them). Billing managers only, same as the invoices.
  Files: `database.py` (settings), `schemas.py` (`SellerOut`), `routers/billing.py`, `.env.example`, one test.
- **`api/client.ts`:** `Plan` gains the GST paise fields; `BillingStatus.upgrade_renewal`; types `Invoice`, `Seller`, `UpgradeQuote`,
  `UpgradeOrder`; functions `listInvoices`, `getInvoice`, `getSeller`, `quoteUpgrade`, `startUpgrade`, `verifyUpgrade`.
- **`lib/money.ts` (new):** `inrPaise` (integer paise -> "Rs 1,234.56", no float maths) and `fmtDate` (moved out of Billing.tsx).
- **`pages/Billing.tsx`:** plan prices read "Rs X + GST / month (Rs Y with 18% GST)"; **Upgrade now** button (higher plan, SAME cycle as
  the current one, no scheduled change) next to "Switch at next renewal" -> quote panel (credit, charge, subtotal, GST, total) ->
  Razorpay Checkout on the one-off order -> `/billing/upgrade/verify`. A verify failure that is not the refund 409 is shown as "payment
  received, plan updates within a minute" (the webhook applies it); the refund 409 is shown as an error. `upgrade_renewal ==
  "reauthorise"` shows a "Subscribe again" card (reuses the normal subscribe flow); `"failed"` shows a short notice. New **Invoices** list
  (managers only) with a "View / print" link.
- **`pages/InvoicePage.tsx` (new), route `/billing/invoice/:invoiceId`:** printable tax invoice outside the Layout (like Receipt), with
  seller name / GSTIN / address, base, GST, total.

### Known gaps
- The invoice shows GST as one line at the rate; no CGST/SGST/IGST split and no place of supply / HSN-SAC code (needs the owner's call).
- The invoice list loads the first 50 (API default) with no paging UI.
- Upgrade-now is offered only for the same cycle, as in 4.3. `change-plan` still 502s for UPI (Phase 5).
- Still nothing has run against real Razorpay or in a browser.

---

## Follow-up session: hand-over prep - shipped WITHOUT Razorpay keys

**Why:** the zip is going to a partner. Razorpay must not be connected, but everything else must work.

### State of the zip
- **No credentials anywhere.** Scanned the whole tree: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
  `RAZORPAY_WEBHOOK_SECRET` and the 4 `RAZORPAY_PLAN_*` ids are empty in `.env.example`, no `.env` is included,
  no `rzp_...` key appears in any source file. The Razorpay code is all still here; it just has no keys to use.
- Removed `backend/smoke.db` (a local SQLite file) from the zip.

### What changed (small, so the keyless app behaves properly)
Found by running the app with the real Razorpay client and blank keys: nothing crashed, but (a) students and
parents were still shown a **Pay now** button that then failed with "Couldn't start the payment", and (b) the
`verify` endpoints would have accepted a signature forged with the EMPTY secret (an empty HMAC key is valid).
Not exploitable in practice (no pending order can exist without keys) but wrong, so:
- `services/razorpay_client.py`: `razorpay_configured()` and `require_razorpay()` (503 "Online payments aren't
  switched on yet.").
- Students/parents: `online_payment_available` is false without keys, so they see "Pay the teacher directly";
  `create-order` answers the same friendly 409 as an institute with no payout account.
- `POST /billing/subscribe`, `/billing/verify`, `/billing/upgrade`, `/billing/upgrade/verify`,
  `/payments/verify`, `/parents/verify` return 503 without keys, before any signature check. The webhook already
  refused without its secret.
- Still working with no keys: login, batches, attendance, tests, plans listing, trial, fee records, **manual
  (cash/UPI) payments and part-payments, receipts**, reminders.
- `cancel` and `change-plan` are not guarded (an existing subscription cannot exist without having had keys).

### To connect Razorpay later
Put the keys, webhook secret and 4 plan ids in the real `backend/.env` (never in git) - no code change. Then work
through section B and Phase 5 below. The startup log warns if keys are set with commission 0.

### Verified
- `python -m tests.test_billing_flow`: **74 pass on SQLite** (73 + 1 new). The new test blanks the keys and checks
  all of the above, including that no call reaches Razorpay and that forged-empty-secret signatures are refused.
  It also passes on **PostgreSQL 16**. Mutation-checked: removing the key check in my-fees, create-order,
  payments-verify, subscribe and billing-verify each made it fail (the two upgrade endpoints' guards are not
  individually mutation-tested).
- Migration tests 0015/0016/0017 pass. Frontend not touched this session (previous `tsc` and `vite build` were clean).
- PostgreSQL, whole suite (earlier this session, before this change): 71 of 73; the 2 failures are the known
  malformed-id 500s listed under Phase 5. Empty-Postgres `alembic upgrade head` still fails at 0001
  (`type "classstatus" already exists`) - re-confirmed.
- Also still open and re-confirmed: CORS is `allow_origins=["*"]` in `main.py` (tighten before a public deploy).

---

## WHAT TO DO NEXT (billing) - last updated after Phase 4.4

Billing work is split into 5 phases. Each ends with tests, `tsc`, `vite build` and a HANDOFF entry.

| Phase | Scope | Status |
|---|---|---|
| 1 | Harden: rate limits, gate Free-plan reminders, commission warning | DONE |
| 2 | Parents can pay their child's fees | DONE |
| 3 | Fee lifecycle: ledger, partial payments, receipts, refund webhook, fee-created + receipt notices | DONE |
| 4.0 | Cheap fixes: rate-limit verify endpoints, reminder amount variable | DONE |
| 4.1 | GST + invoice table, migration 0016, numbering, "+ GST" in plan catalog | DONE |
| 4.2 | Invoices created from the `subscription.charged` webhook + invoice list/detail API | DONE |
| 4.3 | Upgrade-now with proration (backend, works for UPI; charge becomes a `kind="proration"` invoice), migration 0017 | DONE |
| 4.4 | Billing UI: invoice list/detail (+ printable page, seller GSTIN), upgrade-now dialog (quote -> Checkout -> verify, "subscribe again" prompt for `upgrade_renewal == "reauthorise"`), "+ GST" copy; `client.ts` types/functions added; plus `GET /billing/seller` | DONE |
| 5 | Go live: fix migration chain, real Razorpay test-mode run, Postgres, browser check | **NEXT** |

### A. Decisions only the owner can make (blocking or money-affecting)
1. **Platform commission** (`FEE_PLATFORM_COMMISSION_BPS`, currently 0). At 0 every online fee payment
   costs you Razorpay's fee. Choose a % covering Razorpay's fee + GST on it before enabling online fees.
2. ~~GST on subscriptions~~ DECIDED in 4.0: added on top, 18%. **Still yours:** Pro yearly now totals Rs 17,688.20, above
   the Rs 15,000 UPI Autopay no-PIN limit - lower its base to <= Rs 12,711 or accept a PIN each year (see the 4.1 entry).
   Also needed for a valid tax invoice: set `SELLER_LEGAL_NAME`, `SELLER_GSTIN`, `SELLER_ADDRESS` in env (4.4 prints them on the invoice page).

### B. Setup outside the code (the app will not fully work until these are done)
3. Razorpay webhook: tick **`refund.processed`** (new in Phase 3) in addition to the existing events.
4. Meta Business Manager: create and get approved `fee_created` and `payment_receipt` WhatsApp
   templates (4 body variables each; exact order in the Phase 3 entry). Until then notices go by SMS.
5. Route: each institute/teacher still needs a KYC'd linked account set by hand (`set_payout_account`).
   There is no self-serve onboarding.
6. Real prices and limits in `plans.py` (BASE prices, excluding GST); create the 4 Razorpay Plans at **base + GST** (exact
   paise in `GET /billing/plans` -> `total_*_paise`) and paste their ids into env.

### C. Phase 4 - subscription completeness (next)
7. ~~Upgrade now with proration~~ API DONE in 4.3 (`/billing/upgrade/quote|upgrade|upgrade/verify`); the dialog is DONE in 4.4.
8. ~~Invoice list~~ API DONE in 4.2 (`GET /billing/invoices`); the screen is DONE in 4.4.
9. ~~GST on invoices~~ - DONE in 4.1 (table, numbering, maths) + 4.2 (rows from the webhook); shown in 4.4.
Likely files for 4.4: `webapp/src/pages/Billing.tsx`, `webapp/src/api/client.ts`.
Add tests to `tests/test_billing_flow.py`, mutation-check each rule, then append a HANDOFF entry.

### D. Phase 5 - go-live verification (nothing below has ever been done against real services)
10. **Fix the migration chain on an empty PostgreSQL** (fails at 0001 and 0005 - see the WARNING above).
    Not needed for an existing DB at 0012+.
11. **Run the whole suite on PostgreSQL**: `TEST_DATABASE_URL=postgresql+psycopg://... python -m tests.test_billing_flow`.
    Phases 1-3 were only run on SQLite. **4.1 ran the full suite on PG 16.2: all pass except 2 pre-existing
    malformed-id 500s (see the 4.1 entry) - fix those here.** Postgres-specific risks: `with_for_update` row locks in the
    payment/refund path, UUID comparisons, migration 0015 backfill.
12. **Real Razorpay test-mode run**: subscribe, webhook delivery, Route transfer on a fee payment,
    Checkout popup (student and parent, with and without an amount), a real refund -> `refund.processed`.
13. **Click through the UI in a browser**: Pay with amount box, receipt page + print, teacher
    "Record payment", Billing page. No UI has been seen rendered in any session so far.
14. Real WhatsApp/SMS send of a fee-created and a receipt notice once templates are approved.

### E. Smaller known gaps (do when convenient)
- ~~verify endpoints unlimited~~ DONE in 4.0. Login/OTP and the rest of the app still have no rate limit.
- Daily overdue reminder: code now supports a variables template (4.0) but defaults to the old one. Create
  the Meta template and flip `FEE_REMINDER_TEMPLATE` / `FEE_REMINDER_TEMPLATE_VARS` (see the 4.0 entry).
- Refunds can only be issued from the Razorpay dashboard; there is no refund button in the app.
- Teacher "Record payment" is a plain browser prompt box.
- Two payers racing partial orders can overpay (flagged, not prevented).
- Abandoned (pending) ledger rows accumulate; harmless, could be pruned.
- A teacher who joins an institute keeps an old Subscription row. (The platform-admin panel now exists; see the 2026-10-25 entry.)
- ~~Malformed ids give 500 on Postgres~~ DONE (DataError -> 404, QA fix pass).
- Charges made before migration 0016 have no invoice; decide whether to backfill (needs the real payment amounts from Razorpay).
- Watch the logs for `INVOICE_NOT_ISSUED` / `INVOICE_AMOUNT_MISMATCH` (4.2) and `UPGRADE_NEEDS_REFUND` / `UPGRADE_RENEWAL_NOT_SWITCHED` (4.3, needs a manual refund / dashboard fix); there is no alert on them yet.

- (2026-10-25) Platform admin: see "Still open" in that entry (admin ban date not shown in rows, stats load all subscriptions in Python, no payment-reminder messages before the ban).

### F. Rules for whoever continues
- Fee paid/unpaid state changes ONLY through `services/fee_ledger.py`. Never set `FeeRecord.amount_paid /
  is_paid / paid_at` elsewhere.
- Tests: `python -m tests.test_billing_flow` (74 pass) and `python -m pytest tests/test_fixes.py` (11 pass), `python -m tests.test_migration_0015`, `..._0016`, `..._0017`.
  Platform admin / lifecycle (2026-10-25): `python -m pytest tests/test_access.py tests/test_admin.py tests/test_migration_0019.py`. Full suite is now `pytest tests` (133 pass). The 0015/0016/0017 migration tests upgrade to 0018, not head (they build the DB from current models, so head would re-create the 0019 tables).
  Run with `timeout` and mutate one guard at a time (a long all-in-one mutation run once timed out and
  left a broken guard in the source - always confirm originals are restored).
- Append a new `## Follow-up session:` entry per change; update this section's table and lists.
- Invoices: only create them through `services/invoices.py` (`issue_invoice` / `issue_for_charge` - numbering + idempotency live
  there), pass the real charged amount as `total_paise=`, never edit an invoice once issued. Never let invoicing raise out of the
  webhook (see `_issue_charge_invoice`).

## Follow-up session: Claude (sandbox QA + fix pass, 2026-10-20)

**Asked:** full sandbox QA of the teacher, student, parent and institute-owner windows (real browser, Asia/Kolkata, SQLite + Postgres 16), then fix what was found. Findings are in the QA report that came with this zip.

**What changed (backend, `backend/app/`)**
- **Timezones:** new `timeutil.py` (`utcnow`, `fmt_local`, `DISPLAY_TIMEZONE`, default Asia/Kolkata). `schemas.py` has `UtcIn` (aware -> naive UTC) and `UtcOut` (serialised with trailing `Z`). Class/attendance/attempt times use them; WhatsApp/SMS text is formatted in local time. Fee `due_date` stays date-only on purpose.
- **Classes:** end must be after start; cancel rejects already cancelled/completed; reschedule only for effective-scheduled; `effective_status` marks past scheduled classes `completed`; new `GET /classes/my` for students.
- **Attendance:** rejects cancelled / not-yet-started classes and students outside the batch; dedupes; empty marks 422; summary ignores cancelled classes.
- **Tests:** `/start` uses `_visible_test_for` (tenant + batch); resumes an open attempt; `TEST_MAX_ATTEMPTS` (default 1 -> 409); server timer (`duration + TEST_SUBMIT_GRACE_SECONDS`, `seconds_left` in payload); answers deduped by `question_id`; new `GET /tests/my-attempts`; analytics counts skipped questions; test document URL must be `/uploads/..` or http(s); magic-byte check on uploads.
- **Auth:** phone normalisation (`Phone` type); student/parent login checks every phone match against the secret and returns 409 `{choices:[{student_id,label}]}` when several match (client retries with `student_id`); login endpoints rate-limited (`RATE_LIMIT_LOGIN_PER_MIN`, default 10).
- **Deletes:** `services/cleanup.py` (`delete_student` refuses if any paid payment exists, else removes fees/attendance/attempts; `detach_teacher`). `main.py` turns Postgres `DataError` (malformed ids) into 404.
- **Owner tooling:** `GET/POST /institute/batches`, `DELETE /institute/students/{id}`; a teacher may add students to batches they created.
- **Migrations:** 0001 enums `create_type=False`; 0005 UUID types; new `0018_align_id_columns_to_uuid` (Postgres-only, idempotent). `alembic upgrade head` now works on an empty Postgres and `alembic check` shows no drift.

**What changed (webapp, `webapp/src/`)**: `api/client.ts` (exports `BASE_URL`, `toLocalInput`, `resolveApiUrl`, `AccountChoiceError`, new endpoints); Student/Parent login account picker + 429 message; ScheduleClass (local-time prefill, required fields, end>start, error text); MarkAttendance (hides cancelled/future classes, shows save errors); TakeTest (countdown + auto-submit, doc URL resolved against API, "awaiting grading", start/submit errors); StudentHome (Classes + My results); ManageStudents (Delete, Reset PIN); InstituteDashboard (owner checkbox, batches, per-teacher batch assignment, errors); new `InstituteStudents` page at `/institute/students` + enabled Students tab.

**Verified:** `tests/test_fixes.py` (11 new) + billing suite: 87/87 on SQLite, 85/85 on Postgres (`TEST_DATABASE_URL`, fixes+billing). `npx tsc --noEmit` clean, `npm run build` ok. Real browser (Chromium, IST): owner created batch, teacher (with batch) and student from the UI; teacher typed 16:00 -> shows 16:00 (DB 10:30 UTC), reschedule-confirm without edits no longer drifts; student sees class + countdown + score + results history, retake blocked.

**Behaviour changes to know about:** one attempt per test by default (set `TEST_MAX_ATTEMPTS`); login phones are stored/compared as digits only - rows created earlier with `+91`/spaces may need a one-off clean-up; cancelling a past class is now an error.

**Still open:** batch rename/delete and delete-test UI; password-reset still picks the first student on a shared phone (`_lookup_account`); notifications still sent sequentially; Razorpay, WhatsApp/Twilio, Android lock plugin and the fee-reminder cron untested; owner "Analytics" tab still disabled.

## Follow-up session: Claude (platform admin + account lifecycle, 2026-10-25)

**Asked:** a founder-only platform admin panel (two logins, not linked from the app) with headline numbers and per-account controls, plus an automatic account lifecycle that limits and then bans accounts that stop paying. Spec: `docs/superpowers/specs/2026-10-20-platform-admin-design.md`, plan: `docs/superpowers/plans/2026-10-21-platform-admin.md`.

**Lifecycle (`backend/app/services/access.py`).** A trial/paid plan runs to its period end, then a **3-day buffer** (still fully active), then **15 days of limited grace** (`LIMITED_GRACE_DAYS`; logins work, but attendance marking/analytics, creating tests, starting a NEW test attempt and test analytics are refused with 402; an already open attempt can still be resumed and submitted), then **ban** (403 on every authenticated route of that account and everyone under it; payers can still reach Billing). A payment restores access. A **manual (admin) ban** is separate: it is not lifted by payment, only by "Lift ban". Free-tier / never-paid accounts get their clock from the enforcement start date.

**ENFORCEMENT_START (safe default).** `ENFORCEMENT_START` in `backend/.env` (ISO date = midnight UTC). Blank/unset = enforcement disabled: nothing changes for any account. When set, the lifecycle clock for any lapsed account is `max(period end, ENFORCEMENT_START)`, so accounts already unpaid/on free at release get the 3-day buffer, then 15 days grace, ban 18 days after the release date.

**What changed, per task**
- **T1 schema (migration 0019, `models.py`, `database.py`):** tables `platform_admins`, `admin_audit_log`; `subscriptions.grace_until / admin_banned / admin_ban_reason / admin_banned_at`; `created_at` on teachers and students; settings `enforcement_start`, `limited_grace_days`. Test `tests/test_migration_0019.py`. Migration tests 0015/0016/0017 now upgrade to 0018 instead of head (accepted deviation, see above).
- **T2 access rules (`services/access.py`):** `access_for_owner/access_for_subscription` -> `Access(state, reason, grace_starts_at, ban_at)`; `assert_not_locked(db, owner, *, billing=False, payer=False)`, `assert_full_access(db, owner, what)`. `plan_for_owner` hooks in. 12 tests in `tests/test_access.py`.
- **T3 enforcement (`auth.py`, `main.py`, routers attendance/tests/billing):** lock checks in the teacher, student, parent and institute-admin dependencies; grace guards on the endpoints listed above; `BillingStatus` gains `access_state`, `access_reason`, `ban_at`; CORS exposes `X-Account-Status` and `X-Account-Can-Pay`.
- **T4 admin identity (`routers/admin.py`, `auth.get_current_platform_admin`, `scripts/create_platform_admin.py`):** `POST /admin/login` (own token role `platform_admin`, rate limited); admin tokens are rejected by every other route and vice versa.
- **T5 admin API (`routers/admin.py`, `timeutil.month_start_utc`):** `GET /admin/stats`, `GET /admin/accounts?status=`, `POST /admin/accounts/{id}/extend-grace | ban | lift-ban`; every mutation writes one `admin_audit_log` row.
- **T6 frontend:** `/admin-login`, `/admin` (stats tiles + account table with extend/ban/lift), `/account-locked`, `AccessBanner` in Layout, axios interceptor for the lock headers.
- **T7:** small polish fix commit (a platform_admin at `/` is sent to `/admin`; AdminDashboard clears a stale error on refresh; AdminLogin shows API `detail`, "Wrong phone number or password" only on 401, "Could not reach the server. Try again." with no response), plus these docs.

**Rulings made during the build**
- R1: payment-ban response carries `X-Account-Status: banned_payment`; `X-Account-Can-Pay: 1` only for payers (institute admin, independent teacher). Payer message "Your plan wasn't renewed. Renew in Billing to restore access."; others "This account is inactive because the plan wasn't renewed. Please contact your institute." Admin ban: `banned_admin`, "This account has been suspended. Please contact Wandor support.", never Can-Pay. The lock screen shows the Billing link only when Can-Pay was seen.
- R2: only institute admins and independent teachers get Billing during a payment-ban; teachers inside an institute are locked from Billing too.
- R3: `create_platform_admin` normalises the phone (`schemas.normalize_phone`) so login matches; the script is an idempotent upsert.
- R4: `grace_starts_at` and `ban_at` are set whenever the account has lapsed, including during the 3-day buffer (state still "active"); both None when not lapsed.
- R5: commit trailer convention.
- T3: `/tests/{id}/start` blocks only NEW attempts in grace; resuming an open in-time attempt still works (submit alone is useless without the questions).
- T5: the account list keeps free-tier rows and expired trials (founders must be able to extend/ban the accounts that sit in grace/ban after release); `is_paying` on each row and the stats headline share `_is_paying()`. Manual ban is allowed for any independent teacher or institute owner (not only paid plans); students, parents and in-institute teachers are not reachable (ids are subscription ids, unknown -> 404).

**Founder-facing facts:** parents are not counted in "Gained this week" (footnote on the dashboard). Teachers and students that existed before migration 0019 have no signup date (`created_at` NULL), so they never count as "gained"; only accounts created after the migration do. Money tiles are IST-month based (`month_start_utc`).

**Verified (2026-10-25):** full backend suite 130 passed on SQLite and 130 passed on Postgres 16 (fresh db each); `alembic upgrade head` on an empty Postgres runs 0018 -> 0019 with no error, `alembic current` = 0019 (head), `alembic check` = "No new upgrade operations detected."; `npx tsc --noEmit` and `npm run build` clean. Browser (Playwright, IST, SQLite) in Task 6: admin login, tiles matched seeded invoices, extend grace, manual ban + lift, payment-ban lock screen with Billing link, grace banner. NOT browser-tested: the non-payer locked variant (institute teacher under payment-ban), and the T7 polish fixes (typecheck/build only).

**Still open (deferred minors)**
- No test of `plan_for_owner` outside grace (active paid / banned fall-through).
- No HTTP test for an institute student in grace or an ownerless student; student/parent requests cost one extra subscription query.
- No test showing `/admin/login` rate limiting; admin login skips `verify_password` for an unknown phone (same as the other logins) - timing difference.
- `admin_banned_at` is not exposed in account rows; admin-banned rows have `ban_at` null (UI shows "-"); `extend_grace` audit old value is the effective ban date.
- `/admin/stats` and `/admin/accounts` load all subscriptions into Python (access state is date logic); fine now, will not scale.
- pydantic 422s return a list `detail` (app-wide behaviour).
- Task 1 minors: `test_migration_0019` upgrades to head but asserts 0019 (pin it to 0019); brittle 'NUMERIC(), UUID' string match; stale comment in the 0016 test; env leak via `setdefault`.
- `AccessBanner` refetches `/billing/me` per Layout mount. `alembic check` on SQLite is never clean (UUIDs reflect as NUMERIC, pre-existing); use the Postgres check.
- No reminder messages are sent before the buffer/grace/ban dates; the lifecycle is silent apart from the in-app banner.
- A subscription with status expired/pending restarts its lapse clock at the release date.
- A free-tier account in grace gets pro limits (`TRIAL_PLAN`).
- The Billing page shows the "Free" label for a paying account in grace (`billing.py` uses `effective_plan`).
- Spec says "15-day grace starting release day"; the build is 3-day buffer + 15 days (ban at release + 18 days). Confirm with the founders.
- Admin list/stats load all subscriptions in Python.
- Admin login does no hash check for an unknown phone (timing).
- `tests/test_migration_0019.py` asserts head == 0019 and will break when 0020 lands.

**Added in the fix wave (2026-10-25, after review)**
- Accounts with no Subscription row were invisible to the admin panel but still banned by the lifecycle. Migration 0019 now backfills a `plan='free', status='active'` row for every institute and every independent teacher lacking one (idempotent; downgrade keeps them), and `subscriptions.start_trial` always leaves a row (free/active when `TRIAL_DAYS=0`; never restarts a trial). Tests: `test_migration_0019.py`, `test_access.py::test_start_trial_always_leaves_a_row`, `test_admin.py::test_account_without_prior_row_...`.
- `apply_razorpay_subscription` clears `grace_until` when the result is active with a future period end (a founder extension no longer outlives the payment; `admin_banned` untouched).
- README release checklist order fixed (migrate before creating founder logins).

## Frontend redesign (Neo-Constructivist)
- New public landing at `/` for logged-out visitors (`pages/Landing.tsx`, `landing.css`, scoped under `.lp`). Role picker moved to `/enter` (`RoleSelect.tsx`; Student and Parent are now separate rows).
- App-wide tokens re-skinned in `index.css` (ivory #F2EFE6, ink #111, red #D62828, Archivo variable width). Fonts are self-hosted via @fontsource (works offline in Capacitor). Google Fonts link removed.
- Landing ignores dark mode on purpose. Inner pages (27) were only re-skinned through tokens, not redesigned.
