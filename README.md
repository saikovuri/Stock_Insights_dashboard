# StockPilot

AI-powered stock research and portfolio assistant. FastAPI backend + React (Vite/Capacitor) frontend.

## Features

- **AI Brief** — one call per ticker: summary, why it's moving (with cited headlines), bull/bear case, risks, catalysts, rule-based technical signals
- **AI Chat (tool-calling)** — the model pulls live quotes, technicals, news, fundamentals, SEC filings, peers and *your portfolio* on demand
- **Portfolio Doctor** — concentration, sector exposure, beta, correlation, volatility, drawdown, tax-loss candidates, upcoming earnings + AI review
- **Alerts & Daily Briefing** — scanned every 15 min during market hours and each weekday morning; in-app bell + optional free phone push via [ntfy](https://ntfy.sh)
- **News Sentiment** — AI-scored sentiment and relevance (VADER fallback)
- **Ideas** — S&P 500 setup scanner with a 1-year backtested track record per setup, market-wide unusual options activity, insider cluster buying (Form 4), superinvestor 13F changes, US economic calendar
- **Options hub** — volatility & expected move, covered-call / cash-secured-put ideas, directional structures, and flow & positioning (put/call, max pain, call/put walls, dealer gamma flip) from free CBOE delayed quotes
- **Portfolio insights** — performance vs the same dollars in SPY, projected dividend income calendar, wash-sale warnings, correlation, broker CSV import, weekly AI review
- **Thesis tracker** — write why you own a stock; the AI re-checks it after every earnings report and notifies you
- **Key-level alerts** — one click turns a level from the AI brief into a price alert
- Profile-aware layout (day / swing / long-term), short interest (FINRA), charts & indicators, watchlist, trade journal with position sizing, fundamentals, ownership, dividends

## Quick Start

Full setup on a new machine, production deployment, recovery and troubleshooting: **[setup.md](setup.md)**. The short version:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-local.ps1   # or: bash scripts/setup-local.sh
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1           # or: bash scripts/dev.sh
powershell -ExecutionPolicy Bypass -File scripts\check.ps1         # same checks as CI
```

Manual equivalent:
```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env        # fill in the free keys below
uvicorn main:app --reload

cd ../frontend
npm install && npm run dev
```

Without optional keys, some features use Yahoo data or rule-based analysis. Provider failures can still make data unavailable; an unavailable quote is not a zero price or zero P&L.

## External Market Context

- **Ideas > In play > Reddit attention** shows ApeWisdom's stock-community mention rankings, prior-snapshot counts and changes. Click a ticker for stock research and news; attention itself is not verified news, sentiment or a buy/sell signal. Coverage is a sample of selected Reddit communities, not X or the entire internet. The feed does not supply a reliable update timestamp, so retrieval time is labeled separately.
- **Ideas > Macro calendar > Prediction-market context** shows Polymarket economy/finance questions, Yes prices, 24-hour percentage-point changes, reported liquidity/volume, provider timestamps and links to market resolution rules. Only active, unexpired binary markets with valid prices are displayed. Prices are market-implied, not calibrated probabilities; market end times are not necessarily scheduled economic-release times. Low liquidity/volume thresholds are caution heuristics, not validated trading filters.
- These are read-only public API integrations. No account, wallet, API key, order placement or paid subscription is created. Requests and failures are cached for 10 minutes per server process; retries do not bypass this cache. Attention uses one bounded request; predictions use two (20 economy and 20 finance events), deduplicate markets, and show up to 12 results. Missing feeds remain unavailable instead of being treated as zero activity. Set `EXTERNAL_CONTEXT_ENABLED=0` in the backend environment and restart to disable all new provider requests; the default is `1`.
- **X is not connected.** The [official pricing page](https://docs.x.com/x-api/getting-started/pricing), checked October 5, 2026, describes prepaid pay-per-use access (listed post reads: $0.005/resource; recent counts: $0.005/request). Actual rates/access must be confirmed in the developer console before purchasing credits. No scraping or paid fallback is implemented.
- Source documentation checked: [ApeWisdom API](https://apewisdom.io/api), [Polymarket public data](https://docs.polymarket.com/market-data/discover-markets), [Gamma events API](https://docs.polymarket.com/api-reference/events/list-events). Both public endpoints returned data without authentication during the local smoke check. A public endpoint is not blanket permission for commercial redistribution: ApeWisdom's docs did not establish a redistribution license or SLA, and the [Polymarket terms page](https://polymarket.com/tos) did not expose the full terms in the automated check. Confirm applicable terms, attribution, commercial rights and regional restrictions before public deployment, or disable these feeds. This integration does not bypass trading restrictions or connect to Polymarket US trading.
- Neither feed modifies Wheel eligibility, position sizing or automated alerts. No social-to-stock predictive edge, bot filtering, historical baseline or news corroboration is claimed.

## Portfolio Workflows

- **Holdings** is the default portfolio view, with lot-specific closing, FIFO ticker sales and atomic assignment recording.
- **Portfolio Risk** groups position alerts, earnings exposure, portfolio checks, stress scenarios and correlations.
- **Income & Performance** separates combined marked P&L from premium cash flow, benchmarks, dividends, tax checks and weekly review.
- **Journal** separates recorded stock/option trade history from manual notes and options reviews.
- **Account ledger** under Income & Performance records immutable before/after changes, manual fees, deposits, withdrawals, dividends, account valuations, reversals and explicit quantity-limited strategy/wheel-cycle allocations. Requests are idempotent. Opening fees are allocated proportionally across partial lot sales; the US informational report retains the selected lot and acquisition date. Enter total-account NAV immediately before external cash flows to calculate TWR; missing valuations leave it unavailable. Export produces a JSON accounting report; the change-history API is paginated.
- Personalized wheel plans require sign-in. Enter total account cash **including existing reserves**. Recorded collateral is reserved first; existing stock cost and option collateral count toward name and sector limits. Unknown earnings, unavailable/high correlations, thin quotes and stale scans can produce no eligible trade.

## Verification

Use Python 3.13 and Node 22. From the repository root in PowerShell:

```powershell
$env:PYTHONPATH = "$PWD/backend"
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
.\.venv\Scripts\python.exe -m compileall -q backend
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
Push-Location frontend
npx playwright install chromium
Pop-Location
npm --prefix frontend run test:e2e
npm --prefix frontend audit
```

Backend tests use a temporary SQLite database via `STOCKPILOT_DB_PATH`, not the trading database. Browser tests use synthetic, intercepted API responses and test desktop/mobile production builds without real trade writes. They start a temporary preview server on port 4174. Stop dev servers before a clean `npm ci` on Windows to avoid locked native executables.

The regression workflow runs tests, undefined JavaScript/JSX-name checks, compilation, browser checks and a high-severity dependency audit. A separate disposable PostgreSQL 16 job checks repeatable migrations, concurrent sales/assignment, tenant isolation, immutable audit events and public-role RLS. Backend deployment depends on both jobs passing. See [the release checklist](deploy/RELEASE_CHECKLIST.md) before deployment.

## Research Limits

- Quotes may be delayed. Two-sided midpoint marks are estimates, not executable fills; missing marks suppress aggregate valuation/P&L. The data feed does not guarantee synchronized or fresh bid/ask timestamps.
- Received premium is cash flow, not immediate profit. Combined P&L includes realized trades and marked open liabilities/assets. Capital figures are current stock cost plus conservatively allocated collateral, not broker margin or historical capital-at-risk.
- Position/history corrections remain editable, but database triggers retain immutable before/after events. Existing records become labeled opening snapshots: previously deleted records and earlier edits cannot be reconstructed. Cycle links are explicit, not inferred from matching tickers. The US lot report is informational; wash sales, assignment/exercise adjustments, corporate actions and option-specific tax rules require review. Only recorded fees/cash flows are included. TWR depends on accurate entered total-account valuations, including cash and short-option liabilities.
- Standard 100-share option contracts are assumed. Common cash-settled indexes cannot use physical assignment recording; adjusted/nonstandard contracts require separate accounting.
- Wheel premium estimates use the bid less $1 per contract. Roll natural-price estimates assume $1 per leg. Actual fees/fills differ, and a net credit does not establish risk reduction. Income sizing does not independently verify broker buying power; use the account-aware planner for recorded portfolio constraints.
- Strategy Tester retains the fixed 70/30 development/holdout view and adds five expanding-window forward tests. A declared small parameter grid is selected using preceding training data only, with a five-trade minimum and positive net training return. Windows without a qualifying candidate stay untraded. Forward and double-cost results are separate from training; retuning after seeing them contaminates the experiment.
- Without `RESEARCH_UNIVERSE_SOURCE`, scanner history remains a current-constituent exploration with survivorship bias. Dated constituent snapshots can be imported from a documented provider and selected with this setting; the scanner includes former members and filters signals using information known by US market close. Missing membership dates or prices suppress the historical results. Source completeness, corporate actions and delisting proceeds still need independent verification. Forward returns are not strategy P&L.
- New paper ideas freeze a cost model of $1 commission per leg per side plus $0.01/share slippage per leg per side. Performance is net of these assumptions; legacy uncosted outcomes are excluded. Exact expiry-date closing prices are required. These are hypothetical midpoint-entry observations, not broker fills, and do not model early assignment or management.
- No strategy is demonstrated to have a durable profitable edge. Licensed historical datasets, live-provider validation, actual production RLS/configuration, push delivery and physical Android/iOS behavior remain environment-specific release checks, not properties established by fixture tests.

### Dated Universe Import

Run `python backend/research_universe.py snapshots.json` with the intended database configured, then set `RESEARCH_UNIVERSE_SOURCE` to the imported source name. The file is a JSON array of `{ "as_of": "YYYY-MM-DD", "known_at": "ISO timestamp with timezone", "source": "documented provider/version", "members": ["AAPL", "MSFT"] }` records. Use actual historical publication times, never the current constituent list relabeled with old dates. Existing snapshots cannot be silently replaced or backdated. Automatic Wikipedia observations are archived under `observed-current-wikipedia`; these do not establish complete historical index coverage.

## Free API keys

| Key | Source | What it enables |
|-----|--------|-----------------|
| `GROQ_API_KEY` or `GEMINI_API_KEY` | [Groq](https://console.groq.com/keys) / [Google AI Studio](https://aistudio.google.com/apikey) | AI brief, chat, sentiment, portfolio doctor, briefing |
| `FINNHUB_API_KEY` | [Finnhub](https://finnhub.io/register) | Real-time quotes, company news, analyst trends, peers, earnings calendar |
| `TWELVEDATA_API_KEY` | [Twelve Data](https://twelvedata.com/pricing) | Price-history fallback when Yahoo fails |
| `SEC_USER_AGENT` | (no key) | SEC EDGAR filings — just set a contact email |

Yahoo Finance (`yfinance`) is still used for price history, options chains, financial statements and ownership, with the providers above as primary/fallback sources.

Keyless free sources: CBOE delayed option quotes, FINRA short interest, Nasdaq economic calendar, SEC EDGAR 13F/Form 4, OpenFIGI (CUSIP → ticker).

## Project Structure

```
backend/
  main.py              API routes
  providers.py         Finnhub, Twelve Data, SEC EDGAR clients
  stock_data.py        Quotes, history, indicators (with provider fallbacks)
  news_sentiment.py    News + AI/VADER sentiment
  llm.py               OpenAI-compatible LLM wrapper (Groq/Gemini/OpenAI)
  ai_brief.py          Single-call AI research brief
  ai_chat.py           Tool-calling chat
  portfolio_doctor.py  Portfolio risk analytics + AI review
  scheduler.py         Background alerts + daily briefing
  database.py          SQLite (local) / Postgres (Supabase)
frontend/              React app (web + Capacitor Android/iOS)
deploy/                Oracle VM setup, Supabase RLS, manual backup script
```

## Operations

- **Dependencies** are pinned in `backend/requirements.txt` (Python version in `backend/.python-version`). Upgrade deliberately: bump a version, test locally, then deploy.
- **Error tracking:** set `SENTRY_DSN` (Render) and `VITE_SENTRY_DSN` (Vercel) from a free [Sentry](https://sentry.io) account. Without them monitoring is off.
- **Backups:** `.github/workflows/db-backup.yml` runs every Sunday and stores an AES-256 encrypted `pg_dump` as a workflow artifact for 90 days. Add repo secrets `DATABASE_URL` (Supabase *session* connection string, port 5432) and `BACKUP_PASSPHRASE`. Run it any time from the Actions tab. Restore with `gpg -d FILE.sql.gz.gpg | gunzip | psql "$DATABASE_URL"`.
