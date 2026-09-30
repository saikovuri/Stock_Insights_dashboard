import logging
from datetime import datetime, timezone

import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from cache import get_or_fetch
from providers import finnhub_company_news
import llm

log = logging.getLogger(__name__)

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


def fetch_news(ticker: str, company_name: str = "", max_articles: int = 12) -> list[dict]:
    """Recent news (Finnhub, then yfinance) scored by the LLM, with VADER as fallback. Cached 15 min."""
    def _fetch():
        articles = _finnhub_news(ticker, max_articles) or _yfinance_news(ticker, max_articles)
        return _score_articles(ticker, company_name, articles)
    return get_or_fetch(f"newsraw:{ticker}", _fetch, ttl=900)


def _finnhub_news(ticker: str, max_articles: int) -> list[dict]:
    items = sorted(finnhub_company_news(ticker), key=lambda a: a.get("datetime", 0), reverse=True)
    seen, results = set(), []
    for a in items:
        title = (a.get("headline") or "").strip()
        if not title or title in seen:
            continue
        seen.add(title)
        ts = a.get("datetime")
        results.append({
            "title": title,
            "summary": (a.get("summary") or "")[:300],
            "source": a.get("source") or "Unknown",
            "url": a.get("url", ""),
            "published": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ts else "",
        })
        # Over-fetch so relevance filtering still leaves enough
        if len(results) >= max_articles * 2:
            break
    return results


def _score_articles(ticker: str, company_name: str, articles: list[dict]) -> list[dict]:
    if not articles:
        return []
    scores = _llm_scores(ticker, company_name, articles) if llm.ai_enabled() else None
    for i, a in enumerate(articles):
        if scores:
            s, rel = scores[i]
            a["relevance"] = rel
        else:
            s = _analyze_sentiment(f"{a['title']}. {a.get('summary', '')}")
        a["sentiment"] = round(s, 3)
        a["sentiment_label"] = _sentiment_label(s)
        a["scored_by"] = "ai" if scores else "lexicon"

    if scores:
        relevant = [a for a in articles if a.get("relevance", 1) >= 0.3]
        if len(relevant) >= 3:
            articles = relevant
    return articles[:12]


def _llm_scores(ticker: str, company_name: str, articles: list[dict]) -> list[tuple[float, float]] | None:
    lines = "\n".join(
        f"{i + 1}. {a['title']}" + (f" — {a['summary'][:160]}" if a.get("summary") else "")
        for i, a in enumerate(articles)
    )
    system = "You score financial news for equity investors. Output JSON only."
    user = (
        f"Stock: {ticker} ({company_name or ticker}).\n"
        "For each numbered item give [sentiment, relevance]:\n"
        "- sentiment: impact on THIS stock's shareholders, -1 (very negative) to 1 (very positive), 0 if neutral\n"
        "- relevance: 0 to 1, how much the item is actually about this company\n"
        f'Return {{"scores": [[s, r], ...]}} with exactly {len(articles)} pairs in order.\n\n{lines}'
    )
    try:
        # VADER is the fallback, so don't let sentiment eat the time budget of the request that needs it
        data = llm.chat_json(system, user, temperature=0, max_tokens=1200, budget_s=20, light=True)
        raw = data.get("scores")
        if not isinstance(raw, list) or len(raw) != len(articles):
            return None
        return [(max(-1.0, min(1.0, float(s))), max(0.0, min(1.0, float(r)))) for s, r in raw]
    except Exception as e:
        log.info("LLM sentiment failed for %s, using lexicon: %s", ticker, e)
        return None


def _yfinance_news(ticker: str, max_articles: int) -> list[dict]:
    """Fetch news from yfinance (free, no API key)."""
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news or []
    except Exception:
        return []

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
            published = datetime.fromtimestamp(pub_date, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        elif isinstance(pub_date, str):
            published = pub_date

        if not title:
            continue
        results.append({
            "title": title,
            "summary": (content.get("summary") or "")[:300],
            "source": publisher,
            "url": link,
            "published": published,
        })

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
