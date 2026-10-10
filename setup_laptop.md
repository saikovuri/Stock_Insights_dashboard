# Run the StockPilot backend on an old laptop (Ubuntu 24.04, always on)

This guide moves the backend from the Oracle VM to a laptop at home. The frontend stays on Vercel and the database stays on Supabase; only the API server moves. The laptop runs exactly what the Oracle VM runs today: one uvicorn process with the built-in scheduler (alerts, wheel refresh, scans).

Two ways to make the laptop reachable from the internet, without opening ports on your router. Pick **one**:

| | **A. Tailscale Funnel** | **B. Cloudflare Tunnel** |
| --- | --- | --- |
| Cost | Free | Free tunnel, but you need a domain on Cloudflare (about $10/year) |
| Address | `https://stockpilot.<your-tailnet>.ts.net` (fixed) | `https://api.<your-domain>` (fixed) |
| Setup | Simplest: install, log in, one command | More steps: domain, login, tunnel, DNS route |
| Request time limit | None documented | 100 seconds per request (error 524 after that) |
| Bonus | Private SSH to the laptop from anywhere through Tailscale | Cloudflare's DDoS protection and caching in front |

If you don't own a domain, use **A**.

Throughout, commands marked **(laptop)** run in the laptop's terminal (directly or over SSH); commands marked **(Windows)** run in PowerShell on your main computer. Replace `sai` with the username you choose during the Ubuntu install.

---

## 0. Before you start

You need:
- the laptop: 64-bit, at least 2 GB RAM (4 GB+ is comfortable), 20 GB free disk, its charger;
- a USB stick of 4 GB or more (it will be wiped);
- a network cable for the first setup (Wi-Fi can be set up afterwards);
- your main Windows computer with the SSH key that reaches the Oracle VM (`~/.ssh/stockpilot_deploy`).

**Save the production settings file now.** It holds the database password, `JWT_SECRET` (keeps everyone logged in and keeps transfer files valid), API keys and `REGISTRATION_CODE`. **(Windows):**

```powershell
scp -i $HOME\.ssh\stockpilot_deploy -o UserKnownHostsFile=$HOME\.ssh\stockpilot_known_hosts `
  ubuntu@157.151.152.97:stock-insights/backend/.env $HOME\stockpilot-prod.env
