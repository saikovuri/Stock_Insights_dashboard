import { useState, useEffect, useMemo } from 'react';
import { fetchInPlay } from '../api/stockApi';

const vol = v => v == null ? '—' : v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : `${(v / 1e3).toFixed(0)}K`;
const cap = v => v == null ? '—' : v >= 1e12 ? `$${(v / 1e12).toFixed(1)}T` : v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : `$${(v / 1e6).toFixed(0)}M`;
const pct = v => v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`;
const cls = v => v == null ? '' : v >= 0 ? 'positive' : 'negative';

const FILTERS = {
  all: { label: 'All', test: () => true },
  small: { label: 'Small caps (< $2B)', test: r => (r.market_cap || 0) < 2e9 },
  large: { label: 'Mid & large caps', test: r => (r.market_cap || 0) >= 2e9 },
  catalyst: { label: 'With catalyst', test: r => !!r.catalyst },
};

export default function InPlay({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState('all');
  const [side, setSide] = useState('both');
  const [minPrice, setMinPrice] = useState(2);

  useEffect(() => {
    const load = () => fetchInPlay().then(d => { setData(d); setError(null); }).catch(e => setError(e.message));
    load();
    const timer = setInterval(load, 180_000);
    return () => clearInterval(timer);
  }, []);

  const rows = useMemo(() => (data?.rows || [])
    .filter(FILTERS[filter].test)
    .filter(r => side === 'both' || (side === 'up' ? r.change_pct > 0 : r.change_pct < 0))
    .filter(r => r.price >= minPrice), [data, filter, side, minPrice]);

  if (error && !data) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Screening the market for stocks in play…</p></div>;

  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>⚡ Stocks in play</h3>
        <span className="market-sub">
          {data.market_state === 'open' ? `Market open · ${data.session_elapsed_pct}% of session` : data.market_state}
          {' · '}{data.screened} screened · refreshes every 3 min · {new Date(data.as_of).toLocaleTimeString()}
        </span>
      </div>
      <p className="structures-intro">
        Movers with unusual volume, gaps or a news catalyst — the names day traders focus on. <b>Rel vol</b> compares
        today's volume with the 10-day average for the same point in the session (3× = three times normal).
        {data.market_state === 'pre-market' && ' Premarket % is shown before the open.'}
      </p>
      <div className="scanner-filters">
        <div className="chart-toggle">
          {Object.entries(FILTERS).map(([k, f]) => (
            <button key={k} className={filter === k ? 'active' : ''} onClick={() => setFilter(k)}>{f.label}</button>
          ))}
        </div>
        <div className="chart-toggle">
          {[['both', 'Both'], ['up', '▲ Up'], ['down', '▼ Down']].map(([k, l]) => (
            <button key={k} className={side === k ? 'active' : ''} onClick={() => setSide(k)}>{l}</button>
          ))}
        </div>
        <label className="market-sub">
          Min price ${minPrice}
          <input type="range" min={1} max={50} step={1} value={minPrice} onChange={e => setMinPrice(Number(e.target.value))} />
        </label>
      </div>
      <div className="table-scroll">
        <table className="market-table inplay-table">
          <thead>
            <tr>
              <th>Stock</th><th>Price</th><th>Change</th><th title="Open vs previous close">Gap</th>
              <th>Pre / Post</th><th title="Time-of-day adjusted relative volume">Rel vol</th><th>Volume</th>
              <th>Mkt cap</th><th title="FINRA short interest as % of shares outstanding">Short %</th><th>Catalyst</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.symbol} onClick={() => onSelect(r.symbol)}>
                <td><strong>{r.symbol}</strong><div className="market-sub inplay-name">{r.name}</div></td>
                <td>${r.price}</td>
                <td className={cls(r.change_pct)}><strong>{pct(r.change_pct)}</strong></td>
                <td className={cls(r.gap_pct)}>{pct(r.gap_pct)}</td>
                <td className="market-sub">
                  {r.premarket_pct != null && <span className={cls(r.premarket_pct)}>PM {pct(r.premarket_pct)} </span>}
                  {r.postmarket_pct != null && <span className={cls(r.postmarket_pct)}>AH {pct(r.postmarket_pct)}</span>}
                  {r.premarket_pct == null && r.postmarket_pct == null && '—'}
                </td>
                <td className={r.rvol >= 3 ? 'positive' : ''}><strong>{r.rvol}×</strong></td>
                <td>{vol(r.volume)}</td>
                <td>{cap(r.market_cap)}</td>
                <td className={r.short_pct >= 15 ? 'negative' : ''}>
                  {r.short_pct != null ? `${r.short_pct}%` : '—'}
                  {r.days_to_cover >= 5 && <span className="market-sub"> ({r.days_to_cover}d)</span>}
                </td>
                <td className="inplay-catalyst" onClick={e => e.stopPropagation()}>
                  {r.catalyst ? (
                    r.catalyst.url
                      ? <a href={r.catalyst.url} target="_blank" rel="noopener noreferrer" title={r.catalyst.headline}>
                          {r.catalyst.kind === 'earnings' ? '📊 ' : '📰 '}{r.catalyst.headline}
                        </a>
                      : <span>{r.catalyst.kind === 'earnings' ? '📊 ' : '📰 '}{r.catalyst.headline}</span>
                  ) : <span className="market-sub">No news found</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <p className="empty-state">Nothing matches these filters right now.</p>}
      <p className="ivrank-note">
        Tip: plan trades around key levels (previous-day high/low, premarket high/low, opening range, VWAP) on the
        5-minute chart — open a stock and switch the chart interval to 5m. Short % uses shares outstanding, not float.
      </p>
    </div>
  );
}
