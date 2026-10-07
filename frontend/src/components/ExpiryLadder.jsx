import { useEffect, useState } from 'react';
import { fetchExpiryLadder } from '../api/stockApi';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const fmtDate = d => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

function LotPlan({ row }) {
  const fifo = row.oldest_first, smart = row.highest_cost_first;
  const split = plan => `${usd(plan.gain)} (short-term ${usd(plan.short_term_gain)}, long-term ${usd(plan.long_term_gain)})`;
  return <details className="ladder-lots">
    <summary>If assigned: {row.shares_if_assigned} shares for {usd(row.proceeds_if_assigned)} · realizes {usd(fifo.gain)}
      {row.gain_difference > 0 && <strong className="positive"> · {usd(row.gain_difference)} less gain with highest-cost lots</strong>}</summary>
    <p>Oldest lots first (a common broker default): {split(fifo)}.</p>
    <p>Highest-cost lots first: {split(smart)}.</p>
    {smart.lots.length > 0 && <ul>{smart.lots.map(lot => <li key={lot.lot_id}>{lot.shares} sh bought {lot.acquired || 'unknown date'} at ${lot.basis}
      {' '}→ {usd(lot.gain)} {lot.long_term ? 'long-term' : 'short-term'}</li>)}</ul>}
    {fifo.uncovered_shares > 0 && <p className="negative">{fifo.uncovered_shares} shares are not recorded in this account: assignment would create a short stock position.</p>}
    <p className="market-sub">Brokers deliver lots using the account&apos;s cost-basis method in force at assignment. Set it (for example to highest cost or a tax-optimized method) beforehand if you want this choice; it usually can&apos;t be changed afterwards. Not tax advice.</p>
  </details>;
}

export default function ExpiryLadder({ version }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let active = true;
    setData(null); setError(null);
    fetchExpiryLadder().then(d => { if (active) setData(d); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [version]);
  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <p className="loading-text">Building the expiration ladder…</p>;
  if (!data.expiries.length) return <p className="empty-state">No open option positions.</p>;
  return <>
    <p className="structures-intro">Every upcoming expiry with what assignment would do to cash and shares. {data.note}</p>
    <div className="expiry-ladder">
      {data.expiries.map(group => <div key={group.expiry} className="desk-item">
        <div className="desk-head"><strong>{fmtDate(group.expiry)}</strong>
          <span className="market-sub">({group.dte}d) · {group.contracts} contract{group.contracts === 1 ? '' : 's'}</span>
          {group.cash_if_itm_puts_assigned > 0 && <span className="negative"> · in-the-money puts need {usd(group.cash_if_itm_puts_assigned)}</span>}
          {group.shares_if_itm_calls_assigned > 0 && <span className="negative"> · in-the-money calls deliver {group.shares_if_itm_calls_assigned} sh ({usd(group.gain_if_itm_calls_assigned)} gain)</span>}
          {group.cash_if_all_puts_assigned > 0 && group.cash_if_itm_puts_assigned === 0 && <span className="market-sub"> · puts reserve {usd(group.cash_if_all_puts_assigned)}</span>}
        </div>
        <ul className="idea-checks">{group.positions.map(row => <li key={row.id}>
          <strong>{row.ticker}</strong> {row.position} ${row.strike} {row.type} × {row.contracts}
          {row.account !== 'Default' && <span className="account-badge">{row.account}</span>}{' '}
          {row.itm == null ? <span className="market-sub">no quote</span>
            : <span className={row.position === 'short' ? (row.itm ? 'negative' : 'positive') : row.itm ? 'positive' : 'market-sub'}>
              {row.itm ? 'in the money' : 'out of the money'}</span>}
          {row.distance_pct != null && <span className="market-sub"> · strike {row.distance_pct > 0 ? '+' : ''}{row.distance_pct}% vs ${row.spot}</span>}
          {row.chance_itm_pct != null && <span className="market-sub"> · ~{row.chance_itm_pct}% chance ITM</span>}
          {row.cash_if_assigned != null && <span className="market-sub"> · {usd(row.cash_if_assigned)} if assigned
            {data.free_cash[row.account] != null && ` (free cash ${usd(data.free_cash[row.account])})`}</span>}
          {row.intrinsic_now != null && <span className="market-sub"> · worth {usd(row.intrinsic_now)} at expiry at today&apos;s price</span>}
          {row.oldest_first && <LotPlan row={row} />}
        </li>)}</ul>
      </div>)}
    </div>
  </>;
}
