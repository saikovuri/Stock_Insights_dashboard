#!/bin/bash
# ── Quick deploy: pull latest code and restart the service ──────────────────
# Run this after pushing changes to GitHub:
#   ssh ubuntu@<your-vm-ip> "bash ~/stock-insights/deploy/update.sh"

set -euo pipefail

APP_DIR="$HOME/stock-insights"
SERVICE_NAME="stock-insights"

cd "$APP_DIR"

echo "Pulling latest code..."
git pull --ff-only

echo "Updating Python dependencies..."
export PATH="$HOME/.local/bin:$PATH"
cd backend
uv pip install --python venv/bin/python -r requirements.txt --quiet

echo "Restarting service..."
sudo systemctl restart ${SERVICE_NAME}

echo "Waiting for startup..."
for _ in $(seq 1 30); do
  curl -fs http://127.0.0.1:8000/health >/dev/null && break
  sleep 2
done

if curl -fs http://127.0.0.1:8000/health; then
  echo ""
  echo "✅ $(git -C "$APP_DIR" log -1 --format='%h %s') is live"
else
  echo "❌ Service didn't come up. Last logs:"
  sudo journalctl -u ${SERVICE_NAME} -n 30 --no-pager
  exit 1
fi
