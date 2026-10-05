"""Strategy tester: popular TradingView-style indicators backtested on one ticker and timeframe.
Signals use the bar close and fill at the next bar's open; intraday positions are flat by the close."""

import numpy as np
import pandas as pd

from cache import get_or_fetch
from stock_data import get_stock_data

# timeframe -> (yfinance interval, period, intraday, minutes per bar)
TIMEFRAMES = {
    "1m": ("1m", "7d", True, 1), "3m": ("1m", "7d", True, 3), "5m": ("5m", "60d", True, 5),
    "15m": ("15m", "60d", True, 15), "1h": ("1h", "1y", False, 60), "1d": ("1d", "5y", False, 390),
}

STRATEGIES = {
    "ema_cross": {"label": "EMA cross", "params": {"fast": 9, "slow": 21, "vwap_filter": 0},
                  "help": "Long when the fast EMA crosses above the slow EMA, short on the opposite cross. "
                          "VWAP filter only takes longs above VWAP and shorts below it (intraday)."},
    "bbawe": {"label": "Bollinger Awesome (BBAWE)", "params": {"bb_len": 20, "fast": 3, "ao_fast": 5, "ao_slow": 34},
              "help": "Fast EMA crosses the Bollinger basis with the Awesome Oscillator confirming direction."},
    "vwap_cross": {"label": "VWAP cross", "params": {},
                   "help": "Long when price closes back above VWAP, short when it closes below (intraday only)."},
    "macd": {"label": "MACD cross", "params": {"fast": 12, "slow": 26, "signal": 9},
             "help": "Long when the MACD histogram turns positive, short when it turns negative."},
    "supertrend": {"label": "Supertrend", "params": {"atr_len": 10, "mult": 3},
                   "help": "Long when Supertrend flips up, short when it flips down."},
    "rsi": {"label": "RSI mean reversion", "params": {"length": 14, "lower": 30, "upper": 70},
            "help": "Long when RSI crosses back above the lower band (exit at 50), short when it crosses back below the upper band."},
    "orb": {"label": "Opening range breakout", "params": {"minutes": 15},
            "help": "First close outside the opening range; stop at the other side of the range (intraday only)."},
}


def _load(ticker: str, tf: str) -> pd.DataFrame:
    interval, period, intraday, _ = TIMEFRAMES[tf]
    df = get_stock_data(ticker, period=period, interval=interval)[["Open", "High", "Low", "Close", "Volume"]].copy()
    if tf == "3m":
        df = df.resample("3min", label="left", closed="left").agg(
            {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}).dropna()
    df = df.dropna()
    df["day"] = df.index.date if intraday else np.arange(len(df))
    return df


def _xup(a, b):
    return (a > b) & (a.shift(1) <= b.shift(1))


