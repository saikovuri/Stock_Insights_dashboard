import { useEffect, useState } from 'react';
import { fetchMyStock } from '../api/stockApi';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const tone = v => v > 0 ? 'positive' : v < 0 ? 'negative' : '';

/** "Your <ticker>" card: what the signed-in user holds and has done in this stock. Reports chart levels upward. */
export default function MyStock({ ticker, price, onLevels }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let active = true;
    setData(null);
    onLevels?.([]);
    fetchMyStock(ticker).then(d => { if (!active) return; setData(d); onLevels?.(d.levels || []); }).catch(() => {});
    return () => { active = false; };
  }, [ticker]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!data || data.empty) return null;
  const value = data.shares && price ? data.shares * price : null;
  const unrealized = value != null && data.avg_cost != null ? value - data.shares * data.avg_cost : null;
  const results = [['Stock trades', data.closed_stock], ['Option trades', data.closed_options]].filter(([, s]) => s.count);
  return <div className="card my-stock" aria-label={`Your ${ticker}`}>
    <h3>Your {ticker}</h3>
    <div className="doctor-stats">
      {data.shares > 0 && <>
        <div><span>Shares</span><strong>{data.shares.toLocaleString()}</strong></div>
        <div><span>Average cost</span><strong>{usd(data.avg_cost)}</strong></div>
        {unrealized != null && <div><span>Unrealized</span><strong className={tone(unrealized)}>{usd(unrealized)}
          {' '}<small>({(unrealized / (data.shares * data.avg_cost) * 100).toFixed(1)}%)</small></strong></div>}
        {data.first_bought && <div><span>First bought</span><strong>{data.first_bought}</strong></div>}
      </>}
      {results.map(([label, s]) => <div key={label}><span>{label} closed</span>
        <strong className={tone(s.pnl)}>{usd(s.pnl)} <small>· {s.count} · {s.win_rate}% wins</small></strong></div>)}
    </div>
    {data.accounts.length > 1 && <p className="market-sub">{data.accounts.map(a => `${a.account}: ${a.shares} sh @ ${usd(a.avg_cost)}`).join(' · ')}</p>}
    {data.options.length > 0 && <ul className="idea-checks my-stock-options">{data.options.map(o => <li key={o.id}>
      {o.position} {o.contracts} × ${o.strike} {o.type} {o.expiry} @ ${Number(o.premium).toFixed(2)}
      {o.account !== 'Default' && <span className="account-badge">{o.account}</span>}</li>)}</ul>}
    <p className="market-sub">Realized results are gross of fees. Your cost, option strikes and price alerts are drawn on the chart below (toggle &quot;My levels&quot;).</p>
  </div>;
}