```

Also store its contents in your password manager. You'll copy this file to the laptop in step 5.4.

---

## 1. Install Ubuntu Server 24.04

1. Download **Ubuntu Server 24.04 LTS** (the "amd64" ISO) from ubuntu.com/download/server.
2. Write it to the USB stick with **Rufus** (rufus.ie) or **balenaEtcher** on Windows. In Rufus pick the ISO and click Start; accept the "ISO image mode" default.
3. Plug the network cable and the USB stick into the laptop. Power it on and press the boot-menu key (often **F12**, **F9**, **Esc** or **F2**; it flashes on screen) and choose the USB stick.
4. Choose **Try or Install Ubuntu Server**. In the installer:
   - Language and keyboard: your choice.
   - Type of install: **Ubuntu Server** (not "minimized").
   - Network: the cable connection should show an address. If the installer lists your Wi-Fi, you can configure it here too.
   - Proxy: leave empty. Mirror: accept the default.
   - Storage: **Use an entire disk** (this erases the laptop). Leave "Set up this disk as an LVM group" ticked. Confirm **Continue**.
   - Profile: your name; **server name `stockpilot`** (this becomes part of the Funnel address); username, e.g. `sai`; a strong password.
   - Ubuntu Pro: **Skip for now**.
   - SSH: tick **Install OpenSSH server**. Leave "Allow password authentication over SSH" on for now; you'll turn it off in step 2.3.
   - Featured snaps: select **none**.
5. When it says **Reboot now**, remove the USB stick when prompted and let it restart.
6. Log in on the laptop with your username and password. Find its local address:

   ```bash
   ip -4 addr | grep inet      # (laptop) e.g. "inet 192.168.1.42/24 ... enp3s0"
   ```

   Note the address (here `192.168.1.42`) and the network (`192.168.1.0/24`).

**Recommended:** in your router's admin page, add a **DHCP reservation** so the laptop always gets the same local address.

---

## 2. Basic setup

### 2.1 Log in from Windows over SSH

**(Windows)** create a key for the laptop and copy it over (enter the laptop password once):

```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\stockpilot_laptop -C "stockpilot laptop"
type $HOME\.ssh\stockpilot_laptop.pub | ssh sai@192.168.1.42 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
ssh -i $HOME\.ssh\stockpilot_laptop sai@192.168.1.42
```

The last command should log in **without** asking for the laptop password. From here on you can do everything over SSH.

### 2.2 Updates, time zone and tools

**(laptop):**

```bash
sudo apt update && sudo apt -y full-upgrade
sudo apt -y install git curl ufw unattended-upgrades
sudo timedatectl set-timezone Etc/UTC     # same as the Oracle VM; the scheduler converts to New York time itself
```

Automatic security updates, with a reboot (only when an update needs one) at 08:30 UTC, which is before the US pre-market:

```bash
sudo dpkg-reconfigure -plow unattended-upgrades     # answer "Yes"
sudo tee /etc/apt/apt.conf.d/52stockpilot > /dev/null << 'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "08:30";
EOF
```

### 2.3 Turn off SSH password logins

Only do this after step 2.1 works with the key. **(laptop):**

```bash
echo "PasswordAuthentication no" | sudo tee /etc/ssh/sshd_config.d/10-no-passwords.conf
sudo systemctl restart ssh
```

Keep the Windows terminal you're logged in with open, and test a **new** `ssh -i $HOME\.ssh\stockpilot_laptop sai@192.168.1.42` before closing it.

### 2.4 Firewall

Nothing needs to come in from the internet: both tunnels connect **outwards**. Only allow SSH from your home network. Use the network from step 1.6 (e.g. `192.168.1.0/24`). **(laptop):**

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.1.0/24 to any port 22 proto tcp
sudo ufw enable                 # answer "y"
sudo ufw status verbose
```

### 2.5 Wi-Fi (optional, if you don't want to keep the cable)

Skip this if the installer already set up Wi-Fi or you stay on a cable (a cable is more reliable). **(laptop):**

```bash
sudo apt -y install wpasupplicant         # needs the cable connection
ip link                                    # find the Wi-Fi name, starts with "wl", e.g. wlp2s0
sudo tee /etc/netplan/60-wifi.yaml > /dev/null << 'EOF'
network:
  version: 2
  wifis:
    wlp2s0:
      dhcp4: true
      access-points:
        "YOUR-WIFI-NAME":
          password: "YOUR-WIFI-PASSWORD"
EOF
sudo chmod 600 /etc/netplan/60-wifi.yaml
sudo netplan apply
ip -4 addr show wlp2s0                     # should show an address
```

Replace `wlp2s0`, the network name and the password. If the Wi-Fi address differs from the cable's, update your DHCP reservation and the address you SSH to.

---

## 3. Keep the laptop always on

### 3.1 Don't sleep when the lid closes

**(laptop):**

```bash
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
sudo systemctl restart systemd-logind
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target
```

Test: close the lid, wait a minute, and check the laptop still answers `ssh`.

### 3.2 Turn back on after a power cut

The battery covers short cuts. For longer ones, reboot into the BIOS/UEFI setup (usually **F2**, **F1**, **Del** or **F10** at power-on) and look for **"AC Power Recovery"**, **"Power On with AC Attach"**, **"Wake on AC"** or **"Auto Power On"**, and enable it. Not every laptop has it; without it, press the power button after a long outage.

### 3.3 Protect the battery (if supported)

Charging to 100% around the clock can swell an old battery. Many Lenovo, Dell, ASUS and some HP laptops support a charge limit. **(laptop):**

