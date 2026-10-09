"""Smart money: insider buying clusters (Finnhub, market-wide Form 4 feed) and superinvestor
13F changes (SEC EDGAR, CUSIPs mapped to tickers via OpenFIGI)."""

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import requests

from cache import get_or_fetch
from database import kv_get, kv_set
from providers import _sec_get, finnhub_market_insiders

log = logging.getLogger(__name__)

# ── Insider buying ───────────────────────────────────────────────────────

def insider_buying(days: int = 30) -> dict:
    """Open-market purchases (Form 4 code P) grouped by company; 2+ distinct buyers = cluster."""
    def _fetch():
        today = date.today()
        buys, missing = [], 0
        for i in range(days + 1):
            d = today - timedelta(days=i)
            if d.weekday() >= 5:
                continue
            rows = finnhub_market_insiders(d)
            if not rows:
                missing += 1
            for r in rows:
                sym, change, price = r.get("symbol") or "", r.get("change") or 0, r.get("transactionPrice") or 0
                if (r.get("source") != "sec" or r.get("transactionCode") != "P" or r.get("isDerivative")
                        or change <= 0 or price <= 0 or not re.fullmatch(r"[A-Z]{1,5}", sym)):
                    continue
                buys.append({"symbol": sym, "name": r.get("name"), "shares": change, "price": price,
                             "value": change * price, "date": r.get("transactionDate") or r.get("filingDate")})
        by = defaultdict(list)
        for b in buys:
            if b["value"] >= 10_000:
                by[b["symbol"]].append(b)
        groups = []
        for sym, items in by.items():
            insiders = sorted({b["name"] for b in items})
            groups.append({"symbol": sym, "insiders": len(insiders), "names": insiders[:5],
                           "total_value": round(sum(b["value"] for b in items)),
                           "buys": len(items), "last_date": max(b["date"] or "" for b in items),
                           "avg_price": round(sum(b["value"] for b in items) / sum(b["shares"] for b in items), 2)})
        clusters = sorted((g for g in groups if g["insiders"] >= 2),
                          key=lambda g: (g["insiders"], g["total_value"]), reverse=True)[:25]
        big = sorted((g for g in groups if g["insiders"] == 1 and g["total_value"] >= 250_000),
                     key=lambda g: g["total_value"], reverse=True)[:15]
        if missing > days // 2:
            raise LookupError("Insider feed unavailable")
        return {"clusters": clusters, "big_buys": big, "days": days, "purchases": len(buys),
                "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    try:
        return get_or_fetch(f"insiders:clusters:{days}", _fetch, ttl=6 * 3600)
    except LookupError:
        return {"clusters": [], "big_buys": [], "days": days, "purchases": 0, "unavailable": True}


# ── Superinvestor 13F filings ────────────────────────────────────────────

FUNDS = [
    (1067983, "Warren Buffett", "Berkshire Hathaway"),
    (1336528, "Bill Ackman", "Pershing Square"),
    (1061768, "Seth Klarman", "Baupost Group"),
    (1656456, "David Tepper", "Appaloosa"),
    (1536411, "Stanley Druckenmiller", "Duquesne Family Office"),
    (1040273, "Dan Loeb", "Third Point"),
    (1709323, "Li Lu", "Himalaya Capital"),
    (1167483, "Chase Coleman", "Tiger Global"),
    (1061165, "Lone Pine", "Lone Pine Capital"),
    (1135730, "Philippe Laffont", "Coatue"),
    (1103804, "Andreas Halvorsen", "Viking Global"),
    (1697748, "Cathie Wood", "ARK Invest"),
]
SUPER_KEY = "superinvestors:v1"
CUSIP_KEY = "cusip_map"
_building = threading.Lock()


def _filings(cik: int) -> list[tuple[str, str, str]]:
    r = _sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")["filings"]["recent"]
    return [(d, a, p) for f, d, a, p in zip(r["form"], r["filingDate"], r["accessionNumber"], r["reportDate"])
            if f == "13F-HR"][:2]


def _holdings(cik: int, accession: str) -> dict[str, dict]:
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
    items = _sec_get(f"{base}/index.json")["directory"]["item"]
    xml_name = next((i["name"] for i in items if i["name"].endswith(".xml") and i["name"] != "primary_doc.xml"), None)
    if not xml_name:
        return {}
    root = ET.fromstring(requests.get(f"{base}/{xml_name}", headers={"User-Agent": _ua()}, timeout=20).content)
    out: dict[str, dict] = {}
    for row in root.iter():
        if not row.tag.endswith("infoTable"):
            continue
        f = {c.tag.split("}")[-1]: c for c in row.iter()}
        if f.get("putCall") is not None:
            continue
        cusip = (f["cusip"].text or "").strip().upper()
        h = out.setdefault(cusip, {"cusip": cusip, "name": (f["nameOfIssuer"].text or "").strip().title(),
                                   "value": 0.0, "shares": 0.0})
        h["value"] += float(f["value"].text or 0)
        h["shares"] += float(f["sshPrnamt"].text or 0) if f.get("sshPrnamt") is not None else 0
    return out


def _ua() -> str:
    from config import SEC_USER_AGENT
    return SEC_USER_AGENT


def _map_cusips(cusips: set[str]) -> dict[str, str | None]:
    cached = (kv_get(CUSIP_KEY) or {}).get("data") or {}
    todo = [c for c in cusips if c not in cached][:250]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]
        try:
            resp = requests.post("https://api.openfigi.com/v3/mapping", timeout=15,
                                 json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk])
            if resp.status_code == 429:
                break
            for c, res in zip(chunk, resp.json()):
                data = res.get("data") or []
                cached[c] = data[0].get("ticker", "").replace("/", "-") or None if data else None
        except Exception as e:
            log.info("OpenFIGI failed: %s", e)
            break
        time.sleep(2.6)  # free tier: 25 requests/minute
    kv_set(CUSIP_KEY, cached)
    return cached


