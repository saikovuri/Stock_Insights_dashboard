import argparse
import json
import math
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description="Read-only StockPilot health/provider smoke check; never places or edits trades")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--authenticated", action="store_true")
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("Use a base URL without credentials, query or fragment")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}):
        parser.error("Remote smoke checks require HTTPS")
    headers = {"Accept": "application/json"}
    if args.authenticated:
        token = os.environ.get("STOCKPILOT_SMOKE_TOKEN")
        if not token:
            parser.error("Set STOCKPILOT_SMOKE_TOKEN locally; do not paste tokens into chat")
        headers["Authorization"] = "Bearer " + token
    paths = ["/api/health", "/api/stock/AAPL/metrics"]
    if args.authenticated:
        paths += ["/api/auth/me", "/api/accounting/report"]
    failed = False
    for path in paths:
        try:
            with urlopen(Request(args.base_url.rstrip("/") + path, headers=headers), timeout=60) as response:
                data = json.load(response)
            if path == "/api/health" and data.get("db") != "connected":
                raise ValueError("Database is not healthy")
            if path.endswith("/metrics"):
                price = data.get("price")
                if not isinstance(price, (float, int)) or not math.isfinite(price) or price <= 0:
                    raise ValueError("A valid provider price is unavailable")
            if path.endswith("/report") and not {"twr", "tax_lots", "manual_entries"}.issubset(data):
                raise ValueError("Accounting schema is missing")
            print(f"PASS {path}")
        except Exception as error:
            print(f"FAIL {path}: {type(error).__name__}")
            failed = True
    if failed:
        raise SystemExit(1)
    print("Read-only smoke checks passed. Quote timeliness, actual fills, push delivery and physical devices still require verification.")


if __name__ == "__main__":
    main()