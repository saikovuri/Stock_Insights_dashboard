import requests
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config import NEWS_API_KEY

# VADER with financial lexicon for accurate stock sentiment
_sia = SentimentIntensityAnalyzer()
_sia.lexicon.update({
    # Market direction
    "bull": 2.0, "bullish": 3.0, "bear": -2.0, "bearish": -3.0,
    "rally": 2.0, "rebound": 1.5, "recovery": 1.5, "correction": -1.5,
    # Analyst actions
    "upgrade": 2.5, "downgrade": -2.5, "outperform": 2.5, "underperform": -2.5,
    "overweight": 1.5, "underweight": -1.5,
    # Price movement
    "surge": 2.5, "soar": 2.5, "jump": 1.5, "climb": 1.0,
    "plunge": -3.0, "crash": -3.5, "tumble": -2.5, "slump": -2.0, "drop": -1.5, "sink": -2.0,
    # Earnings
    "beat": 1.5, "miss": -1.5, "exceed": 1.5, "disappoint": -2.0,
    "blowout": 2.0, "shortfall": -2.0,
    # Fundamentals
    "growth": 1.5, "decline": -1.5, "profit": 1.0, "loss": -1.5,
    "revenue": 0.5, "debt": -0.5, "bankruptcy": -4.0, "default": -3.0,
    "dividend": 1.0, "buyback": 1.5, "dilution": -1.5,
    # Market conditions
    "oversold": 1.0, "overbought": -1.0, "breakout": 2.0, "breakdown": -2.0,
    "momentum": 1.0, "volatile": -0.5, "volatility": -0.5,
    # Events
    "acquisition": 1.0, "merger": 0.5, "layoff": -1.5, "layoffs": -1.5,
    "lawsuit": -1.5, "investigation": -1.5, "fraud": -3.5, "recall": -2.0,
})


def _analyze_sentiment(text: str) -> float:
    """Get compound sentiment score using VADER + financial lexicon. Range: -1 to +1."""
    if not text:
        return 0.0
    return _sia.polarity_scores(text)["compound"]


def fetch_news(ticker: str, company_name: str = "", max_articles: int = 10) -> list[dict]:
    """Fetch recent news articles — tries NewsAPI first, falls back to yfinance."""
    # Try NewsAPI if key is configured
    if NEWS_API_KEY:
        articles = _newsapi_fetch(ticker, company_name, max_articles)
        if articles:
            return articles

    # Free fallback: yfinance news (no API key needed)
    return _yfinance_news(ticker, max_articles)


def _newsapi_fetch(ticker: str, company_name: str, max_articles: int) -> list[dict]:
    query = f"{ticker} stock"
    if company_name:
        query = f"{company_name} OR {ticker}"

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "sortBy": "publishedAt",
        "pageSize": max_articles,
        "language": "en",
        "apiKey": NEWS_API_KEY,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("articles", [])
        return _process_articles(articles)
    except Exception:
        return []


def _yfinance_news(ticker: str, max_articles: int) -> list[dict]:
    """Fetch news from yfinance (free, no API key)."""
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news or []
    except Exception:
        return _fallback_news(ticker)

    if not news_items:
        return _fallback_news(ticker)

    results = []
    for item in news_items[:max_articles]:
        # yfinance >= 0.2.44 nests everything under 'content'
        content = item.get("content", item)  # fall back to item itself for older versions

        title = content.get("title", "")

        # Provider can be a dict (new) or a plain string (old)
        provider = content.get("provider") or {}
        if isinstance(provider, dict):
            publisher = provider.get("displayName", "Unknown")
        else:
            publisher = content.get("publisher", str(provider) or "Unknown")

        # URL can be nested under canonicalUrl (new) or plain 'link' (old)
        canonical = content.get("canonicalUrl") or {}
        if isinstance(canonical, dict):
            link = canonical.get("url", "")
        else:
            link = content.get("link", "") or item.get("link", "")

        # Publication date
        pub_date = content.get("pubDate", "") or item.get("providerPublishTime", "")
        published = ""
        if isinstance(pub_date, (int, float)):
            from datetime import datetime, timezone
            published = datetime.fromtimestamp(pub_date, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(pub_date, str):
            published = pub_date

        # Sentiment analysis on title + summary
        summary_text = content.get("summary", "")
        analysis_text = f"{title}. {summary_text}" if summary_text else title
        sentiment = _analyze_sentiment(analysis_text)

        results.append({
            "title": title,
            "source": publisher,
            "url": link,
            "published": published,
            "sentiment": round(sentiment, 3),
            "sentiment_label": _sentiment_label(sentiment),
        })

    return results if results else _fallback_news(ticker)


def _fallback_news(ticker: str) -> list[dict]:
    """Return placeholder when no API key is configured."""
    return [
        {
            "title": f"No news API key configured — add NEWS_API_KEY to .env to see live news for {ticker}",
            "source": "System",
            "url": "",
            "published": "",
            "sentiment": 0.0,
            "sentiment_label": "Neutral",
        }
    ]


def _process_articles(articles: list[dict]) -> list[dict]:
    """Analyze sentiment for each article."""
    results = []
    for art in articles:
        title = art.get("title") or ""
        description = art.get("description") or ""
        text = f"{title}. {description}"
        sentiment = _analyze_sentiment(text)

        results.append(
            {
                "title": title,
                "source": (art.get("source") or {}).get("name", "Unknown"),
                "url": art.get("url", ""),
                "published": art.get("publishedAt", ""),
                "sentiment": round(sentiment, 3),
                "sentiment_label": _sentiment_label(sentiment),
            }
        )
    return results


def _sentiment_label(score: float) -> str:
    if score > 0.1:
        return "Positive"
    if score < -0.1:
        return "Negative"
    return "Neutral"


def aggregate_sentiment(articles: list[dict]) -> dict:
    """Compute overall sentiment stats from a list of scored articles."""
    if not articles:
        return {"avg": 0, "label": "Neutral", "positive": 0, "negative": 0, "neutral": 0}

    scores = [a["sentiment"] for a in articles]
    avg = sum(scores) / len(scores)

    return {
        "avg": round(avg, 3),
        "label": _sentiment_label(avg),
        "positive": sum(1 for s in scores if s > 0.1),
        "negative": sum(1 for s in scores if s < -0.1),
        "neutral": sum(1 for s in scores if -0.1 <= s <= 0.1),
    }