```bash
ls /sys/class/power_supply/            # e.g. BAT0, AC
cat /sys/class/power_supply/BAT0/charge_control_end_threshold 2>/dev/null || echo "no charge limit support"
```

If a number appears, limit charging to 80% with TLP:

```bash
sudo apt -y install tlp
sudo sed -i 's/^#\?START_CHARGE_THRESH_BAT0=.*/START_CHARGE_THRESH_BAT0=75/; s/^#\?STOP_CHARGE_THRESH_BAT0=.*/STOP_CHARGE_THRESH_BAT0=80/' /etc/tlp.conf
sudo systemctl enable --now tlp
sudo tlp start
sudo tlp-stat -b | grep -i thresh       # should show 75 / 80
```

If there's no support: check the laptop maker's BIOS for a "battery conservation"/"primarily AC use" mode, or remove the battery if it's removable (you then lose protection against short power cuts). Keep the laptop somewhere ventilated, not on fabric.

---

## 4. (Optional) See temperature and health

```bash
sudo apt -y install lm-sensors && sensors        # CPU temperature; under ~70 °C idle is fine
df -h /                                          # disk space
```

---

## 5. Install the backend

These mirror sections 4–7 of `deploy/oracle-setup.sh`, without Caddy and without the Oracle firewall changes (the tunnel replaces both).

### 5.1 Code

**(laptop):**

```bash
git clone https://github.com/saikovuri/Stock_Insights_dashboard.git ~/stock-insights
```

### 5.2 Python 3.13 and packages (through uv)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
cd ~/stock-insights/backend
uv venv --python 3.13 venv
uv pip install --python venv/bin/python -r requirements.txt
```

### 5.3 Allow the deploy script to restart the service

`deploy/update.sh` uses `sudo` for two commands. Let your user run exactly those without a password, so automatic deploys (section 7) work:

```bash
sudo tee /etc/sudoers.d/stock-insights > /dev/null << EOF
$USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart stock-insights, /usr/bin/journalctl -u stock-insights -n 30 --no-pager
EOF
sudo chmod 440 /etc/sudoers.d/stock-insights
sudo visudo -c        # must say "parsed OK"
```

### 5.4 Settings file

**(Windows)** copy the production file you saved in step 0:

```powershell
scp -i $HOME\.ssh\stockpilot_laptop $HOME\stockpilot-prod.env sai@192.168.1.42:stock-insights/backend/.env
```

**(laptop)** lock it down and **turn the scheduler off while testing**, so the laptop and the Oracle VM don't both send alerts:

```bash
chmod 600 ~/stock-insights/backend/.env
echo "SCHEDULER_ENABLED=0" >> ~/stock-insights/backend/.env
grep -c "=" ~/stock-insights/backend/.env      # about a dozen lines
```

Nothing else in the file changes: `CORS_ORIGINS` lists the frontend (Vercel) addresses, not the backend's, and `DATABASE_URL` uses Supabase's pooler, which works from a home connection. If you ever turned on **Network restrictions** in Supabase (Project settings → Database), add your home IP there.

Once copied, delete `$HOME\stockpilot-prod.env` from Windows if the password manager has it.

### 5.5 Service (starts on boot, restarts on crash)

**(laptop):**

```bash
sudo tee /etc/systemd/system/stock-insights.service > /dev/null << EOF
[Unit]
Description=StockPilot API
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$HOME/stock-insights/backend
ExecStart=$HOME/stock-insights/backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now stock-insights
sleep 10
curl -s http://127.0.0.1:8000/health; echo
curl -s http://127.0.0.1:8000/api/health; echo     # also checks the database
```

Both should answer with an OK status. If not: `sudo journalctl -u stock-insights -n 50 --no-pager`.

Keep **one worker** (`--workers 1`): the scheduler and cache must not run twice. The server only listens on `127.0.0.1`; only the tunnel can reach it.

---

## 6A. Option A: Tailscale Funnel

### 6A.1 Account and install

1. Create a free account at **tailscale.com** (Personal plan; sign in with Google, Microsoft or GitHub).
2. **(laptop):**

   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```

   It prints a login URL. Open it on any computer, sign in, and approve the laptop.
