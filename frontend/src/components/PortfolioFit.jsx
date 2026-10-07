import { useEffect, useState } from 'react';
import { useAuth } from '../AuthContext';
import { fetchPortfolioFit } from '../api/stockApi';

const CLS = { 'Good fit': 'positive', 'OK fit': 'rvol-warm', 'Poor fit': 'negative' };
const TONE = { good: 'positive', bad: 'negative', warn: 'rvol-warm', info: 'market-sub' };

/** Fit scores keyed by ticker for signed-in users; items are [{ ticker, cash_needed }]. */
export function usePortfolioFit(items) {
  const { user } = useAuth();
  const [fits, setFits] = useState({});
  const key = JSON.stringify(items);
  useEffect(() => {
    let active = true;
    const list = JSON.parse(key);
    if (!user || !list.length) { setFits({}); return undefined; }
    fetchPortfolioFit(list).then(data => {
      if (active) setFits(data.empty ? {} : Object.fromEntries(data.items.map(item => [item.ticker, item])));
    }).catch(() => { if (active) setFits({}); });
    return () => { active = false; };
  }, [key, user]);
  return fits;
}

export function FitBadge({ fit, detailed = false }) {
  if (!fit) return null;
  const summary = fit.reasons.map(r => r.text).join(' · ');
  return <span className="fit-badge-wrap">
    <span className={`fit-badge ${CLS[fit.label] || ''}`} title={summary} aria-label={`${fit.label}, score ${fit.score}: ${summary}`}>
      {fit.label} {fit.score}
    </span>
    {detailed && <ul className="fit-reasons">{fit.reasons.map(r => <li key={r.text} className={TONE[r.tone]}>{r.text}</li>)}</ul>}
  </span>;
}
