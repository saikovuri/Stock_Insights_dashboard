# StockPilot setup and handover guide

This guide is for setting StockPilot up on a new computer and running it without outside help. Read section 1 **before** you lose access to the current machine.

- What the app does, screen by screen: [intro.md](intro.md)
- Project overview and API key list: [README.md](README.md)
- Steps before each production release: [deploy/RELEASE_CHECKLIST.md](deploy/RELEASE_CHECKLIST.md)

---

## 1. Do this before you lose access to the current machine

None of these items are in GitHub. Keep them somewhere safe, such as a password manager:

| Save | Where it is now | Why you need it |
| --- | --- | --- |
| Every value in `backend/.env` (`JWT_SECRET`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `FINNHUB_API_KEY`, `TWELVEDATA_API_KEY`, `SEC_USER_AGENT`, `CORS_ORIGINS`, ...) | `backend/.env` on this machine | Without these the app has no AI or real-time data. Keep the **same `JWT_SECRET`** if you want old account-transfer files to import. |
| Your local data | `backend/stockinsights.db` (SQLite). The E*TRADE imports you tested locally live here, **not** in production. | Run `.venv\Scripts\python.exe backend\backup_sqlite.py` and copy the file from `backups\`. Or use **Portfolio → Holdings → Data tools → Export data to another login** to get a JSON file. |
| SSH access to the production laptop | Key `~/.ssh/stockpilot_laptop` on this machine. The laptop (`sai-kovouri@192.168.87.20`) only accepts SSH from its home network (or through Tailscale if you add your PC to the tailnet). | You can also just use the laptop's own keyboard and screen. |
| The production `backend/.env` on the laptop, including `DATABASE_URL` | `~/stock-insights/backend/.env` on the laptop | On the laptop: `cat ~/stock-insights/backend/.env`, and store the output in your password manager. A rebuild needs it (`deploy/laptop-setup.sh` asks for it). |
| `BACKUP_PASSPHRASE` | A GitHub secret (set 2026-10-12; first backup succeeded that day), and your password manager | Without it the weekly database backups cannot be decrypted. |
| Logins for GitHub, Vercel, Supabase, Oracle Cloud, Groq, Google AI Studio, Finnhub, Twelve Data, Sentry (if used), ntfy topic | Your accounts | Every service is on a free tier, but you must be able to sign in to each one. |

Finally, run `git status` and push anything that isn't pushed yet.

---

## 2. How the pieces fit together

```mermaid
flowchart LR
  U[Browser / Android / iOS app] -->|HTTPS| V[Vercel: React frontend]
  U -->|HTTPS /api| F[Tailscale Funnel]
  F --> B[FastAPI backend on the home laptop, uvicorn, 1 worker]
  B --> DB[(Supabase PostgreSQL)]
  B --> P[Finnhub, Yahoo, CBOE, SEC, Groq/Gemini, ntfy]
  B -->|every 5 min: pull commits that passed CI| GH[GitHub master branch]
  GH -->|Vercel Git integration| V
