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

```bash
cd backend
pip install -r requirements.txt
cp ../.env.example .env        # fill in the free keys below
uvicorn main:app --reload

cd ../frontend
npm install && npm run dev
```

Everything degrades gracefully: without keys you get Yahoo data and rule-based analysis.

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
