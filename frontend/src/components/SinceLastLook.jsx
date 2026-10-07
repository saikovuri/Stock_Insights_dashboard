import { useEffect, useState } from 'react';

const KEY = 'stockpilot_last_look_v1';
const MIN_GAP_MS = 60 * 60 * 1000;
const MAX_TICKERS = 200;

const load = () => { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; } };
const ago = ms => {
  const hours = Math.round(ms / 3600000);
  return hours < 48 ? `${hours} hour${hours === 1 ? '' : 's'}` : `${Math.round(hours / 24)} days`;
};

/** Compare today's view of a stock with the snapshot from the last visit (this browser, at least an hour ago). */
export function lastLookChanges(previous, current) {
  if (!previous) return null;
  const seen = new Set(previous.headlines || []);
  const fresh = current.articles.filter(a => a.url && !seen.has(a.url));
  const out = {
    since: previous.at,
    priceChangePct: previous.price && current.price ? (current.price - previous.price) / previous.price * 100 : null,
    previousPrice: previous.price,
    headlines: fresh.slice(0, 3).map(a => ({ title: a.title, url: a.url })),
    headlineCount: fresh.length,
    earningsMoved: previous.earnings && current.earnings && previous.earnings !== current.earnings
      ? { from: previous.earnings, to: current.earnings } : null,
    reported: previous.earnings && current.lastEarnings && current.lastEarnings >= previous.earnings ? current.lastEarnings : null,
  };
  out.any = out.headlineCount > 0 || out.earningsMoved || out.reported || (out.priceChangePct != null && Math.abs(out.priceChangePct) >= 0.1);
  return out;
}

export default function SinceLastLook({ ticker, price, articles = [], earningsDate, lastEarnings }) {
  const [changes, setChanges] = useState(null);
  useEffect(() => {
    if (!ticker || !price) return;
    const store = load();
    const previous = store[ticker];
    const now = Date.now();
    if (previous && now - previous.at < MIN_GAP_MS) { setChanges(null); return; }
    const current = { price, articles, earnings: earningsDate, lastEarnings };
    setChanges(lastLookChanges(previous, current));
    store[ticker] = { at: now, price, earnings: earningsDate || null, headlines: articles.map(a => a.url).filter(Boolean).slice(0, 40) };
    const kept = Object.entries(store).sort((a, b) => b[1].at - a[1].at).slice(0, MAX_TICKERS);
    localStorage.setItem(KEY, JSON.stringify(Object.fromEntries(kept)));
  }, [ticker, price, articles, earningsDate, lastEarnings]);
  if (!changes?.any) return null;
  const pct = changes.priceChangePct;
  return <div className="card since-last-look" aria-label="Since your last look">
    <h3>🕒 Since your last look <span className="market-sub">({ago(Date.now() - changes.since)} ago)</span></h3>
    <ul className="idea-checks">
      {pct != null && <li>Price <span className={pct >= 0 ? 'positive' : 'negative'}>{pct >= 0 ? '+' : ''}{pct.toFixed(1)}%</span>
        {' '}(${changes.previousPrice} → ${price})</li>}
      {changes.reported && <li className="rvol-warm">Reported earnings on {changes.reported}</li>}
      {changes.earningsMoved && <li className="rvol-warm">Next earnings date moved: {changes.earningsMoved.from} → {changes.earningsMoved.to}</li>}
      {changes.headlineCount > 0 && <li>{changes.headlineCount} new headline{changes.headlineCount === 1 ? '' : 's'}:
        <ul>{changes.headlines.map(h => <li key={h.url}><a href={h.url} target="_blank" rel="noopener noreferrer">{h.title}</a></li>)}</ul></li>}
    </ul>
    <p className="market-sub">Compared with your last visit in this browser at least an hour ago.</p>
  </div>;
}
