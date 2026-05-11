import { useState } from 'react';
import { fetchStructures } from '../api/stockApi';

function fmtDollar(v) {
  if (v == null) return '—';
  if (typeof v === 'string') return v;
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

export default function Structures({ ticker }) {
  const [direction, setDirection] = useState('bull');
  const [budget, setBudget] = useState(500);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      setData(await fetchStructures(ticker, direction, budget));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <div className="structures-header">
        <h3 style={{ margin: 0 }}>🛠 Suggested Structures</h3>
      </div>
      <p className="structures-intro">
        Compare a single-leg long option to a defined-risk debit spread on the same idea.
        Spreads are usually the better expected-value trade for retail directional bets.
      </p>

      <div className="structures-controls">
        <div className="tool-row">
          <label>Direction</label>
          <div className="structures-dir-row">
            <button
              className={`structures-dir-btn ${direction === 'bull' ? 'active bull' : ''}`}
              onClick={() => setDirection('bull')}
            >🐂 Bullish</button>
            <button
              className={`structures-dir-btn ${direction === 'bear' ? 'active bear' : ''}`}
              onClick={() => setDirection('bear')}
            >🐻 Bearish</button>
          </div>
        </div>
        <div className="tool-row">
          <label>Budget ($)</label>
          <input
            type="number"
            className="tool-input"
            value={budget}
            min={50}
            step={50}
            onChange={e => setBudget(Number(e.target.value) || 0)}
          />
        </div>
        <button className="btn-primary btn-sm" onClick={load} disabled={loading || !ticker || budget < 50}>
          {loading ? 'Loading…' : 'Compare'}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {data && data.structures.length === 0 && (
        <p className="empty-state">No tradable structures available for {ticker} at this budget.</p>
      )}

      {data && data.structures.length > 0 && (
        <>
          <div className="structures-meta">
            Spot ${data.spot} · Expiry {data.expiry} ({data.dte}d)
          </div>
          <div className="structures-grid">
            {data.structures.map((s, i) => (
              <div key={i} className="structure-card">
                <div className="structure-title">{s.type}</div>
                <div className="structure-legs">
                  {s.legs.map((leg, j) => (
                    <div key={j} className={`structure-leg ${leg.action === 'BUY' ? 'leg-buy' : 'leg-sell'}`}>
                      {leg.action} {leg.strike} @ ${leg.mid}
                    </div>
                  ))}
                </div>
                <div className="structure-stats">
                  <div><span>Contracts</span><strong>{s.contracts}</strong></div>
                  <div><span>Cost</span><strong>{fmtDollar(s.cost)}</strong></div>
                  <div><span>Max Loss</span><strong className="negative">{fmtDollar(s.max_loss)}</strong></div>
                  <div><span>Max Profit</span><strong className="positive">{fmtDollar(s.max_profit)}</strong></div>
                  <div><span>Breakeven</span><strong>${s.breakeven}</strong></div>
                  <div><span>Move Needed</span><strong>{s.move_needed_pct}%</strong></div>
                </div>
                <p className="structure-notes">{s.notes}</p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
