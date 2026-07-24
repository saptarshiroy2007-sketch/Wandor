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

## Not built yet (unchanged priorities from before)

- Student-facing auth (test attempts take a raw `student_id` for now)
- File upload endpoint for test documents (assumes a URL from S3/GCS already)
- Attendance tracking
- Real LLM wiring in `mcq_gen.py`
- Alembic migrations
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
uvicorn app.main:app --reload
```

## Running the web app

```bash
cd webapp
npm install
npm run dev   # http://localhost:5173
```
