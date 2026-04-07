#!/bin/bash
# ── Quick deploy: pull latest code and restart the service ──────────────────
# Run this after pushing changes to GitHub:
#   ssh ubuntu@<your-vm-ip> "bash ~/stock-insights/deploy/update.sh"

set -euo pipefail

APP_DIR="$HOME/stock-insights"
SERVICE_NAME="stock-insights"

cd "$APP_DIR"

echo "Pulling latest code..."
git pull

echo "Updating Python dependencies..."
cd backend
source venv/bin/activate
pip install -r requirements.txt --quiet

echo "Restarting service..."
sudo systemctl restart ${SERVICE_NAME}

echo "Waiting for startup..."
sleep 3

if sudo systemctl is-active --quiet ${SERVICE_NAME}; then
  echo "✅ Service is running"
  curl -s http://127.0.0.1:8000/health | python3 -m json.tool
else
  echo "❌ Service failed to start. Check logs:"
  echo "   sudo journalctl -u ${SERVICE_NAME} -n 20"
fi
