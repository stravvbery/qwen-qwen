#!/usr/bin/env bash
# Helper: run backend + frontend in two foregrounded subshells.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${FIREWORKS_API_KEY:-}" ]]; then
  echo "FIREWORKS_API_KEY is not set. Export it or put it in backend/.env"
  exit 1
fi

(
  cd backend
  [[ -d .venv ]] || python3 -m venv .venv
  source .venv/bin/activate
  pip install -q -e . >/dev/null
  exec uvicorn app.main:app --reload --port 8000
) &
BACKEND_PID=$!

(
  cd frontend
  [[ -d node_modules ]] || npm install
  exec npm run dev
) &
FRONT_PID=$!

trap 'kill $BACKEND_PID $FRONT_PID 2>/dev/null || true' EXIT

wait
