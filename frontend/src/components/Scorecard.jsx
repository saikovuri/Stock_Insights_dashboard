import { useEffect, useState } from 'react';
import { fetchScorecard } from '../api/stockApi';
import Skeleton from './Skeleton';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : v > 0 ? '+' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const cls = v => (v > 0 ? 'positive' : v < 0 ? 'negative' : '');
const SCOPES = [['trading', 'Trading accounts'], ['long_term', 'Long-term accounts'], ['all', 'All accounts']];

function Rows({ rows, first, label }) {
  return <div className="table-scroll"><table className="market-table phone-cards" aria-label={label}>
    <thead><tr><th>{first}</th><th>Trades</th><th>Win rate</th><th>Your P&L</th><th>Same money in SPY</th><th>Difference</th></tr></thead>
    <tbody>{rows.map(r => <tr key={r.strategy || r.month}>
      <td><strong>{r.strategy || r.month}</strong>{r.avg_days != null && <div className="market-sub">held {r.avg_days}d on average</div>}</td>
      <td data-label="Trades">{r.trades}</td>
      <td data-label="Win rate">{r.win_rate}%</td>
      <td data-label="Your P&L" className={cls(r.net)}>{usd(r.net)}</td>
      <td data-label="In SPY" className={cls(r.spy)}>{usd(r.spy)}</td>
      <td data-label="Difference" className={cls(r.edge)}><strong>{usd(r.edge)}</strong></td>
    </tr>)}</tbody>
  </table></div>;
}

/** Closed trades against holding SPY with the same money for the same days. */
export default function Scorecard() {
  const [scope, setScope] = useState('trading');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    setData(null); setError(null);
    fetchScorecard(scope).then(value => { if (active) setData(value); }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [scope]);
  const t = data?.totals;
  return <section className="portfolio-section scorecard">
    <h3>Is my trading beating the index?</h3>
    <div className="trade-history-kinds" role="group" aria-label="Accounts">
      {SCOPES.map(([value, label]) => <button key={value} type="button" className={`watchlist-tab${scope === value ? ' active' : ''}`}
        aria-pressed={scope === value} onClick={() => setScope(value)}>{label}</button>)}
    </div>
    {error ? <p className="error-text">{error}</p> : !data ? <Skeleton label="Comparing with SPY" lines={2} /> : !t ? <p className="empty-state">{data.note}</p> : <>
      <p className={`scorecard-verdict ${cls(t.edge)}`}>{t.edge >= 0
        ? <>Your closed trades made <strong>{usd(t.edge)}</strong> more than the same money would have made in SPY over the same days.</>
        : <>The same money in SPY over the same days would have made <strong>{usd(-t.edge)}</strong> more than your closed trades.</>}</p>
      <div className="doctor-stats" aria-label="Scorecard totals">
        <div><span>Trades compared</span><strong>{t.trades}</strong></div>
        <div><span>Your P&L (after fees)</span><strong className={cls(t.net)}>{usd(t.net)}</strong></div>
        <div><span>Same money in SPY</span><strong className={cls(t.spy)}>{usd(t.spy)}</strong></div>
        <div><span>Difference</span><strong className={cls(t.edge)}>{usd(t.edge)}{t.edge_pct_of_capital != null && <small> ({t.edge_pct_of_capital}% of capital)</small>}</strong></div>
        <div><span>Win rate</span><strong>{t.win_rate}%</strong></div>
      </div>
      {t.trades < 20 && <p className="rvol-warm">Only {t.trades} trades: too few to tell skill from luck. Keep recording and check again.</p>}
      <h4>By strategy (worst first)</h4>
      <Rows rows={data.groups} first="Strategy" label="By strategy" />
      <h4>By month closed</h4>
      <Rows rows={[...data.months].reverse()} first="Month" label="By month" />
      {data.skipped > 0 && <p className="market-sub">{data.skipped} trade{data.skipped === 1 ? '' : 's'} skipped (no open date or no SPY price).</p>}
      <p className="ivrank-note">{data.note}</p>
    </>}
  </section>;
}
