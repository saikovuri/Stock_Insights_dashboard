# Stock Insights Dashboard

AI-powered stock research and portfolio assistant. FastAPI backend + React (Vite/Capacitor) frontend.

## Features

- **AI Brief** — one call per ticker: summary, why it's moving (with cited headlines), bull/bear case, risks, catalysts, rule-based technical signals
- **AI Chat (tool-calling)** — the model pulls live quotes, technicals, news, fundamentals, SEC filings, peers and *your portfolio* on demand
- **Portfolio Doctor** — concentration, sector exposure, beta, correlation, volatility, drawdown, tax-loss candidates, upcoming earnings + AI review
- **Alerts & Daily Briefing** — scanned every 15 min during market hours and each weekday morning; in-app bell + optional free phone push via [ntfy](https://ntfy.sh)
- **News Sentiment** — AI-scored sentiment and relevance (VADER fallback)
- Charts & indicators, screener, watchlist, options tools (IV rank, structures, pre-trade checklist), fundamentals, ownership, dividends

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
deploy/                Oracle VM setup, Supabase RLS
```
