#!/bin/bash
# ── StockPilot backend on Oracle Cloud (Always Free ARM VM) ─────────────────
#
# VM:   Shape VM.Standard.A1.Flex, 2 OCPU / 12 GB (free tier allows up to 4 / 24)
#       Image Canonical Ubuntu 24.04 (aarch64)
# Run:  bash oracle-setup.sh [api-domain]
#       Omit the domain to get a free HTTPS hostname: <public-ip>.sslip.io
#
# Safe to re-run: it pulls the latest code, reinstalls deps and restarts.
# ────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/saikovuri/Stock_Insights_dashboard.git}"
APP_DIR="$HOME/stock-insights"
SERVICE_NAME="stock-insights"
PY_VERSION="3.13"

echo "=== 1. System packages ==="
sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get upgrade -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y git curl debian-keyring debian-archive-keyring \
  apt-transport-https iptables-persistent unattended-upgrades

echo "=== 2. Open ports 80/443 in the VM firewall ==="
# Oracle's Ubuntu images ship iptables rules that REJECT everything except SSH,
# on top of the VCN Security List — both must allow 80/443.
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    line=$(sudo iptables -L INPUT --line-numbers | awk '/REJECT/ {print $1; exit}')
    if [ -n "$line" ]; then
      sudo iptables -I INPUT "$line" -p tcp --dport "$port" -m state --state NEW -j ACCEPT
    else
      sudo iptables -A INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT
    fi
  fi
done
sudo netfilter-persistent save

echo "=== 3. Caddy (reverse proxy, automatic HTTPS) ==="
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update && sudo apt-get install -y caddy
fi

echo "=== 4. Code ==="
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi

echo "=== 5. Python $PY_VERSION + dependencies (via uv) ==="
if ! command -v uv >/dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
cd "$APP_DIR/backend"
[ -x venv/bin/python ] || uv venv --python "$PY_VERSION" venv
uv pip install --python venv/bin/python -r requirements.txt

echo "=== 6. Environment file ==="
ENV_FILE="$APP_DIR/backend/.env"
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" << 'ENVEOF'
# Copy these values from Render → your service → Environment.
DATABASE_URL=
JWT_SECRET=
CORS_ORIGINS=https://stock-insights-dashboard.vercel.app,capacitor://localhost,http://localhost,http://localhost:5173

GEMINI_API_KEY=
GROQ_API_KEY=
# OPENAI_API_KEY=

FINNHUB_API_KEY=
TWELVEDATA_API_KEY=
SEC_USER_AGENT=StockPilot you@example.com

SENTRY_DSN=
SENTRY_ENVIRONMENT=production
ENVEOF
  chmod 600 "$ENV_FILE"
  echo ""
  echo "⚠️  Created $ENV_FILE — fill in the values, then re-run this script:"
  echo "    nano $ENV_FILE && bash $APP_DIR/deploy/oracle-setup.sh ${1:-}"
  exit 0
fi
chmod 600 "$ENV_FILE"
if grep -qE '^(DATABASE_URL|JWT_SECRET)=$' "$ENV_FILE"; then
  echo "❌ DATABASE_URL and JWT_SECRET must be set in $ENV_FILE"; exit 1
fi

echo "=== 7. systemd service ==="
# One worker: the in-process scheduler and cache must not run twice.
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null << EOF
[Unit]
Description=StockPilot API
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR/backend
ExecStart=$APP_DIR/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

echo "=== 8. HTTPS hostname ==="
DOMAIN="${1:-}"
if [ -z "$DOMAIN" ]; then
  PUBLIC_IP=$(curl -s https://api.ipify.org)
  DOMAIN="${PUBLIC_IP//./-}.sslip.io"
fi
sudo tee /etc/caddy/Caddyfile > /dev/null << EOF
${DOMAIN} {
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "=== 9. Health check ==="
for _ in $(seq 1 30); do
  curl -fs http://127.0.0.1:8000/health >/dev/null && break
  sleep 2
done
curl -fs http://127.0.0.1:8000/health && echo "  ← local OK"
sleep 5
curl -fs "https://${DOMAIN}/health" && echo "  ← public HTTPS OK" \
  || echo "⚠️  HTTPS not ready yet (the certificate can take a minute). Check: sudo journalctl -u caddy -n 30"

echo ""
echo "✅ API: https://${DOMAIN}"
echo "   Set VITE_API_URL=https://${DOMAIN} in Vercel and redeploy the frontend."
echo ""
echo "   Logs:    sudo journalctl -u ${SERVICE_NAME} -f"
echo "   Update:  bash $APP_DIR/deploy/update.sh"
