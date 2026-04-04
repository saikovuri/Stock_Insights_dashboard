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
                "message": f"{metrics['name']} is within {pct_from_high:.1f}% of its 52-week high (${high_52:.2f})",
                "value": round(pct_from_high, 2),
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

    avg_50 = metrics.get("50d_avg", 0)
    avg_200 = metrics.get("200d_avg", 0)
    if price and avg_50 and avg_200:
        if avg_50 > avg_200 and price > avg_50:
            alerts.append({
                "type": "GOLDEN_CROSS",
                "severity": "info",
                "message": f"{metrics['name']}: 50-day avg (${avg_50:.2f}) > 200-day avg (${avg_200:.2f}) — bullish signal",
                "value": round(avg_50 - avg_200, 2),
            })
        elif avg_50 < avg_200 and price < avg_50:
            alerts.append({
                "type": "DEATH_CROSS",
                "severity": "warning",
                "message": f"{metrics['name']}: 50-day avg (${avg_50:.2f}) < 200-day avg (${avg_200:.2f}) — bearish signal",
                "value": round(avg_200 - avg_50, 2),
            })

    return alerts
