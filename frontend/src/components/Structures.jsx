import { useState } from 'react';
import { fetchStructures } from '../api/stockApi';
import Tip from './Tip';

const RISKS = {
  extreme: { label: '⚡ Extreme', sub: '0–6 days', hint: '0DTE / this-week options: lottery-ticket odds, can go to zero in hours.' },
  high: { label: '🔥 High', sub: '1–3 weeks', hint: 'Near-dated options: most leverage, can go to zero fast.' },
  moderate: { label: '⚖️ Moderate', sub: '30–45 days', hint: 'Enough time for the idea to work, still leveraged.' },
  low: { label: '🛡 Low', sub: 'LEAPS / shares', hint: 'Long-dated in-the-money options or shares — slow time decay.' },
};

const LIQ = {
  good: { text: 'Liquid', cls: 'positive' },
  ok: { text: 'OK liquidity', cls: '' },
  thin: { text: 'Thin — wide spread', cls: 'negative' },
};

const money = v => (typeof v === 'string' ? v : `$${Math.round(Number(v)).toLocaleString()}`);
const fmtDate = d => {
  const dt = new Date(d + 'T12:00:00');
  const opts = { month: 'short', day: 'numeric' };
  if (dt.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  return dt.toLocaleDateString(undefined, opts);
};

function IdeaCard({ i, expiry, why }) {
  const liq = LIQ[i.liquidity];
  const unit = i.qty === 1 ? i.unit : `${i.unit}s`;
  return (
    <div className={`structure-card ${i.best ? 'structure-best' : ''}`}>
      <div className="structure-title">
        {i.title}
        {i.best && <span className="structure-best-badge">⭐ Best fit</span>}
      </div>
      {i.best && why && <p className="structure-why">{why}</p>}
      <div className="structure-legs">
        {i.legs.map((l, j) => (
          <div key={j} className={`structure-leg ${l.action === 'BUY' ? 'leg-buy' : 'leg-sell'}`}>
            {l.type === 'shares'
              ? `BUY ${i.qty} ${unit} @ $${l.mid}`
              : `${l.action} ${i.qty} × $${l.strike} ${l.type} · ${fmtDate(expiry)} @ $${l.mid}`}
            {l.oi != null && (
              <span className="structure-leg-oi">
                {' '}· OI {l.oi.toLocaleString()}{l.spread_pct != null && ` · bid/ask ${l.spread_pct}%`}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="structure-stats">
        <div><span>Size</span><strong>{i.qty} {unit}</strong></div>
        <div><span>Cost</span><strong>{money(i.cost)}</strong></div>
        <div><span>Max loss</span><strong className="negative">{money(i.max_loss)}</strong></div>
        <div><span>Max profit</span><strong className="positive">{money(i.max_profit)}</strong></div>
        <div><span>Breakeven</span><strong>${i.breakeven}</strong></div>
        <div><span>Move needed</span><strong>{i.move_needed_pct > 0 ? '+' : ''}{i.move_needed_pct}%</strong></div>
        {i.prob_profit_pct != null && (
          <div><span>Chance of profit <Tip term="pop" /></span><strong>~{i.prob_profit_pct}%</strong></div>
        )}
        {i.reward_risk != null && <div><span>Reward : risk</span><strong>{i.reward_risk} : 1</strong></div>}
        {i.open_interest != null && (
          <div><span>Liquidity <Tip term="open_interest" /></span><strong className={liq?.cls}>{liq?.text}</strong></div>
        )}
      </div>
      <p className="structure-notes">{i.notes}</p>
    </div>
  );
}

export default function Structures({ ticker }) {
  const [direction, setDirection] = useState('bull');
  const [risk, setRisk] = useState('moderate');
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
      setData(await fetchStructures(ticker, direction, budget, risk));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const em = data?.expected_move;
  return (
    <div className="card">
      <div className="structures-header">
        <h3 style={{ margin: 0 }}>🛠 Directional trade finder</h3>
      </div>
      <p className="structures-intro">
        Pick a direction, how much risk you want and your budget. We pick the most liquid expiry and strikes in
        that window (high open interest, tight bid/ask), size shares, a single option and a debit spread to it, and
        highlight the best fit.
      </p>

      <div className="structures-controls">
        <div className="tool-row">
          <label>Direction</label>
          <div className="structures-dir-row">
            <button className={`structures-dir-btn ${direction === 'bull' ? 'active bull' : ''}`} onClick={() => setDirection('bull')}>🐂 Bullish</button>
            <button className={`structures-dir-btn ${direction === 'bear' ? 'active bear' : ''}`} onClick={() => setDirection('bear')}>🐻 Bearish</button>
          </div>
        </div>
        <div className="tool-row">
          <label>Risk</label>
          <div className="structures-dir-row">
            {Object.entries(RISKS).map(([k, r]) => (
              <button key={k} className={`structures-dir-btn structures-risk-btn ${risk === k ? 'active risk' : ''}`}
                onClick={() => setRisk(k)} title={r.hint}>
                {r.label}<small>{r.sub}</small>
              </button>
            ))}
          </div>
        </div>
        <div className="tool-row">
          <label>Budget ($)</label>
          <input type="number" className="tool-input" value={budget} min={50} step={50}
            onChange={e => setBudget(Number(e.target.value) || 0)} />
        </div>
        <button className="btn-primary btn-sm" onClick={load} disabled={loading || !ticker || budget < 50}>
          {loading ? 'Loading…' : 'Find trades'}
        </button>
      </div>

      {error && <p className="error-text">{error}</p>}

      {data && (
        <div className="structures-meta">
          Spot ${data.spot} · {data.timeframe}: expiry {fmtDate(data.expiry)}{data.monthly ? ' (monthly)' : ''} ({data.dte === 0 ? '0DTE — today' : `${data.dte}d`})
          {em && <> · expected move ±{em.pct}% (${em.low}–${em.high}) <Tip term="expected_move" /></>}
          {data.iv_level && <> · options {data.iv_level === 'high' ? 'expensive' : data.iv_level === 'low' ? 'cheap' : 'fairly priced'}</>}
          {data.expiry_note && <div className="structure-why">✓ {data.expiry_note}</div>}
        </div>
      )}

      {data?.earnings_before_expiry && data.ideas.some(i => i.kind !== 'shares') && (
        <div className="income-warning income-er">
          <strong>⚠️ Earnings {fmtDate(data.earnings_date)} is before this expiry.</strong>
          <div>Options carry extra premium into the report and usually lose it the day after (IV crush) — the stock
            has to beat the expected move, not just go your way.</div>
        </div>
      )}

      {data && data.ideas.length === 0 && (
        <p className="empty-state">
          Nothing fits a ${budget.toLocaleString()} budget for {ticker}
          {data.min_budget_needed ? ` — the cheapest idea needs about $${Math.ceil(data.min_budget_needed).toLocaleString()}` : ''}.
          {!['high', 'extreme'].includes(risk) && ' A higher-risk (shorter-dated) choice is cheaper.'}
        </p>
      )}

      {data && data.ideas.length > 0 && (
        <>
          <div className="structures-grid">
            {data.ideas.map(i => <IdeaCard key={i.kind} i={i} expiry={data.expiry} why={data.best_why} />)}
          </div>
          {direction === 'bear' && (
            <p className="ivrank-note">Shorting shares isn't suggested — its loss is unlimited. Puts and put spreads cap the risk at what you pay.</p>
          )}
        </>
      )}
    </div>
  );
}