def _rma(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def _vwap(df):
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    return (tp * df["Volume"]).groupby(df["day"]).cumsum() / df["Volume"].groupby(df["day"]).cumsum()


def _supertrend(df, n, mult):
    c, h, l = df["Close"], df["High"], df["Low"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = _rma(tr, n).values
    hl2 = ((h + l) / 2).values
    up, dn, cv = hl2 - mult * atr, hl2 + mult * atr, c.values
    fu, fd, trend = up.copy(), dn.copy(), np.ones(len(df))
    for i in range(1, len(df)):
        fu[i] = max(up[i], fu[i - 1]) if cv[i - 1] > fu[i - 1] else up[i]
        fd[i] = min(dn[i], fd[i - 1]) if cv[i - 1] < fd[i - 1] else dn[i]
        trend[i] = 1 if cv[i] > fd[i - 1] else -1 if cv[i] < fu[i - 1] else trend[i - 1]
    return pd.Series(trend, index=df.index)


def _signals(df, strategy, p, intraday):
    """Returns (long_entry, long_exit, short_entry, short_exit) boolean Series."""
    c = df["Close"]
    if strategy == "ema_cross":
        f = c.ewm(span=int(p["fast"]), adjust=False).mean()
        s = c.ewm(span=int(p["slow"]), adjust=False).mean()
        up, dn = _xup(f, s), _xup(s, f)
        if int(p.get("vwap_filter", 0)) and intraday:
            v = _vwap(df)
            return up & (c > v), dn | (c < v), dn & (c < v), up | (c > v)
        return up, dn, dn, up
    if strategy == "bbawe":
        basis = c.rolling(int(p["bb_len"])).mean()
        f = c.ewm(span=int(p["fast"]), adjust=False).mean()
        hl2 = (df["High"] + df["Low"]) / 2
        ao = hl2.rolling(int(p["ao_fast"])).mean() - hl2.rolling(int(p["ao_slow"])).mean()
        up, dn = _xup(f, basis), _xup(basis, f)
        return up & (ao > 0) & (ao.diff() > 0), dn, dn & (ao < 0) & (ao.diff() < 0), up
    if strategy == "vwap_cross":
        if not intraday:
            raise ValueError("VWAP cross needs an intraday timeframe")
        v = _vwap(df)
        newday = df["day"] != df["day"].shift(1)
        up, dn = _xup(c, v) & ~newday, _xup(v, c) & ~newday
        return up, dn, dn, up
    if strategy == "macd":
        m = c.ewm(span=int(p["fast"]), adjust=False).mean() - c.ewm(span=int(p["slow"]), adjust=False).mean()
        h = m - m.ewm(span=int(p["signal"]), adjust=False).mean()
        zero = h * 0
        return _xup(h, zero), _xup(zero, h), _xup(zero, h), _xup(h, zero)
    if strategy == "supertrend":
        t = _supertrend(df, int(p["atr_len"]), float(p["mult"]))
        up, dn = (t == 1) & (t.shift(1) == -1), (t == -1) & (t.shift(1) == 1)
        return up, dn, dn, up
    if strategy == "rsi":
        d = c.diff()
        n = int(p["length"])
        rsi = 100 - 100 / (1 + _rma(d.clip(lower=0), n) / _rma(-d.clip(upper=0), n))
        lo, hi = rsi * 0 + float(p["lower"]), rsi * 0 + float(p["upper"])
        return _xup(rsi, lo), rsi >= 50, _xup(hi, rsi), rsi <= 50
    raise ValueError("Unknown strategy")


def _simulate(df, sig, intraday, side, stop, target):
    le, lx, se, sx = (np.array(x.fillna(False).values, dtype=bool) for x in sig)
    if side == "long":
        se[:] = False
    elif side == "short":
        le[:] = False
    o, h, l, c = (df[k].values for k in ("Open", "High", "Low", "Close"))
    d, idx = df["day"].values, df.index
    trades, pos, entry, e_i = [], 0, 0.0, 0

    def close(i, price, why):
        nonlocal pos
        trades.append({"side": pos, "entry_time": idx[e_i], "exit_time": idx[i], "entry": entry, "exit": price,
                       "ret": pos * (price / entry - 1), "bars": i - e_i, "why": why})
        pos = 0

    for i in range(len(df)):
        if pos and i >= e_i:
            sp = entry * (1 - pos * stop) if stop else None
            tp = entry * (1 + pos * target) if target else None
            if sp and ((pos == 1 and l[i] <= sp) or (pos == -1 and h[i] >= sp)):
                close(i, min(sp, o[i]) if pos == 1 else max(sp, o[i]), "stop")
            elif tp and ((pos == 1 and h[i] >= tp) or (pos == -1 and l[i] <= tp)):
                close(i, max(tp, o[i]) if pos == 1 else min(tp, o[i]), "target")
        if i == len(df) - 1:
            if pos:
                close(i, c[i], "end")
            break
        same = d[i + 1] == d[i]
        if pos and intraday and not same:
            close(i, c[i], "close")
            continue
        if (pos == 1 and lx[i]) or (pos == -1 and sx[i]):
            close(i + 1, o[i + 1], "signal")
        if not pos and (same or not intraday):
            if le[i]:
                pos, entry, e_i = 1, o[i + 1], i + 1
            elif se[i]:
                pos, entry, e_i = -1, o[i + 1], i + 1
    return trades


def _orb(df, minutes, bar_min, side):
    n = max(1, int(minutes) // bar_min)
    trades = []
    for _, g in df.groupby("day"):
        if len(g) <= n + 1:
            continue
        hi, lo = g["High"].iloc[:n].max(), g["Low"].iloc[:n].min()
        o, h, l, c, idx = g["Open"].values, g["High"].values, g["Low"].values, g["Close"].values, g.index
        for i in range(n, len(g) - 1):
            s = 1 if c[i] > hi else -1 if c[i] < lo else 0
            if not s or (side == "long" and s == -1) or (side == "short" and s == 1):
                if s:
                    break
                continue
            entry, stop, exit_p, j_exit, why = o[i + 1], (lo if s == 1 else hi), None, len(g) - 1, "close"
            for j in range(i + 1, len(g)):
                if (s == 1 and l[j] <= stop) or (s == -1 and h[j] >= stop):
                    exit_p, j_exit, why = (min(stop, o[j]) if s == 1 else max(stop, o[j])), j, "stop"
                    break
            exit_p = exit_p if exit_p is not None else c[-1]
            trades.append({"side": s, "entry_time": idx[i + 1], "exit_time": idx[j_exit], "entry": entry,
                           "exit": exit_p, "ret": s * (exit_p / entry - 1), "bars": j_exit - i - 1, "why": why})
            break
    return trades


def _stats(trades, cost, sessions):
    if not trades:
        return {"trades": 0}
    r = np.array([t["ret"] for t in trades])
    net = r - cost
    wins, losses = net[net > 0], net[net < 0]
    eq = np.cumsum(net)
    dd = float((eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]).min())
    out = {
        "trades": len(r), "per_session": round(len(r) / max(sessions, 1), 2),
        "win_rate": round(float((net > 0).mean()) * 100, 1),
        "avg_net_pct": round(float(net.mean()) * 100, 3), "avg_gross_pct": round(float(r.mean()) * 100, 3),
        "total_net_pct": round(float(net.sum()) * 100, 2),
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if len(losses) else None,
        "avg_win_pct": round(float(wins.mean()) * 100, 3) if len(wins) else None,
        "avg_loss_pct": round(float(losses.mean()) * 100, 3) if len(losses) else None,
        "max_drawdown_pct": round(dd * 100, 2),
        "avg_bars": round(float(np.mean([t["bars"] for t in trades])), 1),
    }
    for s, name in ((1, "long"), (-1, "short")):
        sub = np.array([t["ret"] for t in trades if t["side"] == s]) - cost
        out[f"{name}_trades"] = len(sub)
        out[f"{name}_avg_net_pct"] = round(float(sub.mean()) * 100, 3) if len(sub) else None
    return out


def _params(strategy, overrides):
    p = dict(STRATEGIES[strategy]["params"])
    for k, v in (overrides or {}).items():
        if k in p and v is not None:
            p[k] = v
    for name, value in p.items():
        if not np.isfinite(value):
            raise ValueError(f"{name} must be finite")
        if name == "vwap_filter":
            if value not in (0, 1):
                raise ValueError("VWAP filter must be 0 or 1")
        elif name in ("lower", "upper"):
            if not 0 <= value <= 100:
                raise ValueError("RSI bands must be between 0 and 100")
        elif value <= 0 or value > 500 or (name != "mult" and int(value) != value):
            raise ValueError(f"{name} must be a positive {'number' if name == 'mult' else 'integer'} up to 500")
    if p.get("fast", 0) >= p.get("slow", 501) or p.get("ao_fast", 0) >= p.get("ao_slow", 501):
        raise ValueError("Fast period must be shorter than slow period")
    if p.get("lower", 0) >= p.get("upper", 100):
        raise ValueError("Lower band must be below upper band")
    return p


def _validation(df, strategy, params, intraday, bar_min, side, cost, stop, target):
    signals = None if strategy == "orb" else _signals(df, strategy, params, intraday)
    boundaries = [0]
    for fraction in (0.7, 0.8, 0.9):
        index = int(len(df) * fraction)
        if intraday:
            index = int(np.flatnonzero(df["day"].values == df["day"].iloc[index])[0])
        boundaries.append(index)
    boundaries.append(len(df))

    def evaluate(start, end):
        sample = df.iloc[start:end]
        if len(sample) < 2:
            return {"stats": {"trades": 0}, "from": None, "to": None}
        trades = (_orb(sample, params["minutes"], bar_min, side) if strategy == "orb" else
                  _simulate(sample, tuple(signal.iloc[start:end] for signal in signals), intraday, side, stop, target))
        sessions = sample["day"].nunique() if intraday else len(sample)
        return {"from": sample.index[0].isoformat(), "to": sample.index[-1].isoformat(),
                "stats": _stats(trades, cost, sessions), "double_cost_stats": _stats(trades, cost * 2, sessions)}

    return {"train": evaluate(0, boundaries[1]), "holdout": evaluate(boundaries[1], len(df)),
            "windows": [evaluate(start, end) for start, end in zip(boundaries[1:-1], boundaries[2:])],
            "note": "First 70% development window, final 30% chronological holdout with three sequential windows. "
                    "Parameters are fixed; indicators warm up using earlier observations only and positions reset at boundaries. "
                    "Retuning after seeing holdout results invalidates the holdout. Costs are round-trip bps including fees/slippage; "
                    "double-cost results are a sensitivity check. This is not a claim of a validated trading edge."}


def _walk_forward(df, strategy, params, intraday, bar_min, side, cost, stop, target):
    candidates = [params]
    parameter = next((name for name in ("fast", "length", "atr_len", "bb_len", "minutes") if name in params), None)
    if parameter:
        for scale in (0.75, 1.25):
            try:
                candidate = _params(strategy, {**params, parameter: max(1, round(params[parameter] * scale))})
            except ValueError:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
    boundaries = []
    for fraction in (0.5, 0.6, 0.7, 0.8, 0.9):
        boundary = int(len(df) * fraction)
        if intraday:
            boundary = int(np.flatnonzero(df["day"].values == df["day"].iloc[boundary])[0])
        boundaries.append(boundary)
    boundaries = sorted(set(boundaries + [len(df)]))
    folds, all_trades = [], []
    for start, end in zip(boundaries, boundaries[1:]):
        if start < 30 or end - start < 2:
            continue
        train, sample = df.iloc[:start], df.iloc[start:end]
        training_sessions = train["day"].nunique() if intraday else len(train)
        ranked = []
        for candidate in candidates:
            trades = (_orb(train, candidate["minutes"], bar_min, side) if strategy == "orb" else
                      _simulate(train, _signals(train, strategy, candidate, intraday), intraday, side, stop, target))
            stats = _stats(trades, cost, training_sessions)
            if stats["trades"] >= 5 and stats["total_net_pct"] > 0:
                ranked.append((stats["total_net_pct"], candidate, stats))
        fold = {"train_from": train.index[0].isoformat(), "train_to": train.index[-1].isoformat(),
                "from": sample.index[0].isoformat(), "to": sample.index[-1].isoformat(),
                "params": None, "training_stats": None, "stats": {"trades": 0}, "double_cost_stats": {"trades": 0}}
        if ranked:
            _, chosen, training_stats = max(ranked, key=lambda item: item[0])
            signals = None if strategy == "orb" else _signals(df.iloc[:end], strategy, chosen, intraday)
            trades = (_orb(sample, chosen["minutes"], bar_min, side) if strategy == "orb" else
                      _simulate(sample, tuple(signal.iloc[start:end] for signal in signals), intraday, side, stop, target))
            sessions = sample["day"].nunique() if intraday else len(sample)
            fold.update(params=chosen, training_stats=training_stats, stats=_stats(trades, cost, sessions),
                        double_cost_stats=_stats(trades, cost * 2, sessions))
            all_trades.extend(trades)
        folds.append(fold)
    test = df.iloc[boundaries[0]:]
    sessions = test["day"].nunique() if intraday else len(test)
    return {"windows": folds, "candidates": candidates, "stats": _stats(all_trades, cost, sessions),
            "double_cost_stats": _stats(all_trades, cost * 2, sessions),
            "note": "Expanding-window parameter selection: first 50% training, five subsequent 10% test windows. "
                    "The declared grid varies one lookback by +/-25%; each choice uses only preceding training data. "
                    "Selection maximizes training net return with at least five trades and positive net return; otherwise no trade. "
                    "Positions reset each window. Forward results include round-trip costs; double-cost results stress the assumptions. "
                    "This is single-ticker research, not a point-in-time universe test or evidence of future profitability."}


def run(ticker, tf, strategy, overrides=None, side="both", cost_bps=3.0, stop_pct=0.0, target_pct=0.0):
    if tf not in TIMEFRAMES:
        raise ValueError("Unsupported timeframe")
    if strategy not in STRATEGIES:
        raise ValueError("Unknown strategy")
    if side not in {"both", "long", "short"} or any(not np.isfinite(value) or value < 0 for value in (cost_bps, stop_pct, target_pct)):
        raise ValueError("Invalid side, costs, stop or target")
    intraday, bar_min = TIMEFRAMES[tf][2], TIMEFRAMES[tf][3]
    p = _params(strategy, overrides)
    key = f"bt:{ticker}:{tf}:{strategy}:{sorted(p.items())}:{side}:{cost_bps}:{stop_pct}:{target_pct}"

    def _fetch():
        df = _load(ticker, tf)
        if len(df) < 60:
            raise ValueError("Not enough price history for this timeframe")
        if strategy == "orb":
            if not intraday:
                raise ValueError("Opening range breakout needs an intraday timeframe")
            trades = _orb(df, p["minutes"], bar_min, side)
        else:
            trades = _simulate(df, _signals(df, strategy, p, intraday), intraday, side,
                               stop_pct / 100, target_pct / 100)
        cost = cost_bps / 1e4
        sessions = df["day"].nunique() if intraday else len(df)
        if intraday:
            days = [g for _, g in df.groupby("day")]
            base = [g["Close"].iloc[-1] / g["Open"].iloc[0] - 1 for g in days]
            baseline = {"label": "Buy the open, sell the close (every day)",
                        "avg_pct": round(float(np.mean(base)) * 100, 3),
                        "total_pct": round(float(np.sum(base)) * 100, 2)}
        else:
            baseline = {"label": "Buy and hold", "total_pct": round((df["Close"].iloc[-1] / df["Open"].iloc[0] - 1) * 100, 2)}
        eq = np.cumsum([t["ret"] - cost for t in trades]) * 100
        step = max(1, len(trades) // 300)
        fmt = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
        return {
            "ticker": ticker, "timeframe": tf, "strategy": strategy, "label": STRATEGIES[strategy]["label"],
            "params": p, "side": side, "cost_bps": cost_bps, "stop_pct": stop_pct, "target_pct": target_pct,
            "from": df.index[0].strftime(fmt), "to": df.index[-1].strftime(fmt), "sessions": int(sessions),
            "stats": _stats(trades, cost, sessions), "baseline": baseline,
            "validation": _validation(df, strategy, p, intraday, bar_min, side, cost, stop_pct / 100, target_pct / 100),
            "walk_forward": _walk_forward(df, strategy, p, intraday, bar_min, side, cost, stop_pct / 100, target_pct / 100),
            "equity": [{"t": trades[i]["exit_time"].strftime(fmt), "equity": round(float(eq[i]), 3)}
                       for i in range(0, len(trades), step)],
            "recent_trades": [{"side": "long" if t["side"] == 1 else "short",
                               "entry_time": t["entry_time"].strftime(fmt), "exit_time": t["exit_time"].strftime(fmt),
                               "entry": round(float(t["entry"]), 2), "exit": round(float(t["exit"]), 2),
                               "ret_pct": round((t["ret"] - cost) * 100, 2), "why": t["why"]}
                              for t in trades[-25:]][::-1],
        }
    return get_or_fetch("walk-forward-v1:" + key, _fetch, ttl=600)


def compare(ticker, tf, cost_bps=3.0):
    intraday = TIMEFRAMES[tf][2]
    rows = []
    for s in STRATEGIES:
        if not intraday and s in ("vwap_cross", "orb"):
            continue
        variants = [(s, {})] + ([("ema_cross", {"vwap_filter": 1})] if s == "ema_cross" and intraday else [])
        for name, ov in variants:
            try:
                r = run(ticker, tf, name, ov, cost_bps=cost_bps)
            except ValueError:
                continue
            label = r["label"] + (" + VWAP filter" if ov.get("vwap_filter") else "")
            rows.append({"strategy": name, "overrides": ov, "label": label, "params": r["params"], **r["stats"]})
    rows.sort(key=lambda x: x.get("avg_net_pct") if x.get("trades") else -99, reverse=True)
    base = run(ticker, tf, "ema_cross", cost_bps=cost_bps)
    return {"ticker": ticker, "timeframe": tf, "rows": rows, "baseline": base["baseline"],
            "from": base["from"], "to": base["to"], "sessions": base["sessions"], "cost_bps": cost_bps}
