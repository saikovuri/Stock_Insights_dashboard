import { useState, useEffect } from 'react';
import { fetchIvRank } from '../api/stockApi';

const VERDICT_LABEL = {
  high: { text: 'High', desc: 'Premium expensive — favor selling premium / spreads, avoid buying naked options' },
  mid: { text: 'Mid', desc: 'Average — neither edge nor handicap on premium' },
  low: { text: 'Low', desc: 'Premium cheap — long calls/puts have a structural tailwind' },
};

export default function IvRank({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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

  if (loading) return <div className="card"><p className="loading-text">Loading IV rank…</p></div>;
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return null;

  const verdict = data.verdict ? VERDICT_LABEL[data.verdict] : null;
  const rankPct = data.rv_rank;
  const expectedLow = data.expected_move_dollars != null ? (data.spot - data.expected_move_dollars) : null;
  const expectedHigh = data.expected_move_dollars != null ? (data.spot + data.expected_move_dollars) : null;

  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>📊 IV Rank &amp; Expected Move</h3>
        {verdict && (
          <span className={`ivrank-badge ivrank-${data.verdict}`}>
            {verdict.text} {rankPct != null && `· ${rankPct}%`}
          </span>
        )}
      </div>

      {rankPct != null && (
        <div className="ivrank-bar-wrap">
          <div className="ivrank-bar-track">
            <div className={`ivrank-bar-fill ivrank-${data.verdict}`} style={{ width: `${rankPct}%` }} />
          </div>
          <div className="ivrank-bar-labels">
            <span>Low {data.rv_low_pct}%</span>
            <span>Now {data.rv_current_pct}%</span>
            <span>High {data.rv_high_pct}%</span>
          </div>
        </div>
      )}

      {verdict && <p className="ivrank-verdict-desc">{verdict.desc}</p>}

      <div className="ivrank-grid">
        <div className="ivrank-stat">
          <div className="ivrank-stat-label">ATM IV ({data.dte}d)</div>
          <div className="ivrank-stat-value">{data.atm_iv_pct != null ? `${data.atm_iv_pct}%` : '—'}</div>
        </div>
        <div className="ivrank-stat">
          <div className="ivrank-stat-label">Expected Move</div>
          <div className="ivrank-stat-value">
            {data.expected_move_dollars != null ? `±$${data.expected_move_dollars} (${data.expected_move_pct}%)` : '—'}
          </div>
        </div>
        <div className="ivrank-stat">
          <div className="ivrank-stat-label">Earnings</div>
          <div className="ivrank-stat-value">{data.earnings_date || 'None upcoming'}</div>
        </div>
      </div>

      {expectedLow != null && expectedHigh != null && (
        <p className="ivrank-range">
          Market is pricing a 1-σ range of <strong>${expectedLow.toFixed(2)} – ${expectedHigh.toFixed(2)}</strong> by {data.expiry}.
          If your trade thesis needs a bigger move than this, the trade is structurally bad before you even pick a strike.
        </p>
      )}

      <p className="ivrank-note">{data.note}</p>
    </div>
  );
}
