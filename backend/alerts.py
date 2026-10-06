from config import DEFAULT_PRICE_CHANGE_ALERT, DEFAULT_VOLUME_SPIKE_ALERT


def check_alerts(metrics: dict, thresholds: dict | None = None) -> list[dict]:
    """Check stock metrics against alert thresholds. Returns triggered alerts."""
    if thresholds is None:
        thresholds = {}

    price_threshold = thresholds.get("price_change_pct", DEFAULT_PRICE_CHANGE_ALERT)
    volume_threshold = thresholds.get("volume_spike", DEFAULT_VOLUME_SPIKE_ALERT)

    alerts = []

    change_pct = abs(metrics.get("change_pct", 0))
    if change_pct >= price_threshold:
        direction = "up" if metrics["change_pct"] > 0 else "down"
        alerts.append({
            "type": "PRICE_CHANGE",
            "severity": "high" if change_pct >= price_threshold * 2 else "medium",
            "message": f"{metrics['name']} moved {direction} {change_pct:.1f}% today",
            "value": metrics["change_pct"],
        })

    volume = metrics.get("volume", 0)
    avg_volume = metrics.get("avg_volume", 0)
    if avg_volume and volume:
        vol_ratio = volume / avg_volume
        if vol_ratio >= volume_threshold:
            alerts.append({
                "type": "VOLUME_SPIKE",
                "severity": "high" if vol_ratio >= volume_threshold * 2 else "medium",
                "message": f"{metrics['name']} volume is {vol_ratio:.1f}x average ({volume:,} vs avg {avg_volume:,})",
                "value": round(vol_ratio, 2),
            })

    price = metrics.get("price", 0)
    high_52 = metrics.get("52w_high", 0)
    low_52 = metrics.get("52w_low", 0)

    if price and high_52:
        pct_from_high = (high_52 - price) / high_52 * 100
        if pct_from_high <= 2:
            alerts.append({
                "type": "NEAR_52W_HIGH",
                "severity": "info",
                "message": (f"{metrics['name']} is at a new 52-week high (${high_52:.2f})" if price >= high_52 else
                            f"{metrics['name']} is within {pct_from_high:.1f}% of its 52-week high (${high_52:.2f})"),
                "value": round(max(pct_from_high, 0), 2),
            })

    if price and low_52:
        pct_from_low = (price - low_52) / low_52 * 100
        if pct_from_low <= 5:
            alerts.append({
                "type": "NEAR_52W_LOW",
                "severity": "warning",
                "message": f"{metrics['name']} is within {pct_from_low:.1f}% of its 52-week low (${low_52:.2f})",
                "value": round(pct_from_low, 2),
            })

    return alerts


def _cross_date(fast, slow, lookback: int, direction: str):
    """Date of the most recent crossing of fast over (up) / under (down) slow within the last N bars."""
    diff = (fast - slow).dropna()
    if len(diff) < 2:
        return None
    above = diff > 0
    crossed = above != above.shift(1)
    crossed.iloc[0] = False
    hits = crossed & (above if direction == "up" else ~above)
    recent = hits.tail(lookback)
    return recent[recent].index[-1] if recent.any() else None


def technical_events(name: str, df) -> list[dict]:
    """Recent crossover events from daily bars with indicators (see stock_data.compute_indicators)."""
    import pandas as pd
    out = []

    def add(type_, severity, message, when):
        out.append({"type": type_, "severity": severity, "message": message,
                    "date": pd.Timestamp(when).strftime("%Y-%m-%d")})

    close = df["Close"]
    checks = [
        ("GOLDEN_CROSS", "info", df["sma_50"], df["sma_200"], 10, "up",
         "50-day average crossed above the 200-day (golden cross)"),
        ("DEATH_CROSS", "warning", df["sma_50"], df["sma_200"], 10, "down",
         "50-day average crossed below the 200-day (death cross)"),
        ("ABOVE_200D", "info", close, df["sma_200"], 3, "up", "price reclaimed its 200-day average"),
        ("BELOW_200D", "warning", close, df["sma_200"], 3, "down", "price fell below its 200-day average"),
        ("MACD_BULLISH", "info", df["macd"], df["macd_signal"], 2, "up", "MACD crossed above its signal line"),
        ("MACD_BEARISH", "medium", df["macd"], df["macd_signal"], 2, "down", "MACD crossed below its signal line"),
    ]
    for type_, sev, fast, slow, lookback, direction, text in checks:
        when = _cross_date(fast, slow, lookback, direction)
        if when is not None:
            add(type_, sev, f"{name}: {text} on {pd.Timestamp(when).strftime('%b %d')}", when)

    rsi = df["rsi"]
    for type_, sev, level, direction, text in [
        ("RSI_OVERBOUGHT", "medium", 70, "up", "RSI moved above 70 (overbought)"),
        ("RSI_OVERSOLD", "medium", 30, "down", "RSI dropped below 30 (oversold)"),
    ]:
        when = _cross_date(rsi, pd.Series(level, index=rsi.index), 3, direction)
        if when is not None:
            add(type_, sev, f"{name}: {text} — now {rsi.iloc[-1]:.0f}", when)
    return out
