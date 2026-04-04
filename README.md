# Stock Insights Dashboard

AI-powered stock analysis dashboard built with Streamlit.

## Features

- **Key Metrics** — Real-time price, P/E, market cap, moving averages, volume
- **Interactive Charts** — Candlestick/line charts with 20/50-day moving averages
- **News Sentiment** — Live news with NLP sentiment scoring (positive/negative/neutral)
- **AI Summary** — GPT-powered stock analysis with buy/hold/sell recommendation
- **Alerts** — Auto-detected signals: price swings, volume spikes, 52-week proximity, MA crossovers
- **Portfolio Tracking** — Add holdings, track P/L in real-time

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up API keys (optional but recommended)
cp .env.example .env
# Edit .env with your keys:
#   OPENAI_API_KEY  — for AI summaries (get from https://platform.openai.com)
#   NEWS_API_KEY    — for live news (get from https://newsapi.org)

# 3. Run the dashboard
streamlit run app.py
```

The dashboard works without API keys — you'll get rule-based analysis instead of AI, and placeholder news instead of live feeds.

## API Keys

| Key | Source | Required? | What it enables |
|-----|--------|-----------|-----------------|
| `OPENAI_API_KEY` | [OpenAI](https://platform.openai.com/api-keys) | Optional | AI-powered stock summaries and recommendations |
| `NEWS_API_KEY` | [NewsAPI](https://newsapi.org/register) | Optional | Live news headlines with sentiment analysis |

## Project Structure

```
├── app.py              # Streamlit dashboard (main entry point)
├── stock_data.py       # Stock price & metrics via yfinance
├── news_sentiment.py   # News fetching + TextBlob sentiment
├── ai_summary.py       # OpenAI GPT analysis (with offline fallback)
├── portfolio.py        # Portfolio CRUD + P/L calculation
├── alerts.py           # Smart alert detection
├── config.py           # Configuration & env loading
├── requirements.txt    # Python dependencies
└── .env.example        # API keys template
```

## Future Roadmap

- [ ] Scheduled daily email/Slack alerts
- [ ] Multi-ticker comparison view
- [ ] Technical indicators (RSI, MACD, Bollinger)
- [ ] Watchlist with batch analysis
- [ ] Historical portfolio performance chart
- [ ] Export reports to PDF
