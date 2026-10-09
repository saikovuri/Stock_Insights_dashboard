import { useState, useEffect } from 'react';
import { fetchOptionsFlow } from '../api/stockApi';
import Tip from './Tip';
import ClampText from './ClampText';

const money = v => v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `$${(v / 1e3).toFixed(0)}K` : `$${v}`;
const num = v => v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : `${v}`;

export function FlowTable({ trades, showTicker, onSelect }) {
  const [all, setAll] = useState(false);
  if (!trades?.length) return <p className="empty-state" style={{ padding: 0 }}>No unusual contracts right now.</p>;
  return (
    <div className="financials-table-wrap">
      <table className={`analyst-table flow-table ${all ? '' : 'flow-collapsed'}`}>
        <thead>
          <tr>
            {showTicker && <th>Ticker</th>}
            <th>Contract</th><th>Expiry</th><th>Volume / OI <Tip term="open_interest" /></th><th>Estimated notional</th><th>IV <Tip term="iv" /></th><th>Last vs quote</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i}>
              {showTicker && <td className="flow-cell-wide"><button className="link-btn" onClick={() => onSelect?.(t.ticker)}><strong>{t.ticker}</strong></button></td>}
              <td className={`flow-cell-wide ${t.kind === 'call' ? 'positive' : 'negative'}`}>
                ${t.strike} {t.kind.toUpperCase()} <span className="market-sub">({t.otm_pct === 0 ? 'ATM' : t.otm_pct > 0 ? `${t.otm_pct}% OTM` : `${Math.abs(t.otm_pct)}% ITM`})</span>
              </td>
              <td data-label="Expiry">{t.expiry} <span className="market-sub">{t.dte}d</span></td>
              <td data-label="Vol / OI">{num(t.volume)} / {num(t.open_interest)}{t.vol_oi ? <span className="market-sub"> ({t.vol_oi}×)</span> : null}</td>
              <td data-label="Premium"><strong>{money(t.premium)}</strong></td>
              <td data-label="IV">{t.iv_pct ? `${t.iv_pct}%` : '—'}</td>
              <td data-label="Last vs quote" title="Last trade and current quote are not synchronized. This does not identify buyer or seller intent.">
                {t.side === 'bought' ? '🟢 at ask' : t.side === 'sold' ? '🔴 at bid' : '⚪ mid'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {trades.length > 5 && (
        <button className="clamp-toggle show-mobile" onClick={() => setAll(a => !a)}>
          {all ? 'Show fewer ▴' : `Show all ${trades.length} ▾`}
        </button>
      )}
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

  if (error) return <div className="card"><h3>🌊 Positioning & unusual activity</h3><p className="empty-state" style={{ padding: 0 }}>{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading options flow…</p></div>;

  const pcCls = data.pc_volume > 1 ? 'negative' : data.pc_volume < 0.6 ? 'positive' : '';
  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🌊 Positioning & unusual activity</h3>
        <span className="market-sub">Spot ${data.spot}</span>
      </div>
      {data.summary && <ClampText className="ivrank-verdict-desc">{data.summary}</ClampText>}
      <div className="doctor-stats">
        <div><span>Put/call volume <Tip term="pc_ratio" /></span><strong className={pcCls}>{data.pc_volume ?? '—'}</strong></div>
        <div><span>Put/call open interest <Tip term="open_interest" /></span><strong>{data.pc_oi ?? '—'}</strong></div>
        <div><span>Call wall (resistance) <Tip term="call_wall" /></span><strong>{data.call_wall ? `$${data.call_wall}` : '—'}</strong></div>
        <div><span>Put wall (support) <Tip term="put_wall" /></span><strong>{data.put_wall ? `$${data.put_wall}` : '—'}</strong></div>
        <div>
          <span>Gamma flip <Tip term="gamma_flip" /></span>
          <strong>
            {data.gamma_flip ? `$${data.gamma_flip}` : '—'}
          </strong>
        </div>
        <div>
          <span>Assumed gamma proxy <Tip term="dealer_gamma" /></span>
          <strong className={data.gamma_regime === 'positive' ? 'positive' : data.gamma_regime === 'negative' ? 'negative' : ''}>
            {data.gamma_regime ? `${data.gamma_regime} (${money(Math.abs(data.net_gex))}/1%)` : '—'}
          </strong>
        </div>
        {data.max_pain.map(p => (
          <div key={p.expiry}>
            <span>Max pain {p.expiry} ({p.dte}d) <Tip term="max_pain" /></span>
            <strong>${p.max_pain} <span className="market-sub">{p.vs_spot_pct > 0 ? '+' : ''}{p.vs_spot_pct}%</span></strong>
          </div>
        ))}
      </div>
      <h4 className="sub-chart-title">Unusual activity (volume above open interest, ≥ $25K premium) <Tip term="unusual" /></h4>
      <FlowTable trades={data.unusual} />
      <p className="ivrank-note">
        Call/put walls are the strikes with the most open interest within ±20% of spot. Max pain is the price where
        option holders lose the most at expiry. {data.note}
      </p>
    </div>
  );
}
