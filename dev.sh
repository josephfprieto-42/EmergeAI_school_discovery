#!/usr/bin/env bash
# Run the API and the web app together for local development.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x backend/.venv/bin/uvicorn ]; then
  echo "Backend venv missing. Run: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "Frontend deps missing. Run: (cd frontend && npm install)" >&2
  exit 1
fi
if [ ! -f data/schoolmatch.db ]; then
  echo "Database missing. Run: backend/.venv/bin/python backend/ingest/build_db.py" >&2
  exit 1
fi

trap 'kill 0' EXIT
(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
(cd frontend && npm run dev) &
wait
