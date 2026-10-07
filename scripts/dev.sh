#!/usr/bin/env bash
# Starts the backend (port 8000) in the background and the frontend (port 5173) in the foreground.
# Ctrl+C stops both. From the repo root:  bash scripts/dev.sh
set -euo pipefail
cd "$(dirname "$0")/.."
(cd backend && ../.venv/bin/python -m uvicorn main:app --port 8000 --reload) &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null' EXIT
echo "Backend: http://localhost:8000/api/health   App: http://localhost:5173"
cd frontend && npm run dev
