#!/bin/bash
# StockPilot backend on an always-on Ubuntu 24.04 laptop (Desktop or Server), published with Tailscale Funnel.
#   bash laptop-setup.sh            set up or re-check everything; safe to re-run
#   bash laptop-setup.sh cutover    after the Oracle backend is stopped: scheduler on, setup sudo rule removed
# Guide: setup_laptop.md
set -euo pipefail

REPO_URL="https://github.com/saikovuri/Stock_Insights_dashboard.git"
APP_DIR="$HOME/stock-insights"
ENV_FILE="$APP_DIR/backend/.env"
SERVICE="stock-insights"
ORACLE="ubuntu@157.151.152.97"
ORACLE_HOSTKEY="157.151.152.97 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILnMUynHb67tEzytcReNrEdvD8zMLVqJ69T5IbeNlMFB"
APT="sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 -y -q"

step() { printf '\n=== %s ===\n' "$*"; }
healthy() {
  for _ in $(seq 1 45); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
  curl -fs http://127.0.0.1:8000/api/health >/dev/null
}

[ "$(id -u)" -ne 0 ] || { echo "Run this as your normal user, not with sudo."; exit 1; }
sudo -v

if [ "${1:-}" = "cutover" ]; then
  step "Cut over: scheduler on"
  sed -i '/^SCHEDULER_ENABLED=0$/d' "$ENV_FILE"
  sudo systemctl restart "$SERVICE"
  if healthy; then echo "API + database OK, scheduler ON"; else sudo journalctl -u "$SERVICE" -n 40 --no-pager; exit 1; fi
  sudo rm -f /etc/sudoers.d/90-stockpilot-setup
  echo "Temporary setup sudo rule removed; sudo asks for your password again."
  echo "Send Copilot: CUTOVER DONE"
  exit 0
fi

step "1. System packages (can take a few minutes)"
$APT update
$APT full-upgrade
$APT install git curl ufw unattended-upgrades openssh-server python3

step "2. Time zone and automatic security updates"
sudo timedatectl set-timezone Etc/UTC
echo 'unattended-upgrades unattended-upgrades/enable_auto_updates boolean true' | sudo debconf-set-selections
sudo dpkg-reconfigure -f noninteractive unattended-upgrades
# Reboot only when an update needs it, before the US pre-market
sudo tee /etc/apt/apt.conf.d/52stockpilot > /dev/null << 'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "08:30";
EOF