3. In the Tailscale admin console (login.tailscale.com/admin/machines): find **stockpilot** → **⋯** → **Disable key expiry**. Without this the laptop drops off after 180 days and the site goes down.
4. Allow Tailscale through the firewall: `sudo ufw allow in on tailscale0`.

### 6A.2 Turn on Funnel

**(laptop):**

```bash
sudo tailscale funnel --bg http://127.0.0.1:8000
```

The first time, it prints a link to enable **HTTPS certificates** and **Funnel** for your tailnet. Open it, approve, and run the command again. Then:

```bash
tailscale funnel status
```

It shows your public address, for example `https://stockpilot.tail1234ab.ts.net`. `--bg` keeps it on across reboots.

### 6A.3 Test

From your phone on mobile data (not your Wi-Fi), or **(Windows)**:

```powershell
curl.exe https://stockpilot.tail1234ab.ts.net/api/health
```

The first request after enabling can take a few minutes while DNS and the certificate are set up.

### 6A.4 Bonus: SSH from anywhere

Install Tailscale on your Windows computer and sign in with the same account. Then you can reach the laptop from anywhere with `ssh -i $HOME\.ssh\stockpilot_laptop sai@stockpilot` (add `sudo tailscale set --ssh` on the laptop if you prefer Tailscale's own SSH).

To turn the public address off later: `sudo tailscale funnel reset`.

---

## 6B. Option B: Cloudflare Tunnel

### 6B.1 Domain on Cloudflare

1. Create a free account at **cloudflare.com**.
2. Either buy a domain in Cloudflare (**Domain Registration → Register Domains**, at cost, about $10/year for `.com`), or add a domain you already own (**Add a domain**) and change its nameservers at your current registrar to the two Cloudflare shows. Wait until Cloudflare says the domain is **Active**.
3. You'll use the subdomain `api.<your-domain>` for the backend. Below, replace `example.com` with your domain.

### 6B.2 Install cloudflared

**(laptop):**

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg > /dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt -y install cloudflared
cloudflared --version
```

### 6B.3 Create the tunnel

**(laptop):**

```bash
cloudflared tunnel login
```

It prints a URL. Open it on any computer, log in to Cloudflare and click your domain. It saves `~/.cloudflared/cert.pem` on the laptop. Then:

```bash
cloudflared tunnel create stockpilot              # prints the tunnel ID (a long UUID)
cloudflared tunnel route dns stockpilot api.example.com
```

The second command creates the `api.example.com` DNS record pointing at the tunnel.

### 6B.4 Configure and run it as a service

Put the config and credentials where the system service reads them. **(laptop):**

```bash
TUNNEL_ID=$(cloudflared tunnel list | awk '$2=="stockpilot" {print $1}')
echo "$TUNNEL_ID"                                  # must not be empty
sudo mkdir -p /etc/cloudflared
sudo cp ~/.cloudflared/"$TUNNEL_ID".json /etc/cloudflared/
sudo chmod 600 /etc/cloudflared/"$TUNNEL_ID".json
sudo tee /etc/cloudflared/config.yml > /dev/null << EOF
tunnel: $TUNNEL_ID
credentials-file: /etc/cloudflared/$TUNNEL_ID.json
ingress:
  - hostname: api.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
EOF
sudo cloudflared service install
sudo systemctl enable --now cloudflared
systemctl status cloudflared --no-pager
cloudflared tunnel info stockpilot                 # should list active connections
```

Use `http://127.0.0.1:8000`, not `localhost`: the backend only listens on IPv4.

(Alternative: Cloudflare's dashboard can create a "remotely managed" tunnel under **Zero Trust → Networks → Tunnels**, giving one `sudo cloudflared service install <TOKEN>` command; add a public hostname `api` → `http://127.0.0.1:8000`. Use one method, not both.)

### 6B.5 Cloudflare settings to check

- **Security → Bots → Bot Fight Mode: off.** Otherwise Cloudflare may answer API calls from the app with a challenge page (error 403 with HTML).
- **Caching:** the default doesn't cache API responses (no file extensions), so nothing to change.
- Requests longer than **100 seconds** fail with error 524. Most StockPilot calls are far shorter; the first build of a large scan may hit it, so retry after a minute (the result is then cached).

### 6B.6 Test

```powershell
curl.exe https://api.example.com/api/health
```

---

## 7. Automatic deploys (replaces the GitHub → Oracle SSH deploy)

GitHub can't SSH into a laptop behind your router, so the laptop checks GitHub every 5 minutes instead. It deploys a new commit only after **all GitHub checks for that commit have passed**, which is the same rule as today. It restarts the server only when `backend/` or `deploy/` changed.

### 7.1 The update script

**(laptop):**

```bash
cat > ~/stock-insights-autoupdate.sh << 'EOF'
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
EOF
chmod +x ~/stock-insights-autoupdate.sh
bash ~/stock-insights-autoupdate.sh && echo "script OK"
```

The script lives outside the repo, so `git pull` never overwrites it.

### 7.2 Run it every 5 minutes

```bash
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
sudo systemctl enable --now stock-insights-autoupdate.timer
systemctl list-timers stock-insights-autoupdate.timer --no-pager
```

See what it did: `journalctl -u stock-insights-autoupdate -n 30 --no-pager`.

A commit whose checks failed is never deployed; the next passing commit is. The GitHub API allows 60 unauthenticated requests an hour, and the script calls it only when there's a new commit.

---

## 8. Switch production to the laptop

Do these in order. Below, `NEW_URL` is your address from 6A or 6B, e.g. `https://stockpilot.tail1234ab.ts.net` or `https://api.example.com` (no trailing slash, no `/api`).

1. **Let the browser call the new address.** In the repo, edit [vercel.json](vercel.json): in the `Content-Security-Policy` value, add `NEW_URL` to `connect-src`, next to `https://157-151-152-97.sslip.io` (keep both during the switch). Commit and push; Vercel redeploys on its own.
2. **Point the frontend at the laptop.** Vercel → the project → **Settings → Environment Variables** → set `VITE_API_URL` = `NEW_URL` (Production) → **Deployments** → latest → **⋯ → Redeploy**.
3. **Stop the Oracle backend** so only one scheduler runs. **(Windows):**

   ```powershell
   ssh -i $HOME\.ssh\stockpilot_deploy -o UserKnownHostsFile=$HOME\.ssh\stockpilot_known_hosts ubuntu@157.151.152.97 "sudo systemctl disable --now stock-insights"
   ```

4. **Turn the laptop's scheduler on. (laptop):**

   ```bash
   sed -i '/^SCHEDULER_ENABLED=0$/d' ~/stock-insights/backend/.env
   sudo systemctl restart stock-insights
   ```

5. **Stop GitHub from deploying to Oracle.** GitHub → repo → **Settings → Secrets and variables → Actions** → delete `OCI_HOST` (the deploy step then skips and reports success, which section 7 relies on). You can delete `OCI_SSH_KEY` and `OCI_KNOWN_HOSTS` too.
6. **Test:** open the Vercel site, sign in (existing logins keep working because `JWT_SECRET` is the same), open Portfolio, Ideas and a stock page. Check the laptop logs while you click: `sudo journalctl -u stock-insights -f`.
7. **Phone apps (if you use them):** change the native fallback URL in [frontend/src/api/config.js](frontend/src/api/config.js) to `NEW_URL`, push, then rebuild and reinstall them (setup.md section 5.5).
8. **After a week without problems:** remove `https://157-151-152-97.sslip.io` from `vercel.json`, update the addresses in setup.md, and terminate the Oracle instance **and its boot volume** in the Oracle console (Compute → Instances → stockpilot → **Terminate**, tick "Permanently delete the attached boot volume"). Do this before Oct 30 if your Oracle account is Pay As You Go, so nothing reaches your card.

**Going back** (while the Oracle VM still exists): set `VITE_API_URL` back to `https://157-151-152-97.sslip.io` and redeploy Vercel, put `SCHEDULER_ENABLED=0` on the laptop and restart it, then `sudo systemctl enable --now stock-insights` on the Oracle VM.

**Rate limits:** the server limits requests per visitor IP. Cloudflare passes the visitor's IP through, so limits stay per visitor. With Tailscale Funnel, check the log lines from step 6: if every request shows `127.0.0.1` instead of real addresses, all visitors share one limit. That's fine for personal use.

---

## 9. Get told when it's down

Create a free account at **uptimerobot.com** → **New monitor** → type **HTTP(s)** → URL `NEW_URL/api/health` → interval 5 minutes → alert by email. It emails you on power, internet or server outages.

If you set up Sentry (`SENTRY_DSN` in `.env`), server errors are reported there as before.

---

## 10. Everyday commands (laptop)

```bash
sudo systemctl status stock-insights            # running?
sudo journalctl -u stock-insights -f            # live logs (Ctrl+C to stop)
sudo systemctl restart stock-insights           # restart
bash ~/stock-insights/deploy/update.sh          # deploy the latest code now, skipping the CI check
journalctl -u stock-insights-autoupdate -n 30   # what the auto-deploy did
nano ~/stock-insights/backend/.env              # change settings, then restart
tailscale funnel status                         # Option A
systemctl status cloudflared                    # Option B
df -h / ; free -m ; sensors                     # disk, memory, temperature
sudo reboot                                     # everything comes back by itself
```

---

## 11. Troubleshooting

| Symptom | Check / fix |
| --- | --- |
| Site loads but every API call fails | Browser console shows a CSP error: `NEW_URL` missing from `connect-src` in `vercel.json`. Otherwise check `VITE_API_URL` in Vercel and redeploy. |
| Public address gives 502 / "bad gateway" | The backend is down: `sudo systemctl status stock-insights`, then `sudo journalctl -u stock-insights -n 50`. |
| `/health` works, `/api/health` returns 503 | Database unreachable: check `DATABASE_URL`, Supabase status, and Supabase network restrictions. |
| Funnel address doesn't open | `tailscale funnel status`; wait up to 10 minutes after first enabling; make sure Funnel and HTTPS were approved in the admin console. |
| Laptop disappeared from Tailscale after months | Key expired: Admin console → Machines → stockpilot → Disable key expiry, then `sudo tailscale up`. |
| Cloudflare error 1033 | `cloudflared` isn't running: `sudo systemctl restart cloudflared`, `cloudflared tunnel info stockpilot`. |
| Cloudflare error 524 | A request took over 100 seconds (usually the first big scan). Retry after a minute. |
| Cloudflare 403 with an HTML page | Bot Fight Mode is on; turn it off (6B.5). |
| Alerts or notifications arrive twice | Both the Oracle VM and the laptop run the scheduler. Stop one (section 8, step 3). |
| New commits aren't deployed | `journalctl -u stock-insights-autoupdate -n 30`. "still running": wait for CI. "failed": fix CI (GitHub → Actions). An Oracle deploy failure here means `OCI_HOST` still exists. |
| Laptop went to sleep | Redo section 3.1; check `systemctl status sleep.target` says "masked". |
| Laptop stays off after a power cut | Enable the BIOS power-on-AC setting (3.2). |
| `sudo: a password is required` in auto-deploy logs | Redo 5.3; the sudoers line must match the commands exactly. |
| Disk filling up | `sudo journalctl --vacuum-size=200M`, `sudo apt autoremove`. |
