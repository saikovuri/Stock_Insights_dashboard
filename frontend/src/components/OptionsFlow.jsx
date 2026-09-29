import { useState, useEffect } from 'react';
import { fetchOptionsFlow } from '../api/stockApi';

const money = v => v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(0)}K` : `$${v}`;
const num = v => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : `${v}`;

export function FlowTable({ trades, showTicker, onSelect }) {
  if (!trades?.length) return <p className="empty-state" style={{ padding: 0 }}>No unusual contracts right now.</p>;
  return (
    <div className="financials-table-wrap">
      <table className="analyst-table flow-table">
        <thead>
          <tr>
            {showTicker && <th>Ticker</th>}
            <th>Contract</th><th>Expiry</th><th>Volume / OI</th><th>Premium</th><th>IV</th><th>Side</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i}>
              {showTicker && <td><button className="link-btn" onClick={() => onSelect?.(t.ticker)}><strong>{t.ticker}</strong></button></td>}
              <td className={t.kind === 'call' ? 'positive' : 'negative'}>
                ${t.strike} {t.kind.toUpperCase()} <span className="market-sub">({t.otm_pct === 0 ? 'ATM' : t.otm_pct > 0 ? `${t.otm_pct}% OTM` : `${Math.abs(t.otm_pct)}% ITM`})</span>
              </td>
              <td>{t.expiry} <span className="market-sub">{t.dte}d</span></td>
              <td>{num(t.volume)} / {num(t.open_interest)}{t.vol_oi ? <span className="market-sub"> ({t.vol_oi}×)</span> : null}</td>
              <td><strong>{money(t.premium)}</strong></td>
              <td>{t.iv_pct ? `${t.iv_pct}%` : '—'}</td>
              <td title="Last trade vs bid/ask: at the ask suggests a buyer, at the bid a seller">
                {t.side === 'bought' ? '🟢 at ask' : t.side === 'sold' ? '🔴 at bid' : '⚪ mid'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function OptionsFlow({ ticker }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null); setError(null);
    fetchOptionsFlow(ticker).then(setData).catch(e => setError(e.message));
  }, [ticker]);

  if (error) return <div className="card"><h3>🌊 Flow & positioning</h3><p className="empty-state" style={{ padding: 0 }}>{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading options flow…</p></div>;

  const pcCls = data.pc_volume > 1 ? 'negative' : data.pc_volume < 0.6 ? 'positive' : '';
  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🌊 Flow & positioning</h3>
        <span className="market-sub">Spot ${data.spot}</span>
      </div>
      {data.summary && <p className="ivrank-verdict-desc">{data.summary}</p>}
      <div className="doctor-stats">
        <div><span>Put/call volume</span><strong className={pcCls}>{data.pc_volume ?? '—'}</strong></div>
        <div><span>Put/call open interest</span><strong>{data.pc_oi ?? '—'}</strong></div>
        <div><span>Call wall (resistance)</span><strong>{data.call_wall ? `$${data.call_wall}` : '—'}</strong></div>
        <div><span>Put wall (support)</span><strong>{data.put_wall ? `$${data.put_wall}` : '—'}</strong></div>
        <div>
          <span>Gamma flip</span>
          <strong title="Above this price dealers dampen moves; below it they tend to amplify them">
            {data.gamma_flip ? `$${data.gamma_flip}` : '—'}
          </strong>
        </div>
        <div>
          <span>Dealer gamma</span>
          <strong className={data.gamma_regime === 'positive' ? 'positive' : data.gamma_regime === 'negative' ? 'negative' : ''}>
            {data.gamma_regime ? `${data.gamma_regime} (${money(Math.abs(data.net_gex))}/1%)` : '—'}
          </strong>
        </div>
        {data.max_pain.map(p => (
          <div key={p.expiry}>
            <span>Max pain {p.expiry} ({p.dte}d)</span>
            <strong>${p.max_pain} <span className="market-sub">{p.vs_spot_pct > 0 ? '+' : ''}{p.vs_spot_pct}%</span></strong>
          </div>
        ))}
      </div>
      <h4 className="sub-chart-title">Unusual activity (volume above open interest, ≥ $25K premium)</h4>
      <FlowTable trades={data.unusual} />
      <p className="ivrank-note">
        Call/put walls are the strikes with the most open interest within ±20% of spot. Max pain is the price where
        option holders lose the most at expiry. {data.note}
      </p>
    </div>
  );
}
