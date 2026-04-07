#!/bin/bash
# ── Oracle Cloud Free Tier Setup Script ─────────────────────────────────────
# Run this on your Oracle Cloud ARM VM (Ubuntu 22.04 / 24.04 free tier)
#
# Prerequisites:
#   1. Create an Oracle Cloud account (always-free tier)
#   2. Launch a VM: Shape = VM.Standard.A1.Flex (1 OCPU, 1 GB RAM)
#      Image = Canonical Ubuntu 22.04 or 24.04
#   3. In the VCN Security List, add Ingress Rule: TCP port 443 and 80
#   4. SSH into the VM: ssh -i <your-key> ubuntu@<public-ip>
#   5. Run: bash oracle-setup.sh
#
# This script installs Python 3.13, clones your repo, sets up systemd,
# and configures Caddy as reverse proxy with automatic HTTPS.
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="https://github.com/saikovuri/Stock_Insights_dashboard.git"
APP_DIR="$HOME/stock-insights"
SERVICE_NAME="stock-insights"

echo "=== 1. System update ==="
sudo apt update && sudo apt upgrade -y

echo "=== 2. Install Python 3.13 + pip ==="
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt install -y python3.13 python3.13-venv python3.13-dev

echo "=== 3. Install Caddy (reverse proxy with auto-HTTPS) ==="
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy

echo "=== 4. Clone repo ==="
if [ -d "$APP_DIR" ]; then
  echo "Directory exists, pulling latest..."
  cd "$APP_DIR" && git pull
else
  git clone "$REPO_URL" "$APP_DIR"
fi

echo "=== 5. Create Python venv + install deps ==="
cd "$APP_DIR/backend"
python3.13 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 6. Create .env file (EDIT THIS!) ==="
if [ ! -f "$APP_DIR/backend/.env" ]; then
  cat > "$APP_DIR/backend/.env" << 'ENVEOF'
# ── Required ──────────────────────────────────────────────
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
JWT_SECRET=CHANGE_ME_TO_A_RANDOM_STRING
CORS_ORIGINS=https://stock-insights-dashboard.vercel.app,http://localhost:5173

# ── Optional ──────────────────────────────────────────────
OPENAI_API_KEY=sk-...
NEWS_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
ENVEOF
  echo ""
  echo "⚠️  IMPORTANT: Edit $APP_DIR/backend/.env with your actual credentials!"
  echo "   nano $APP_DIR/backend/.env"
  echo ""
fi

echo "=== 7. Create systemd service ==="
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=Stock Insights FastAPI Backend
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR/backend
Environment=PATH=$APP_DIR/backend/venv/bin:/usr/bin
EnvironmentFile=$APP_DIR/backend/.env
ExecStart=$APP_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}

echo "=== 8. Configure Caddy ==="
echo ""
echo "Choose your setup:"
echo "  A) Use a custom domain (recommended, free HTTPS via Let's Encrypt)"
echo "  B) Use IP only (HTTP, no HTTPS)"
echo ""
read -p "Enter A or B: " CHOICE

if [[ "${CHOICE^^}" == "A" ]]; then
  read -p "Enter your domain (e.g., api.stockinsights.com): " DOMAIN
  sudo tee /etc/caddy/Caddyfile > /dev/null << EOF
${DOMAIN} {
    reverse_proxy 127.0.0.1:8000
}
EOF
  echo "Point your domain's A record to this VM's public IP, then Caddy handles HTTPS automatically."
else
  PUBLIC_IP=$(curl -s ifconfig.me)
  sudo tee /etc/caddy/Caddyfile > /dev/null << EOF
:80 {
    reverse_proxy 127.0.0.1:8000
}
EOF
  echo "API will be available at http://${PUBLIC_IP}"
fi

sudo systemctl restart caddy

echo "=== 9. Start the service ==="
sudo systemctl start ${SERVICE_NAME}

echo ""
echo "✅ Setup complete!"
echo ""
echo "Commands you'll need:"
echo "  sudo systemctl status ${SERVICE_NAME}    # Check if running"
echo "  sudo journalctl -u ${SERVICE_NAME} -f    # View logs"
echo "  sudo systemctl restart ${SERVICE_NAME}   # Restart after code changes"
echo "  cd $APP_DIR && git pull && sudo systemctl restart ${SERVICE_NAME}  # Deploy update"
echo ""
echo "⚠️  Don't forget to:"
echo "  1. Edit $APP_DIR/backend/.env with real credentials"
echo "  2. Update CORS_ORIGINS in .env to include your frontend URL"
echo "  3. Update frontend API_BASE to point to this server's URL"
echo "  4. Open ports 80 and 443 in Oracle Cloud VCN Security List"