```

| Piece | Production | Local development |
| --- | --- | --- |
| Frontend | https://stock-insights-dashboard.vercel.app (Vercel) | http://localhost:5173 (Vite; `/api` is forwarded to port 8000) |
| Backend | https://stockpilot.tail112222.ts.net (home laptop `sai-kovouri-dell`, Ubuntu Desktop 24.04, published with Tailscale Funnel, systemd service `stock-insights`; moved from the Oracle VM on 2026-10-13, see [setup_laptop.md](setup_laptop.md)) | http://localhost:8000 (uvicorn) |
| Database | Supabase PostgreSQL (`DATABASE_URL`) | SQLite file `backend/stockinsights.db`, used when `DATABASE_URL` is empty |
| CI/CD | `.github/workflows/ci.yml` (tests), `db-backup.yml` (weekly encrypted backup); the laptop deploys itself (section 5.1). `deploy-oci.yml` (old Oracle deploy) now skips because `OCI_HOST` is deleted. | `scripts/check.ps1` runs the same checks |

Versions: **Python 3.13** (`backend/.python-version` says 3.13.14), **Node 22**, React 19, Vite 6, Capacitor 8.

---

## 3. Set up on a new computer

### 3.1 Install the tools

- Git: https://git-scm.com/downloads
- Python 3.13: https://www.python.org/downloads/ (on Windows, tick **Add python.exe to PATH**)
- Node.js 22 LTS: https://nodejs.org
- Optional: VS Code
- Optional: Android Studio (for the Android app)
- Optional: a Mac with Xcode (for the iOS app)

### 3.2 Clone and set up

```powershell
git clone https://github.com/saikovuri/Stock_Insights_dashboard.git
cd Stock_Insights_dashboard
powershell -ExecutionPolicy Bypass -File scripts\setup-local.ps1     # Windows
```

```bash
bash scripts/setup-local.sh                                          # macOS / Linux
```

The script:
1. creates `.venv` and installs the backend packages;
2. creates `backend/.env` from `.env.example` with a fresh random `JWT_SECRET`, if the file doesn't exist yet;
3. runs `npm install` in `frontend/`;
4. installs the Playwright test browser.

### 3.3 Fill in `backend/.env`

Paste the values you saved in section 1. If you are starting fresh, every key below has a free tier:

| Variable | Needed? | What it does / where to get it |
| --- | --- | --- |
| `JWT_SECRET` | **Yes** | Signs logins and account-transfer files. Use a long random string. Changing it logs everyone out and invalidates old transfer files. |
| `DATABASE_URL` | Production only | PostgreSQL connection string (Supabase → Connect). Leave it empty locally to use SQLite. The backend refuses to start with the default secret when this is set. |
| `CORS_ORIGINS` | Yes | Comma-separated frontend origins. Local: `http://localhost:5173`. The VM also needs `https://stock-insights-dashboard.vercel.app,capacitor://localhost,http://localhost`. |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | Recommended | AI brief, chat, sentiment, doctor and weekly review. Keys from https://console.groq.com/keys and https://aistudio.google.com/apikey. `AI_PROVIDER=groq` or `gemini` picks which one is tried first. |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional | Only if `AI_PROVIDER=openai`. |
| `FINNHUB_API_KEY` | Recommended | Real-time quotes, news and earnings (https://finnhub.io/register). Without it the app falls back to Yahoo. `FINNHUB_RATE_PER_MIN` defaults to 55. |
| `TWELVEDATA_API_KEY` | Optional | Price-history fallback. |
| `SEC_USER_AGENT` | Yes | `StockPilot your@email.com`. SEC requires a contact address. |
| `SCHEDULER_ENABLED` | Optional | `1` (default) runs the alert scan and morning briefing. Use `0` for one-off scripts. |
| `ALERT_SCAN_MINUTES`, `BRIEFING_HOUR_ET`, `PRICE_CHANGE_ALERT`, `VOLUME_SPIKE_ALERT` | Optional | Alert timing and thresholds. |
| `NTFY_SERVER` | Optional | Phone push server (default https://ntfy.sh). Each user enters their topic in the app. |
| `REGISTRATION_CODE` | Optional | When set, creating an account requires this invite code (existing users can still sign in). Unset means open sign-up. |
| `TOKEN_EXPIRE_MINUTES`, `REFRESH_EXPIRE_DAYS` | Optional | Session length (defaults: 60 minutes and 30 days). |
| `RESEARCH_UNIVERSE_SOURCE` | Optional | Dated S&P constituent snapshots for the scanner (see README). |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT` | Optional | Backend error tracking. |
| `STOCKPILOT_DB_PATH` | Optional | A different SQLite file path. Tests set this themselves. |

Frontend build variables (set in Vercel, or in a `frontend/.env.local` file):

| Variable | What it does |
| --- | --- |
| `VITE_API_URL` | Backend origin without `/api`: `https://stockpilot.tail112222.ts.net`. Leave it empty locally (Vite forwards `/api`). The native mobile app falls back to the address hard-coded in `frontend/src/api/config.js`. |
| `VITE_SENTRY_DSN` | Optional frontend error tracking. |

### 3.4 Run it

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1      # opens two windows: backend and frontend
```

```bash
bash scripts/dev.sh                                           # Ctrl+C stops both
```

Open http://localhost:5173 and register a user. Locally the database starts empty unless you restore a backup (section 3.5).

Manual equivalent:

```powershell
cd backend; ..\.venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload
cd frontend; npm run dev
```

Check the backend at http://localhost:8000/api/health. It should return `{"status":"ok","db":"connected"}`.

### 3.5 Bring your data back

**SQLite backup:**
1. Stop the backend.
2. Delete `backend/stockinsights.db-wal` and `backend/stockinsights.db-shm` if they exist.
3. Copy the backup over `backend/stockinsights.db`.
4. Start the backend and sign in with your old username and password.

**Export file:**
1. Sign in to the new installation.
2. Go to Portfolio → Holdings → Data tools → **Import data from another login**.
3. This needs the same `JWT_SECRET` as the installation that made the file.

**Into production:** sign in at the Vercel URL and use **Import from broker CSV** (Holdings) to re-import your E*TRADE positions files. Then check the cash balance in the account bar.

---

## 4. Testing

Run every check that CI runs (about 2–3 minutes):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

```bash
bash scripts/check.sh
```

Run a single test:

| What | Command (from the repo root) |
| --- | --- |
| Backend, by name | `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -k next_steps` |
| Frontend unit test | `cd frontend; npx vitest run src -t "next steps"` |
| Browser (e2e) test | `cd frontend; npx playwright test -g "watchlist"` (tests the built `dist/`, served on port 4174; run `npm run build` first or results are stale) |
| Phone layout audit | With local servers running: `cd frontend; node scripts/mobile-audit.mjs http://localhost:5173 $env:TEMP\mobile-audit` (add `desktop` as a third argument for 1440-wide screenshots). Registers a throwaway local user with sample positions, screenshots every main view at Pixel 7 size and lists elements wider than the screen. Local only. |

What the tests do:
- Backend tests use a throwaway SQLite database, never your real one.
- Browser tests use fake API responses, so they don't need API keys.
- CI also runs a disposable PostgreSQL 16 job (`backend/tests/postgres_checks.py`). Run it locally only against a database whose name ends in `_test` and with `STOCKPILOT_DISPOSABLE_DB=1`.

---

## 5. Production

### 5.1 How a change reaches production

1. Commit and `git push origin master`.
2. **Backend:** GitHub runs CI (`ci.yml`). Every 5 minutes the laptop's `stock-insights-autoupdate.timer` checks GitHub; once **all** checks on the newest master commit have passed, it runs `deploy/update.sh` (`git pull`, install packages, restart, health check). Commits that don't touch `backend/` or `deploy/` are pulled without a restart. A commit with failing checks is never deployed.
3. **Frontend:** Vercel builds `frontend/` on each push to master. It uses `vercel.json` for the build command and the security headers.
4. Check the result:
   - GitHub → Actions tab;
   - `curl https://stockpilot.tail112222.ts.net/api/health`;
   - on the laptop: `journalctl -u stock-insights-autoupdate -n 20`;
   - open the Vercel URL.

GitHub repository secrets (Settings → Secrets and variables → Actions):

| Secret | Used by |
| --- | --- |
| `OCI_SSH_KEY`, `OCI_KNOWN_HOSTS` | Old Oracle deploy; unused since 2026-10-13 (`OCI_HOST` deleted, so `deploy-oci.yml` skips). Delete them when the Oracle instance is terminated. |
| `DATABASE_URL` | Weekly backup. Supabase **session-mode** URI, port 5432. |
| `BACKUP_PASSPHRASE` | Weekly backup encryption. |

Vercel project environment variables: `VITE_API_URL` and, optionally, `VITE_SENTRY_DSN`. Redeploy after changing them.

### 5.2 Run the server by hand

On the laptop (its own terminal, or `ssh -i ~/.ssh/stockpilot_laptop sai-kovouri@192.168.87.20` from the home network):

```bash
sudo systemctl status stock-insights          # is it running?
sudo journalctl -u stock-insights -f          # live logs
sudo systemctl restart stock-insights         # restart
bash ~/stock-insights/deploy/update.sh        # pull + restart now, without waiting for the timer
journalctl -u stock-insights-autoupdate -n 30 # what the auto-deploy did
nano ~/stock-insights/backend/.env            # change settings, then restart
sudo tailscale funnel status                  # public address on?
```

Health checks:
- `/health` only shows that the process is alive.
- `/api/health` also checks the database (it returns 503 if the database is down).
- `python backend/release_check.py --base-url https://stockpilot.tail112222.ts.net` runs read-only provider checks.

### 5.3 Rebuild the backend server from scratch

Use this if the laptop dies or you move to another machine. On any Ubuntu 24.04 machine (Desktop or Server), as your normal user:

```bash
bash <(curl -fsSL "https://raw.githubusercontent.com/saikovuri/Stock_Insights_dashboard/master/deploy/laptop-setup.sh?$(date +%s)")
```

It's safe to re-run. It stops once to ask for `backend/.env` (paste your saved copy), and once for the Tailscale sign-in. If the old server is still running, add `SCHEDULER_ENABLED=0` to the new `.env`, stop the old service, then run the same command with ` cutover` at the end. If the public address changes, update Vercel `VITE_API_URL` (then Redeploy), `connect-src` in [vercel.json](vercel.json) and the fallback in [frontend/src/api/config.js](frontend/src/api/config.js). Details and troubleshooting: [setup_laptop.md](setup_laptop.md).

**Old Oracle VM:** shut down on 2026-10-13, not yet terminated, so it can be started again from the Oracle console for a rollback. To roll back: start the instance, `sudo systemctl enable --now stock-insights` on it, stop the laptop service, and set `VITE_API_URL` back to `https://157-151-152-97.sslip.io` (still allowed in `vercel.json`). Once you're sure, terminate the instance **and its boot volume** in the Oracle console, remove the sslip address from `vercel.json`, and delete the `OCI_*` secrets. Its setup script, [deploy/oracle-setup.sh](deploy/oracle-setup.sh), no longer runs as-is (Caddy's apt repository returns 402; see section 6).

Alternative host: [render.yaml](render.yaml) describes the same backend for Render.com. Render's free tier sleeps when idle, which pauses the scheduler.

Home laptop: [setup_laptop.md](setup_laptop.md) runs the backend on an always-on Ubuntu 24.04 laptop, reached through Tailscale Funnel or Cloudflare Tunnel, with a pull-based auto-deploy that waits for CI.

### 5.4 Database (Supabase)

- **Tables:** the backend creates and updates tables itself at startup (`database.init_db`). There are no manual migrations.
- **Row-level security:** after a new database's first start, run [deploy/supabase_rls.sql](deploy/supabase_rls.sql) in the Supabase SQL editor. It blocks Supabase's public REST roles from your tables.
- **Backups:**
  - automatic every Sunday (GitHub Actions artifact, kept for 90 days). Needs both repo secrets: `DATABASE_URL` (Supabase session pooler, port 5432; set 2026-10-12) and `BACKUP_PASSPHRASE` (choose a long passphrase, store it in your password manager, then `gh secret set BACKUP_PASSPHRASE` and type it at the prompt, or add it under Settings → Secrets and variables → Actions). Until both exist, the workflow fails at "Check secrets". Test with Actions → Database backup → Run workflow;
  - manual: `DATABASE_URL=... bash deploy/backup.sh`.
- **Restore:** `gpg -d FILE.sql.gz.gpg | gunzip | psql "$TARGET_DATABASE_URL"`. Practise on a scratch database first. A new Supabase project or a non-Supabase Postgres needs small preparations first; see [move_to_local_db.md](move_to_local_db.md).
- **Moving the database** (second Supabase project, Postgres or SQLite on the laptop, Neon): [move_to_local_db.md](move_to_local_db.md).
- **Pausing:** free Supabase projects pause after a week without activity. The weekly backup counts as activity. If the project pauses anyway, press **Restore** in the Supabase dashboard.

### 5.5 Mobile apps (Capacitor)

The app ID is `com.stockinsights.app` and the web files come from `frontend/dist`.

**Android** (needs Android Studio):
1. Run `cd frontend; npm run cap:android`. This builds the frontend, copies it into `android/` and opens Android Studio.
2. Run on a device, or use Build → Generate Signed Bundle. Keep the signing keystore safe; you cannot update a Play Store app without it.

**iOS** (needs a Mac with Xcode and an Apple developer account):
1. Run `npm run cap:ios`.
2. Sign and run from Xcode.

The bundled app calls the URL in `VITE_API_URL`, or the fallback in `src/api/config.js`. Rebuild and re-sync whenever the backend address changes. Test on a real phone: login, background/resume, notifications.

---

## 6. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Something seems broken and you don't know where to start | Sign in and open **System status** (footer). It shows the database, each data provider, AI configuration and the background jobs. Fix whatever is red first. |
| The page says "This view could not be displayed" after many edits while the dev server runs | Vite's hot reload got stale. Stop the frontend window and run `npm run dev` again, then hard-refresh the browser. |
| `npm install` / `npm ci` fails with EPERM or locked esbuild on Windows | Stop the dev servers first, then retry from inside `frontend/`. |
| `npm ci` fails downloading from `ms-feed-25.pkgs.visualstudio.com` | About 320 entries in `frontend/package-lock.json` were resolved through a Microsoft public package mirror on the old machine. It allows anonymous downloads today. If that stops: in `frontend/`, delete `package-lock.json` and `node_modules`, run `npm install --registry https://registry.npmjs.org/`, run `scripts/check.ps1`, then commit the new lockfile. |
| `npm audit` (or `scripts/check.ps1`) fails with ECONNRESET / "audit endpoint returned an error" | A network problem, not a vulnerability. Run `npm audit --audit-level=high` again later; CI runs it too. |
| The frontend shows network errors and the backend window shows CORS errors | Add the exact origin (scheme + host + port) to `CORS_ORIGINS` and restart the backend. |
| The production site loads but every API call fails | Check `VITE_API_URL` in Vercel and `connect-src` in `vercel.json`. The browser console shows CSP errors. |
| `/api/health` returns 503 | The database can't be reached. Check `DATABASE_URL` and whether Supabase is paused. |
| A backend test fails only between 8 pm and midnight Eastern | The test builds dates with `date.today()`. Use New York time (see the existing tests). |
| A PostgreSQL query works locally but fails on the server | Use `database.PH` for SQL placeholders (`?` in SQLite, `%s` in PostgreSQL); see `database._run`. |
| Option quote "unavailable" for a position | The data provider has no quote. The stress test won't guess a price; use **Run without it** (the result is then marked as leaving it out), close or edit the position, or wait for a quote. |
| Quotes are slow or rate-limited | Finnhub's free tier allows about 60 calls/minute. Lower the number of watchlist and holding tickers, or set `FINNHUB_RATE_PER_MIN`. |
| `apt update` on the Oracle VM fails with `402 Payment Required` for `dl.cloudsmith.io` (seen 2026-10-10) | Caddy's package repository refuses downloads, so `deploy/oracle-setup.sh` would stop at step 1 on a rebuild. Caddy already installed keeps working. For a rebuild, install Caddy another way (see caddyserver.com/docs/install) and remove `/etc/apt/sources.list.d/caddy-stable.list`, or move to the laptop ([setup_laptop.md](setup_laptop.md)), which doesn't use Caddy. |
| Lost SSH key | Oracle cannot re-download it. Create a new pair (`ssh-keygen -t ed25519 -f ~/.ssh/stockpilot_new`), then add the `.pub` line to `~/.ssh/authorized_keys` on the VM. Without any working key: Oracle Cloud console → the instance → **Console connection** (or **Run command**, if the Oracle Cloud Agent plugin is enabled) to append it, or rebuild the VM (section 5.3). Also update the `OCI_SSH_KEY` secret in GitHub (Settings → Secrets → Actions) if you replace the deploy key, so CI deploys keep working. |

---

## 7. Where things are in the code

| Area | Backend | Frontend |
| --- | --- | --- |
| App entry, routes | `backend/main.py`, `routes_*.py`, `api_common.py` (auth dependency, rate limiter) | `src/App.jsx`, `src/api/stockApi.js` (all API calls) |
| Database | `database.py` (SQLite/PostgreSQL, schema in `init_db`), `accounting.py` (audit ledger) | — |
| Portfolio, accounts, cash | `accounts.py`, `corporate_actions.py`, `account_transfer.py` | `components/Portfolio.jsx`, `Accounts.jsx`, `ClosedHistory.jsx` |
| Broker CSV import | `portfolio_insights.py` (`parse_broker_csv`, `parse_activity_csv`, `parse_history_csv`) | `components/PortfolioInsights.jsx` (`ImportCsv`) |
| Suggested next steps | `next_steps.py` | `components/NextSteps.jsx` |
| Option alerts, stress test | `options_desk.py` | `components/OptionsDesk.jsx` |
| Expiration ladder, rules, trim planner | `expiry_ladder.py`, `trading_rules.py`, `trim_plan.py` | `components/ExpiryLadder.jsx`, `RiskTools.jsx` |
| System status | `system_status.py`, `scheduler.HEARTBEAT` | `components/SystemStatus.jsx` |
| Journal edge report and P&L calendar | (uses closed-trade APIs) | `components/Journal.jsx`, `PnlCalendar.jsx` |
| Stock page: your positions, chart levels, since last look | `my_stock.py` | `components/MyStock.jsx`, `CandleChart.jsx`, `SinceLastLook.jsx` |
| Watchlist buy zones, earnings/ex-div week | `buy_zones.py`, `routes_watchlist.py` | `components/WatchlistExtras.jsx` |
| Ideas portfolio fit | `portfolio_fit.py` | `components/PortfolioFit.jsx` |
| Command palette (Ctrl+K) | — | `components/CommandPalette.jsx` (add destinations to `COMMANDS`) |
| Options math, wheel, covered calls, rolls | `options_analytics.py`, `wheel.py` | `components/WheelIdeas.jsx`, `WheelManager.jsx`, `RollRepair.jsx` |
| Quotes and market data | `stock_data.py`, `providers.py`, `cache.py` | — |
| AI | `llm.py`, `ai_brief.py`, `ai_chat.py`, `portfolio_doctor.py` | `components/AiChat.jsx`, `PortfolioDoctor.jsx` |
| Alerts, briefing, push | `alerts.py`, `scheduler.py` | `components/Alerts.jsx` |
| Scanner and ideas | `scanner.py`, `market_context.py` | `components/Ideas.jsx` |
| Tests | `backend/tests/` | `src/portfolio.test.jsx`, `e2e/smoke.spec.js` |

**Adding a feature, step by step:**
1. Put the logic in a backend module, as a plain function that is easy to unit test.
2. Add a route in `main.py` or a `routes_*.py` file with `Depends(get_current_user)` and `@limiter.limit(...)`.
3. Add a backend test in `backend/tests/`.
4. Add a fetch function in `src/api/stockApi.js`.
5. Build the component and render it where it belongs.
6. Add a Vitest test.
7. Update [intro.md](intro.md): this repo's rule is that the feature guide always matches the code.
8. Run `scripts/check.ps1`.
9. Commit and push.

---

## 8. Suggested next work (next few days)

Ordered by value for effort. Each item names where to start.

1. **Get your real E*TRADE data into production.**
   - Sign in at the Vercel URL and re-import both positions files under Holdings → Import from broker CSV, into accounts named like the local ones.
   - Money-market funds now land in cash. Check the cash shown in the account bar.
   - Your local fixes, such as the deleted stale NVDA put, do not exist in production.
2. **Fix purchase dates on imported lots.** E*TRADE's positions file has no dates, so the lots are dated on the import day. That makes the long-term/short-term tax checks and the "vs S&P" numbers wrong. Either:
   - edit each lot (Holdings → ✏️ → **Purchase date** → Save); or
   - import E*TRADE's transaction history with **Transaction history**, which records real dates.

   After changing dates, check Holdings for any newly offered split adjustment.
3. **Use Sync for repeat imports** (built). Holdings → Data tools → Import from broker CSV → **Sync account to this file** compares the file with an account, shows the differences, and only changes what differs. It also flags cost-basis differences ("Cost differs: kept"), which you fix by editing the lot.
4. **Test the importers with your real files.**
   - Fixtures now cover title rows above the header, byte-order marks, Windows line endings, Schwab/E*TRADE/Fidelity cash and total rows, and Robinhood/Webull activity layouts. Real exports can still differ.
   - If a real file fails, the preview shows "Detected columns". Add the missing header spelling to `_COLS` or `_ACTIVITY_COLS` in `portfolio_insights.py`, then add that file's header to the test.
5. **Manage the AMD $580 short calls that are now in the money.**
   - Suggested next steps → **🔧 Repair** (or Option alerts → Repair) prices rolls for short calls (strategy `cc` in `options_analytics.roll_ideas`).
6. **Restrict sign-up on the public server** (built; needs one setting).
   - `/api/auth/register` is open while `REGISTRATION_CODE` is unset. Each user sees only their own data, but strangers would use your free API quotas.
   - On the VM: `echo 'REGISTRATION_CODE=<a code you choose>' >> ~/stock-insights/backend/.env`, then `sudo systemctl restart stock-insights`. The sign-up form then asks for the code; give it only to people you invite.
7. **Housekeeping:** once a month, run `npm outdated` / `pip list --outdated`, upgrade one package at a time, run `scripts/check.ps1`, then push.
8. **Monitoring:**
    - create free Sentry projects and set `SENTRY_DSN` (VM `.env`) and `VITE_SENTRY_DSN` (Vercel) so production errors reach you by email;
    - set up an ntfy topic in the app for phone alerts.
9. **Every December: extend the market calendar.** `backend/market_calendar.py` lists NYSE full-day closures (`HOLIDAYS`) and 1 p.m. early closes (`EARLY_CLOSES`) for 2026–2027 only. Add the next year from nyse.com; otherwise scans and alerts run on holidays with frozen quotes.
10. **Live option quotes (optional, needs you).** Option data comes from Yahoo and can lag. For your own positions, the free E*TRADE API gives real-time quotes, but it needs your consumer key/secret from developer.etrade.com and a daily OAuth approval, and its data is for your use only. Start in `options_analytics._chain` / `_spot` behind an env var, and test in E*TRADE's sandbox first. Shared scans (Wheel, Setups) would need a paid feed that allows redistribution.

Before each production release, follow [deploy/RELEASE_CHECKLIST.md](deploy/RELEASE_CHECKLIST.md).

## 9. Simplification plan (what to remove or merge)

The app has about 70 views. Fewer, clearer views help new users more than new features. Remove one at a time, run `scripts/check.ps1`, and update `intro.md`.

**Removed (Oct 2026):** the unused `EarningsMoves.jsx` and its `/earnings-moves` route; the unreachable correlation view in `PortfolioInsights.jsx`; Reddit attention and prediction markets (`MarketContext.jsx`, `backend/market_context.py`, `/api/market/context`); the Ideas → Superinvestors tab and `/api/ideas/superinvestors`. The stock page's Smart money card still lists superinvestors for one ticker and now starts the 13F refresh itself.

**Kept by choice:** Dashboard → Analysis → **Short interest & smart money**. Its insider-buying line overlaps Fundamentals → Ownership → Insider Trades, but it is the only insider view for the Day trader style.

**Merged and renamed (Oct 2026), nothing lost:**
- The Options **Flow** tab now sits inside **Volatility & positioning** (`OptionsHub.jsx`); day traders see it first, long-term investors folded. Ideas → Unusual options remains the market-wide scan.
- **Portfolio Doctor** is the on-request **Portfolio health** strip at the top of Suggested next steps (`PortfolioDoctor.jsx`); its full review stays under an expandable section.
- **Daily briefing** and **Market overview** are one **Today** card (`MarketOverview.jsx` renders `DailyBriefing.jsx`), with a single 14-day earnings list.
- The checklist and position calculator were already inside **Plan a trade**; the button is now primary with a one-line hint.
- Labels: **Signals** (stock Overview), **Price alerts**, **Option alerts** (Portfolio Risk; the anchor id stays `position-alerts`), **Next steps**. The bell stays **Notifications**.

**Already done (Oct 2026)**: login export/import moved out of Journal into Portfolio → Holdings → Data tools and renamed (it is not for brokerage accounts); the account bar is compact outside Holdings; the stock Overview shows the price before alerts; phone layouts tightened (three metrics per row, three form fields per row, consistent holding rows, positions listed before the entry forms, open options and peers as cards); "Use this when" notes on Income ideas, Wheel candidates and Manage a wheel position; a Jump-to row on Portfolio Risk.
