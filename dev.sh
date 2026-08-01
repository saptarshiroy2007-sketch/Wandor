#!/usr/bin/env bash
# Runs backend (uvicorn) + webapp (vite) together. Ctrl+C stops both.
set -e
cd "$(dirname "$0")"

# --- backend deps ---
if [ ! -d backend/.venv ]; then
  echo "Setting up backend venv..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q --break-system-packages -r backend/requirements.txt 2>/dev/null \
    || backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
[ -f backend/.env ] || cp backend/.env.example backend/.env

# --- webapp deps ---
if [ ! -d webapp/node_modules ]; then
  echo "Installing webapp deps..."
  (cd webapp && npm install)
fi
[ -f webapp/.env ] || echo "VITE_API_BASE_URL=http://localhost:8000" > webapp/.env

# --- run both, kill both on exit ---
cleanup() {
  trap - EXIT INT TERM
  echo "Stopping..."
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

(cd backend && exec ./.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!
(cd webapp && exec npm run dev -- --host 0.0.0.0 --port 5173) &
FRONTEND_PID=$!

echo "Backend  -> http://localhost:8000"
echo "Frontend -> http://localhost:5173"
wait
