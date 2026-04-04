import requests
from textblob import TextBlob
from config import NEWS_API_KEY


def fetch_news(ticker: str, company_name: str = "", max_articles: int = 10) -> list[dict]:
    """Fetch recent news articles for a stock from NewsAPI."""
    if not NEWS_API_KEY:
        return _fallback_news(ticker)

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
    except Exception:
        return _fallback_news(ticker)

    return _process_articles(articles)


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
        sentiment = TextBlob(text).sentiment.polarity

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
