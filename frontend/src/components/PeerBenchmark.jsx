import { useState, useEffect } from 'react';
import { fetchPeers } from '../api/stockApi';

function fmt(n) {
  if (n == null) return 'N/A';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(1)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

function Bar({ value, max, isBase }) {
  if (max == null || max === 0 || value == null) return <span>—</span>;
  const pct = Math.min(100, (value / max) * 100);
  return (
    <div className="peer-bar-wrap" title={value?.toFixed(2)}>
      <div className="peer-bar-track">
        <div
          className={`peer-bar-fill ${isBase ? 'peer-bar-base' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="peer-bar-val">{value?.toFixed(1)}</span>
    </div>
  );
}

export default function PeerBenchmark({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    setLoading(true);
    setError(null);
    fetchPeers(ticker)
      .then(d => {
        if (!d.peers || d.peers.length === 0) setError(`No peer data available for ${ticker}`);
        else setData(d);
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return <div className="card"><p className="loading-text">Loading peer data…</p></div>;
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return null;

  const all = [data.base, ...data.peers];
  const maxPE = Math.max(...all.map(p => p.pe_ratio || 0).filter(Boolean));
  const maxCap = Math.max(...all.map(p => p.market_cap || 0).filter(Boolean));
  const maxBeta = Math.max(...all.map(p => p.beta || 0).filter(Boolean));

  return (
    <div className="card peer-card">
      <div className="peer-header">
        <h3 style={{ margin: 0 }}>📊 Peer Comparison</h3>

      </div>
      <div className="peer-table-wrap">
        <table className="peer-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Price</th>
              <th>Chg%</th>
              <th>P/E Ratio</th>
              <th>Market Cap</th>
              <th>EPS</th>
              <th>Beta</th>
              <th>Div%</th>
            </tr>
          </thead>
          <tbody>
            {all.map((p, i) => {
              const isBase = p.ticker === data.base.ticker;
              return (
                <tr key={p.ticker} className={isBase ? 'peer-row-base' : ''}>
                  <td><strong>{p.ticker}</strong>{isBase && <span className="peer-you-badge">you</span>}</td>
                  <td>${p.price?.toFixed(2) ?? 'N/A'}</td>
                  <td className={p.change_pct >= 0 ? 'positive' : 'negative'}>
                    {p.change_pct != null ? `${p.change_pct >= 0 ? '+' : ''}${p.change_pct.toFixed(2)}%` : 'N/A'}
                  </td>
                  <td><Bar value={p.pe_ratio} max={maxPE} isBase={isBase} /></td>
                  <td>{fmt(p.market_cap)}</td>
                  <td>{p.eps != null ? `$${p.eps.toFixed(2)}` : 'N/A'}</td>
                  <td><Bar value={p.beta} max={maxBeta} isBase={isBase} /></td>
                  <td>{p.dividend_yield != null ? `${(p.dividend_yield * 100).toFixed(2)}%` : 'N/A'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