def _build() -> dict:
    funds, all_cusips = [], set()
    cutoff = (date.today() - timedelta(days=200)).isoformat()
    for cik, manager, firm in FUNDS:
        try:
            filings = _filings(cik)
            if not filings or filings[0][0] < cutoff:
                continue
            cur = _holdings(cik, filings[0][1])
            prev = _holdings(cik, filings[1][1]) if len(filings) > 1 else {}
        except Exception as e:
            log.info("13F failed for %s: %s", firm, e)
            continue
        total = sum(h["value"] for h in cur.values()) or 1
        changes = []
        for c, h in cur.items():
            p = prev.get(c)
            if not p:
                changes.append({**h, "action": "new", "pct_change": None})
            elif p["shares"] and abs(h["shares"] / p["shares"] - 1) >= 0.1:
                changes.append({**h, "action": "added" if h["shares"] > p["shares"] else "reduced",
                                "pct_change": round((h["shares"] / p["shares"] - 1) * 100, 1)})
        for c, p in prev.items():
            if c not in cur:
                changes.append({**p, "action": "sold", "pct_change": -100.0})
        changes.sort(key=lambda x: x["value"], reverse=True)
        top = sorted(cur.values(), key=lambda h: h["value"], reverse=True)[:15]
        for h in top:
            h["weight"] = round(h["value"] / total * 100, 1)
        for h in changes:
            h["weight"] = round(h["value"] / total * 100, 2) if h["action"] != "sold" else None
        changes = changes[:25]
        all_cusips |= {h["cusip"] for h in top + changes}
        funds.append({"cik": cik, "manager": manager, "firm": firm, "filed": filings[0][0],
                      "period": filings[0][2], "total_value": round(total), "positions": len(cur),
                      "top": top, "changes": changes})
        time.sleep(0.2)
    tickers = _map_cusips(all_cusips)
    for f in funds:
        for h in f["top"] + f["changes"]:
            h["ticker"] = tickers.get(h["cusip"])
    by_ticker = defaultdict(list)
    for f in funds:
        for h in f["top"]:
            if h.get("ticker"):
                by_ticker[h["ticker"]].append(f["manager"])
    consensus = sorted(({"ticker": t, "holders": m} for t, m in by_ticker.items() if len(m) >= 2),
                       key=lambda x: len(x["holders"]), reverse=True)[:15]
    return {"funds": funds, "consensus": consensus, "updated_at": datetime.now(timezone.utc).isoformat()}


def _safe_build():
    if not _building.acquire(blocking=False):
        return
    try:
        kv_set(SUPER_KEY, _build())
    except Exception as e:
        log.warning("Superinvestor build failed: %s", e)
    finally:
        _building.release()


def superinvestors() -> dict:
    cached = kv_get(SUPER_KEY)
    age = None
    if cached:
        ts = datetime.fromisoformat(cached["data"]["updated_at"])
        age = (datetime.now(timezone.utc) - ts).total_seconds()
    if (not cached or age > 86400) and not _building.locked():
        threading.Thread(target=_safe_build, daemon=True).start()
    if not cached:
        return {"status": "building", "funds": [], "consensus": []}
    return {**cached["data"], "status": "ready"}


def held_by_superinvestors(ticker: str) -> list[dict]:
    data = superinvestors()  # also starts the daily background refresh
    out = []
    for f in data.get("funds", []):
        for h in f["top"] + f["changes"]:
            if h.get("ticker") == ticker:
                out.append({"manager": f["manager"], "firm": f["firm"], "weight": h.get("weight"),
                            "action": h.get("action"), "period": f["period"]})
                break
    return out