step "3. Never sleep (lid closed, idle)"
sudo mkdir -p /etc/systemd/logind.conf.d
sudo tee /etc/systemd/logind.conf.d/10-stay-awake.conf > /dev/null << 'EOF'
[Login]
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandleSuspendKey=ignore
HandleHibernateKey=ignore
IdleAction=ignore
EOF
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
if command -v gsettings > /dev/null && [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' || true
  gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' || true
fi

step "4. Wi-Fi connects at boot, before anyone logs in"
WIFI=$(nmcli -t -f NAME,TYPE connection show --active 2> /dev/null | awk -F: '$2=="802-11-wireless" {print $1; exit}' || true)
if [ -n "$WIFI" ]; then
  PSK=$(nmcli -s -g 802-11-wireless-security.psk connection show "$WIFI" 2> /dev/null || true)
  if [ -n "$PSK" ]; then
    sudo nmcli connection modify "$WIFI" connection.autoconnect yes connection.permissions "" \
      802-11-wireless-security.psk-flags 0 802-11-wireless-security.psk "$PSK"
  else
    sudo nmcli connection modify "$WIFI" connection.autoconnect yes connection.permissions ""
  fi
  unset PSK
  echo "Wi-Fi '$WIFI' is now a system connection"
else
  echo "No active Wi-Fi connection (cable?) - nothing to change"
fi

step "5. Firewall: SSH from your home network only; nothing else comes in"
IFACE=$(ip route show default | awk '{print $5; exit}')
CIDR=$(ip -o -f inet addr show "$IFACE" | awk '{print $4; exit}')
LAN=$(python3 -c 'import ipaddress, sys; print(ipaddress.ip_interface(sys.argv[1]).network)' "$CIDR")
sudo ufw default deny incoming > /dev/null
sudo ufw default allow outgoing > /dev/null
sudo ufw allow from "$LAN" to any port 22 proto tcp > /dev/null
sudo ufw allow in on tailscale0 > /dev/null
sudo ufw --force enable > /dev/null
echo "Firewall on; SSH allowed from $LAN"

step "6. Code"
if [ -d "$APP_DIR/.git" ]; then git -C "$APP_DIR" pull -q --ff-only; else git clone -q "$REPO_URL" "$APP_DIR"; fi
git -C "$APP_DIR" log -1 --format='%h %s'

step "7. Python 3.13 and packages"
if ! command -v uv > /dev/null && [ ! -x "$HOME/.local/bin/uv" ]; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi
export PATH="$HOME/.local/bin:$PATH"
cd "$APP_DIR/backend"
[ -x venv/bin/python ] || uv venv -q --python 3.13 venv
uv pip install -q --python venv/bin/python -r requirements.txt

step "8. Allow automatic deploys to restart the app"
echo "$USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart $SERVICE, /usr/bin/journalctl -u $SERVICE -n 30 --no-pager" \
  | sudo tee /etc/sudoers.d/stock-insights > /dev/null
sudo chmod 440 /etc/sudoers.d/stock-insights
sudo visudo -cq

step "9. Production settings (backend/.env)"
if [ ! -s "$ENV_FILE" ]; then
  KEY="$HOME/.ssh/stockpilot_oracle"
  KNOWN="$HOME/.ssh/stockpilot_oracle_known_hosts"
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  [ -f "$KEY" ] || ssh-keygen -q -t ed25519 -N "" -f "$KEY" -C "stockpilot-laptop"
  echo "$ORACLE_HOSTKEY" > "$KNOWN"
  TMP=$(mktemp) && chmod 600 "$TMP"
  # The Oracle VM only lets this key read the settings file (forced command)
  if ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 -o UserKnownHostsFile="$KNOWN" -o StrictHostKeyChecking=yes \
       "$ORACLE" read-env > "$TMP" 2> /dev/null < /dev/null \
     && grep -q '^DATABASE_URL=.' "$TMP" && grep -q '^JWT_SECRET=.' "$TMP"; then
    install -m 600 "$TMP" "$ENV_FILE"
    rm -f "$TMP"
    [ -z "$(tail -c1 "$ENV_FILE")" ] || echo >> "$ENV_FILE"
    echo "SCHEDULER_ENABLED=0" >> "$ENV_FILE"
    echo "Copied from the Oracle VM; scheduler stays OFF until cutover"
  else
    rm -f "$TMP"
    echo
    echo ">>> NEXT: send Copilot this whole line, then run the same command again:"
    echo
    cat "$KEY.pub"
    echo
    exit 0
  fi
fi
chmod 600 "$ENV_FILE"
grep -q '^SCHEDULER_ENABLED=0$' "$ENV_FILE" && echo "Scheduler: OFF (until cutover)" || echo "Scheduler: ON"

step "10. Backend service"
# One worker: the in-process scheduler and cache must not run twice
sudo tee /etc/systemd/system/$SERVICE.service > /dev/null << EOF
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
sudo systemctl enable -q $SERVICE
sudo systemctl restart $SERVICE
if healthy; then echo "API + database OK"; else echo "Backend is not healthy:"; sudo journalctl -u $SERVICE -n 40 --no-pager; exit 1; fi

step "11. Tailscale Funnel (public HTTPS address)"
command -v tailscale > /dev/null || curl -fsSL https://tailscale.com/install.sh | sh
if ! sudo tailscale status > /dev/null 2>&1; then
  echo ">>> Open the link below on any device, sign in (a free account is fine) and approve this laptop."
  sudo tailscale up --hostname=stockpilot
fi
if ! sudo tailscale funnel status 2> /dev/null | grep -q 'Funnel on'; then
  echo ">>> If a link appears, open it and enable HTTPS / Funnel; this continues by itself afterwards."
  sudo tailscale funnel --bg http://127.0.0.1:8000
fi
DNS=$(sudo tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
PUBLIC="https://$DNS"

step "12. Automatic deploys (every 5 minutes, only commits that passed GitHub CI)"
cat > "$HOME/stock-insights-autoupdate.sh" << 'AUTOUPDATE'
#!/bin/bash
# Deploy new master commits after GitHub CI has passed for them.
set -euo pipefail
REPO=saikovuri/Stock_Insights_dashboard
cd "$HOME/stock-insights"
git fetch --quiet origin master
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)
[ "$LOCAL" = "$REMOTE" ] && exit 0

if ! python3 - "$REPO" "$REMOTE" << 'PY'
import json, sys, urllib.request
repo, sha = sys.argv[1], sys.argv[2]
req = urllib.request.Request(f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100",
                             headers={"Accept": "application/vnd.github+json", "User-Agent": "stockpilot-laptop"})
runs = json.load(urllib.request.urlopen(req, timeout=20))["check_runs"]
done = bool(runs) and all(r["status"] == "completed" for r in runs)
ok = done and all(r["conclusion"] in ("success", "skipped", "neutral") for r in runs)
print(f"{sha[:7]}: {len(runs)} checks, " + ("passed" if ok else "failed" if done else "still running"))
sys.exit(0 if ok else 1)
PY
then
  exit 0
fi

if git diff --quiet "$LOCAL" "$REMOTE" -- backend deploy; then
  git merge --ff-only --quiet "$REMOTE"
  echo "Fast-forwarded to ${REMOTE:0:7} (no backend changes, no restart)"
else
  bash deploy/update.sh
fi
AUTOUPDATE
chmod +x "$HOME/stock-insights-autoupdate.sh"
sudo tee /etc/systemd/system/stock-insights-autoupdate.service > /dev/null << EOF
[Unit]
Description=StockPilot: deploy new commits that passed CI
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=$USER
ExecStart=/bin/bash $HOME/stock-insights-autoupdate.sh
EOF
sudo tee /etc/systemd/system/stock-insights-autoupdate.timer > /dev/null << 'EOF'
[Unit]
Description=Check GitHub for StockPilot updates every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q --now stock-insights-autoupdate.timer
echo "Timer on"

step "Done"
echo "Backend:  running ($(git -C "$APP_DIR" log -1 --format=%h))"
grep -q '^SCHEDULER_ENABLED=0$' "$ENV_FILE" && echo "Scheduler: OFF until cutover" || echo "Scheduler: ON"
echo "Public:   $PUBLIC"
echo
echo "1. In the Tailscale admin console (login.tailscale.com/admin/machines): stockpilot -> ... -> Disable key expiry."
echo "2. Send Copilot this line:  PUBLIC=$PUBLIC"
