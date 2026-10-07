#!/usr/bin/env bash
# One-time local setup on macOS/Linux. From the repo root:  bash scripts/setup-local.sh
# Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null || { echo "$1 not found. $2"; exit 1; }; }
need git "Install Git."
need node "Install Node.js 22 LTS: https://nodejs.org"
PY=$(command -v python3.13 || command -v python3 || true)
[ -n "$PY" ] || { echo "Install Python 3.13: https://www.python.org/downloads/"; exit 1; }

echo "== Python virtual environment (.venv)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python --version
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r backend/requirements.txt

echo "== backend/.env"
if [ -f backend/.env ]; then
  echo "backend/.env already exists - left unchanged."
else
  SECRET=$(.venv/bin/python -c "import secrets; print(secrets.token_hex(32))")
  sed "s/^JWT_SECRET=.*/JWT_SECRET=$SECRET/" .env.example > backend/.env
  chmod 600 backend/.env
  echo "Created backend/.env with a random JWT_SECRET. Add your API keys to it (see setup.md)."
fi

echo "== Frontend packages"
(cd frontend && npm install && npx playwright install chromium)

echo ""
echo "Done. Start the app with:  bash scripts/dev.sh"
