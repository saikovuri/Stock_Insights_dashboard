"""US economic calendar (Nasdaq's public calendar feed, FOMC schedule as fallback)."""

import html
import logging
from datetime import date, timedelta

import requests

from cache import get_or_fetch

log = logging.getLogger(__name__)

HIGH = ("cpi", "consumer price index", "nonfarm payrolls", "unemployment rate", "interest rate decision",
        "fomc statement", "fomc minutes", "fomc press conference", "fed chair", "powell", "gdp", "pce price",
        "core pce")
MEDIUM = ("ppi", "producer price", "retail sales", "ism manufacturing", "ism non-manufacturing", "ism services",
          "jolts", "initial jobless claims", "consumer confidence", "michigan consumer sentiment",
          "durable goods", "adp nonfarm", "housing starts", "new home sales", "existing home sales",
          "industrial production", "trade balance", "beige book")

# Federal Reserve 2026 FOMC decision days (second day of each meeting)
FOMC_2026 = ["2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
             "2026-10-28", "2026-12-09"]


def _impact(name: str) -> str | None:
    n = name.lower()
    if any(k in n for k in HIGH):
        return "high"
    if any(k in n for k in MEDIUM):
        return "medium"
    return None


def _day(d: date) -> list[dict]:
    def _fetch():
        r = requests.get("https://api.nasdaq.com/api/calendar/economicevents", params={"date": d.isoformat()},
                         headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"}, timeout=10)
        r.raise_for_status()
        rows = ((r.json() or {}).get("data") or {}).get("rows") or []
        out, seen = [], set()
        for x in rows:
            if x.get("country") != "United States":
                continue
            name = html.unescape(x.get("eventName") or "").strip()
            impact = _impact(name)
            if not impact or name in seen:
                continue
            seen.add(name)
            clean = lambda v: (html.unescape(v or "").strip() or None) if (v or "").strip() not in ("", "&nbsp;") else None
            out.append({"date": d.isoformat(), "time_et": x.get("gmt"), "event": name, "impact": impact,
                        "actual": clean(x.get("actual")), "consensus": clean(x.get("consensus")),
                        "previous": clean(x.get("previous"))})
        return out
    return get_or_fetch(f"econ:{d.isoformat()}", _fetch, ttl=3 * 3600)


def economic_calendar(days: int = 7) -> dict:
    today = date.today()
    events, source, failed = [], "Nasdaq", 0
    weekdays = [today + timedelta(days=i) for i in range(days + 1) if (today + timedelta(days=i)).weekday() < 5]
    for d in weekdays:
        try:
            events += _day(d)
        except Exception as e:
            failed += 1
            log.info("Economic calendar unavailable for %s: %s", d, e)
    if weekdays and failed == len(weekdays):
        source = "Federal Reserve schedule"
    fomc = [f for f in FOMC_2026 if today.isoformat() <= f <= (today + timedelta(days=days)).isoformat()]
    for f in fomc:
        if not any(e["date"] == f and "rate decision" in e["event"].lower() for e in events):
            events.append({"date": f, "time_et": "14:00", "event": "FOMC Interest Rate Decision", "impact": "high",
                           "actual": None, "consensus": None, "previous": None})
    events.sort(key=lambda e: (e["date"], e["time_et"] or ""))
    upcoming_fomc = next((f for f in FOMC_2026 if f >= today.isoformat()), None)
    return {"events": events, "next_fomc": upcoming_fomc, "source": source, "days": days}


def high_impact_this_week() -> list[str]:
    try:
        return [f"{e['date']} {e['event']}" for e in economic_calendar(7)["events"] if e["impact"] == "high"][:6]
    except Exception:
        return []
