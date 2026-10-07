#!/usr/bin/env bash
# Runs the same checks as CI. Stops at the first failure. From the repo root:  bash scripts/check.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/backend" DATABASE_URL=""
echo "== Backend tests";   .venv/bin/python -m unittest discover -s backend/tests -q
echo "== Backend compile"; .venv/bin/python -m compileall -q backend
cd frontend
echo "== Lint";            npm run lint
echo "== Unit tests";      npm test
echo "== Build";           npm run build
echo "== Browser tests";   npm run test:e2e
echo "== Dependency audit"; npm audit --audit-level=high
cd ..
echo "== Whitespace";      git diff --check
echo "All checks passed."
