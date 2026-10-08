import { useEffect, useState } from 'react';
import { fetchAccountValue } from '../api/stockApi';

const money = v => `$${Math.round(v).toLocaleString()}`;
let cache = null;

/** Recorded account value (stocks + entered cash) for the signed-in user; null for guests or on failure. */
export function useAccountValue() {
  const token = typeof localStorage === 'undefined' ? null : localStorage.getItem('token');
  const [value, setValue] = useState(null);
  useEffect(() => {
    if (!token) { setValue(null); return undefined; }
    let active = true;
    if (!cache || cache.token !== token || Date.now() - cache.at > 300_000) {
      cache = { token, at: Date.now(), promise: fetchAccountValue().catch(() => null) };
    }
    cache.promise.then(result => { if (active) setValue(result?.value > 0 ? result : null); });
    return () => { active = false; };
  }, [token]);
  return value;
}

/** "If assigned: 31% of your account" so size is judged by the stock you could end up owning, not the premium. */
export function AssignmentShare({ amount, account, label = 'If assigned' }) {
  if (!account?.value || !(amount > 0)) return null;
  const pct = amount / account.value * 100;
  const cls = pct > 25 ? 'negative' : pct > 10 ? 'rvol-warm' : 'positive';
  return (
    <p className={`assign-share ${cls}`} title="Recorded stock value plus entered cash across your accounts">
      {label}: <strong>{pct.toFixed(pct < 10 ? 1 : 0)}%</strong> of your account ({money(amount)} of {money(account.value)})
      {pct > 25 && ' — one stock would dominate the account'}
      {!account.cash_entered && ' · enter cash in Portfolio for a full picture'}
    </p>
  );
}

/** Limit-price steps: start at the mid and give up one tick at a time, never past the bid (sell) or ask (buy). */
export function limitLadder(bid, ask, side = 'sell') {
  if (!(bid > 0) || !(ask >= bid)) return null;
  const b = Math.round(bid * 100);
  const a = Math.round(ask * 100);
  const tick = (b + a) / 2 < 300 ? 1 : 5;
  const start = Math.min(a, Math.max(b, Math.round((b + a) / 2 / tick) * tick));
  const dir = side === 'sell' ? -1 : 1;
  const steps = [0, 1, 2].map(n => start + dir * n * tick).filter(v => v >= b && v <= a);
  return { steps: [...new Set(steps)].map(v => v / 100), floor: (side === 'sell' ? b : a) / 100, tick: tick / 100 };
}

export function LimitHint({ bid, ask, side = 'sell', what = 'premium' }) {
  const plan = limitLadder(bid, ask, side);
  if (!plan) return null;
  const [first, ...rest] = plan.steps.map(v => `$${v.toFixed(2)}`);
  return (
    <p className="limit-hint" title={`Steps of $${plan.tick.toFixed(2)}: many options trade in pennies under $3 and nickels above; some (e.g. SPY, QQQ) in pennies throughout.`}>
      🎯 Limit {side === 'sell' ? 'sell' : 'buy'}: start at <strong>{first}</strong> (mid)
      {rest.length > 0 && <>; if not filled in a few minutes, try {rest.join(', then ')}</>}.
      {' '}Don't {side === 'sell' ? `sell below the $${plan.floor.toFixed(2)} bid` : `pay above the $${plan.floor.toFixed(2)} ask`} — a market order gives up the spread on the {what}.
    </p>
  );
}

/** 1–3 trading days after a report: the gap is known and implied volatility is often still elevated. */
export function isPostEarnings(daysSince, timing) {
  if (daysSince == null) return false;
  return (daysSince >= 1 && daysSince <= 4) || (daysSince === 0 && timing === 'before open');
}

export function PostEarningsBadge({ daysSince, timing }) {
  if (!isPostEarnings(daysSince, timing)) return null;
  return (
    <span className="post-earnings-badge" title="The report and its gap are behind it, and option prices often stay elevated for a day or two: a common window to sell premium.">
      🟢 Post-earnings window
    </span>
  );
}
