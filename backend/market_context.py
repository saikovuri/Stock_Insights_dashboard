import html
import json
import math
import os
import re
from datetime import datetime, timezone

import requests

from cache import get_or_fetch


def _number(value, minimum=0):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= minimum else None
    except (TypeError, ValueError):
        return None


def _date(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def normalize_attention(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Unexpected attention response")
    rows, seen = [], set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker", "")).upper()
        mentions = _number(item.get("mentions"))
        previous = _number(item.get("mentions_24h_ago"))
        rank = _number(item.get("rank"), 1)
        if not re.fullmatch(r"[A-Z]{1,6}(?:[.-][A-Z]{1,2})?", ticker) or ticker in seen:
            continue
        if mentions is None or not mentions.is_integer() or rank is None or not rank.is_integer():
            continue
        if previous is not None and not previous.is_integer():
            previous = None
        seen.add(ticker)
        rows.append({
            "ticker": ticker, "name": html.unescape(str(item.get("name") or ticker))[:160],
            "rank": int(rank), "mentions": int(mentions), "previous_mentions": previous,
            "change_pct": round((mentions / previous - 1) * 100, 1) if previous else None,
            "url": f"https://apewisdom.io/stocks/{ticker}/",
        })
    return sorted(rows, key=lambda row: row["rank"])[:12]


def _array(value):
    try:
        result = json.loads(value) if isinstance(value, str) else value
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def normalize_predictions(events, now):
    if not isinstance(events, list):
        raise ValueError("Unexpected prediction response")
    rows, seen = [], set()
    for event in events:
        if not isinstance(event, dict) or event.get("closed") is not False or event.get("active") is not True:
            continue
        slug = event.get("slug", "")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]{1,250}", slug):
            continue
        markets = event.get("markets")
        if not isinstance(markets, list):
            continue
        for market in markets:
            if not isinstance(market, dict) or market.get("closed") is not False or market.get("active") is not True:
                continue
            identifier = str(market.get("id") or "")
            question = market.get("question")
            end = _date(market.get("endDate"))
            outcomes = _array(market.get("outcomes"))
            prices = [_number(price) for price in _array(market.get("outcomePrices"))]
            if not identifier or identifier in seen or not isinstance(question, str) or not question.strip():
                continue
            if not end or end <= now or len(outcomes) != 2 or set(map(str, outcomes)) != {"Yes", "No"}:
                continue
            if len(prices) != 2 or any(price is None or price > 1 for price in prices) or abs(sum(prices) - 1) > .02:
                continue
            seen.add(identifier)
            updated = _date(market.get("updatedAt"))
            volume = _number(market.get("volume24hr"))
            liquidity = _number(market.get("liquidityNum", market.get("liquidity")))
            change = _number(market.get("oneDayPriceChange"), -1) if outcomes[0] == "Yes" else None
            warnings = []
            if not updated:
                warnings.append("Provider update time unavailable")
            elif (now - updated).total_seconds() > 86400 or (updated - now).total_seconds() > 300:
                warnings.append("Provider timestamp is stale or inconsistent")
            if liquidity is None:
                warnings.append("Liquidity unavailable")
            elif liquidity < 10000:
                warnings.append("Low reported liquidity (under $10,000)")
            if volume is None:
                warnings.append("24h volume unavailable")
            elif volume < 1000:
                warnings.append("Low 24h volume (under $1,000)")
            rows.append({
                "id": identifier, "question": question[:400], "event": str(event.get("title") or "")[:250],
                "yes_pct": round(prices[outcomes.index("Yes")] * 100, 2),
                "change_pp": round(change * 100, 2) if change is not None and change <= 1 else None,
                "volume_24h": volume, "liquidity": liquidity, "end_at": end.isoformat(),
                "updated_at": updated.isoformat() if updated else None, "warnings": warnings,
                "url": f"https://polymarket.com/event/{slug}",
            })
    return sorted(rows, key=lambda row: row["volume_24h"] or 0, reverse=True)[:12]


def _get(url, params=None):
    response = requests.get(url, params=params, timeout=(3, 10),
                            headers={"User-Agent": "StockPilot/1.0 (read-only market context)"})
    response.raise_for_status()
    return response.json()


def get_context(kind):
    if kind not in ("attention", "predictions"):
        raise ValueError("Unknown context kind")
    source = "ApeWisdom / Reddit" if kind == "attention" else "Polymarket"
    if os.getenv("EXTERNAL_CONTEXT_ENABLED", "1") != "1":
        return {"status": "disabled", "source": source, "rows": [], "fetched_at": None,
                "message": "External market context is disabled by the operator."}

    def fetch():
        try:
            if kind == "attention":
                rows = normalize_attention(_get("https://apewisdom.io/api/v1.0/filter/all-stocks/page/1"))
                scope = "Selected stock-focused Reddit communities; first 100 ranked symbols sampled. Not X coverage."
            else:
                events = []
                for tag in ("economy", "finance"):
                    batch = _get("https://gamma-api.polymarket.com/events", {
                        "tag_slug": tag, "active": "true", "closed": "false", "limit": 20,
                        "order": "volume24hr", "ascending": "false",
                    })
                    if not isinstance(batch, list):
                        raise ValueError("Unexpected event list")
                    events.extend(batch)
                rows = normalize_predictions(events, datetime.now(timezone.utc))
                scope = "Economy and finance events sampled by 24h volume; not an exhaustive catalyst calendar."
            return {"status": "ready", "source": source, "rows": rows,
                    "fetched_at": datetime.now(timezone.utc).isoformat(), "scope": scope}
        except (requests.RequestException, ValueError, TypeError):
            return {"status": "unavailable", "source": source, "rows": [], "fetched_at": None,
                    "message": f"{source} data is unavailable. Missing data does not mean no activity."}

    return get_or_fetch(f"market-context:v1:{kind}", fetch, ttl=600)