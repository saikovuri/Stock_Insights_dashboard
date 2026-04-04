from openai import OpenAI
from config import OPENAI_API_KEY


def get_ai_summary(metrics: dict, sentiment: dict, news: list[dict]) -> str:
    """Generate an AI-powered stock summary and recommendation."""
    if not OPENAI_API_KEY:
        return _offline_summary(metrics, sentiment)

    client = OpenAI(api_key=OPENAI_API_KEY)

    headlines = "\n".join(
        f"- {a['title']} (Sentiment: {a['sentiment_label']})" for a in news[:8]
    )

    prompt = f"""You are a stock market analyst. Provide a concise analysis for {metrics['name']} ({metrics.get('sector', 'N/A')}).

KEY METRICS:
- Price: ${metrics['price']} ({metrics['change_pct']:+.2f}% today)
- P/E Ratio: {metrics.get('pe_ratio', 'N/A')}
- Market Cap: {metrics.get('market_cap', 'N/A')}
- 52-Week Range: ${metrics.get('52w_low', 'N/A')} - ${metrics.get('52w_high', 'N/A')}
- 50-Day Avg: ${metrics.get('50d_avg', 'N/A')} | 200-Day Avg: ${metrics.get('200d_avg', 'N/A')}
- Beta: {metrics.get('beta', 'N/A')}
- Volume: {metrics.get('volume', 'N/A')} (Avg: {metrics.get('avg_volume', 'N/A')})

NEWS SENTIMENT: {sentiment['label']} (Score: {sentiment['avg']})
- Positive articles: {sentiment['positive']}
- Negative articles: {sentiment['negative']}
- Neutral articles: {sentiment['neutral']}

RECENT HEADLINES:
{headlines}

Provide:
1. **Summary** (2-3 sentences on current state)
2. **Key Signals** (3-4 bullet points — technical + fundamental)
3. **Sentiment Take** (1-2 sentences on news mood)
4. **Recommendation** (Buy / Hold / Sell with brief reasoning)
5. **Risk Factors** (2-3 bullet points)

Keep it actionable and under 300 words. Add a disclaimer that this is not financial advice."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional stock analyst providing concise, data-driven insights."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI analysis unavailable: {e}\n\n{_offline_summary(metrics, sentiment)}"


def _offline_summary(metrics: dict, sentiment: dict) -> str:
    """Generate a basic rule-based summary when OpenAI is not available."""
    price = metrics.get("price", 0)
    change_pct = metrics.get("change_pct", 0)
    pe = metrics.get("pe_ratio")
    avg_50 = metrics.get("50d_avg", 0)
    avg_200 = metrics.get("200d_avg", 0)
    high_52 = metrics.get("52w_high", 0)
    low_52 = metrics.get("52w_low", 0)

    signals = []

    # Trend signals
    if price and avg_50:
        if price > avg_50:
            signals.append("Trading above 50-day moving average (bullish)")
        else:
            signals.append("Trading below 50-day moving average (bearish)")

    if price and avg_200:
        if price > avg_200:
            signals.append("Trading above 200-day moving average (long-term bullish)")
        else:
            signals.append("Trading below 200-day moving average (long-term bearish)")

    # Valuation
    if pe:
        if pe < 15:
            signals.append(f"P/E of {pe:.1f} suggests undervaluation")
        elif pe > 30:
            signals.append(f"P/E of {pe:.1f} suggests premium valuation")
        else:
            signals.append(f"P/E of {pe:.1f} is in a reasonable range")

    # 52-week position
    if high_52 and low_52 and price:
        range_pct = (price - low_52) / (high_52 - low_52) * 100 if high_52 != low_52 else 50
        signals.append(f"At {range_pct:.0f}% of 52-week range")

    # Recommendation
    bullish = sum(1 for s in signals if "bullish" in s.lower() or "underval" in s.lower())
    bearish = sum(1 for s in signals if "bearish" in s.lower() or "premium" in s.lower())

    if sentiment["label"] == "Positive":
        bullish += 1
    elif sentiment["label"] == "Negative":
        bearish += 1

    if bullish > bearish:
        rec = "**HOLD/BUY** — Majority of signals are positive"
    elif bearish > bullish:
        rec = "**HOLD/SELL** — Caution warranted, several bearish signals"
    else:
        rec = "**HOLD** — Mixed signals, monitor closely"

    lines = [
        f"## {metrics['name']} — Quick Analysis",
        f"**Price:** ${price:.2f} ({change_pct:+.2f}% today)",
        "",
        "### Key Signals",
        *[f"- {s}" for s in signals],
        "",
        f"### News Sentiment: {sentiment['label']} (Score: {sentiment['avg']})",
        "",
        f"### Recommendation: {rec}",
        "",
        "_Note: Add OPENAI_API_KEY to .env for AI-powered analysis. This is not financial advice._",
    ]
    return "\n".join(lines)
