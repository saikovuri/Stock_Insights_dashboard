import { useState, useEffect } from 'react';
import { fetchIvRank } from '../api/stockApi';

const LEVEL = {
  high: { text: 'Premium expensive', cls: 'ivrank-high' },
  normal: { text: 'Premium fair', cls: 'ivrank-mid' },
  low: { text: 'Premium cheap', cls: 'ivrank-low' },
};

function fmtDate(d) {
  return new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function IvRank({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    setLoading(true);
    setError(null);
    fetchIvRank(ticker)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (loading) return <div className="card"><p className="loading-text">Loading volatility…</p></div>;
  if (error) return <div className="card"><h3>📊 Volatility & Expected Move</h3><p className="empty-state">{error}</p></div>;
  if (!data) return null;

  const level = LEVEL[data.level];
  const maxVol = Math.max(data.iv_pct || 0, data.rv_pct || 0, 1);

  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>📊 Volatility & Expected Move</h3>
        {level && <span className={`ivrank-badge ${level.cls}`}>{level.text}</span>}
      </div>

      <p className="ivrank-verdict-desc">{data.summary}</p>

      {data.iv_rank != null ? (
        <div className="ivrank-bar-wrap">
          <div className="ivrank-bar-track">
            <div className={`ivrank-bar-fill ${level?.cls || ''}`} style={{ width: `${data.iv_rank}%` }} />
          </div>
          <div className="ivrank-bar-labels">
            <span>Cheapest (1y)</span>
            <span>IV rank {data.iv_rank} · percentile {data.iv_percentile}</span>
            <span>Most expensive</span>
          </div>
        </div>
      ) : (data.iv_pct != null && data.rv_pct != null) && (
        <div className="vol-compare">
          <div className="vol-row">
            <span>Options expect</span>
            <div className="vol-track"><div className="vol-fill vol-iv" style={{ width: `${data.iv_pct / maxVol * 100}%` }} /></div>
            <strong>{data.iv_pct}%</strong>
          </div>
          <div className="vol-row">
            <span>Stock actually moved</span>
            <div className="vol-track"><div className="vol-fill vol-rv" style={{ width: `${data.rv_pct / maxVol * 100}%` }} /></div>
            <strong>{data.rv_pct}%</strong>
          </div>
          <p className="ivrank-note">
            Yearly volatility. True IV rank unlocks after {data.iv_history_needed} trading days of snapshots
            ({data.iv_history_days}/{data.iv_history_needed} so far).
          </p>
        </div>
      )}

      <div className="ivrank-grid">
        {data.moves.map(m => (
          <div key={m.expiry} className="ivrank-stat">
            <div className="ivrank-stat-label">{m.label} · by {fmtDate(m.expiry)} ({m.dte}d)</div>
            <div className="ivrank-stat-value">${m.low.toFixed(2)} – ${m.high.toFixed(2)}</div>
            <div className="ivrank-stat-sub">±${m.move.toFixed(2)} (±{m.move_pct}%) · ~68% chance it ends in this range</div>
          </div>
        ))}
        <div className={`ivrank-stat ${data.earnings_in_window ? 'ivrank-warn' : ''}`}>
          <div className="ivrank-stat-label">Next earnings</div>
          <div className="ivrank-stat-value">{data.earnings_date ? fmtDate(data.earnings_date) : 'Not scheduled'}</div>
          {data.earnings_in_days != null && (
            <div className="ivrank-stat-sub">
              in {data.earnings_in_days} days{data.earnings_in_window ? ' — inside the monthly window, expect a jump in premium' : ''}
            </div>
          )}
        </div>
      </div>

      <button className="ai-chat-clear" onClick={() => setShowHelp(s => !s)}>
        {showHelp ? 'Hide explanation' : 'What do these mean?'}
      </button>
      {showHelp && (
        <ul className="ivrank-help">
          <li><b>Implied volatility (IV)</b> — how much movement option prices are betting on, as a yearly %.</li>
          <li><b>Realized volatility</b> — how much the stock actually moved over the last 20 trading days.</li>
          <li><b>IV rank</b> — today's IV vs. the past year: 0 = cheapest, 100 = most expensive. High favours option sellers, low favours buyers.</li>
          <li><b>Expected move</b> — the range the market prices for ~68% of outcomes by that date. If your idea needs a bigger move, options are unlikely to pay.</li>
        </ul>
      )}
    </div>
  );
}
