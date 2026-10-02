import { useState } from 'react';
import { askWheel } from '../api/stockApi';
import { useAuth } from '../AuthContext';
import Tip from './Tip';

const VERDICT = {
  good: ['👍 Good wheel candidate', 'safety-ok'],
  caution: ['⚠️ Proceed with caution', 'safety-warn'],
  avoid: ['⛔ Avoid for now', 'safety-bad'],
};
const LIQ = { good: ['Liquid', 'positive'], ok: ['OK', ''], thin: ['Thin', 'negative'] };
const money = v => `$${Math.round(v).toLocaleString()}`;
const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

export default function WheelAsk({ onManage, onSelect }) {
  const { user } = useAuth();
  const [ticker, setTicker] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async e => {
    e?.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setLoading(true); setError(null); setData(null);
    try {
      setData(await askWheel(t));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const ai = data?.ai;
  const pick = ai?.suggested_strike != null ? data.ladder.find(l => l.strike === ai.suggested_strike) : null;
  return (
    <div className="card">
      <h3>🤖 Ask about a stock</h3>
      <p className="structures-intro">
        Not in the list? Check any ticker: we run the same wheel checks and put ladder on live option chains, and the
        AI weighs them with fundamentals, the latest earnings and news to say whether it's a sensible wheel — and at
        which strike.
      </p>
      {!user ? (
        <p className="empty-state">Sign in to ask the AI about a stock.</p>
      ) : (
        <form className="income-controls" onSubmit={run}>
          <label>Ticker
            <input className="tool-input" value={ticker} placeholder="e.g. MU, WDC" onChange={e => setTicker(e.target.value)} />
          </label>
          <button className="btn-primary btn-sm" disabled={!ticker.trim() || loading}>{loading ? 'Analyzing…' : 'Ask'}</button>
        </form>
      )}
      {loading && <p className="loading-text">Reading option chains, fundamentals and news…</p>}
      {error && <p className="empty-state">{error}</p>}

      {data && (
        <>
          <div className="ivrank-header" style={{ marginTop: '0.75rem' }}>
            <h4 style={{ margin: 0 }}>
              <button className="link-btn" onClick={() => onSelect(data.ticker)}><strong>{data.ticker}</strong></button>
              {' '}<span className="market-sub">${data.price}{data.sector ? ` · ${data.sector}` : ''}</span>
            </h4>
            {ai && <span className={`safety-badge ${VERDICT[ai.verdict][1]}`}>{VERDICT[ai.verdict][0]}</span>}
          </div>

          {ai ? (
            <>
              <p className="ivrank-verdict-desc">{ai.summary}</p>
              <div className="two-column">
                <div>
                  <h4 className="sub-chart-title">Why it works</h4>
                  <ul className="idea-checks">{ai.pros.map(p => <li key={p} className="positive">✓ {p}</li>)}</ul>
                </div>
                <div>
                  <h4 className="sub-chart-title">Risks</h4>
                  <ul className="idea-checks">{ai.cons.map(c => <li key={c} className="rvol-warm">⚠ {c}</li>)}</ul>
                </div>
              </div>
              <p className="structure-why">
                <b>{pick ? `Suggested: sell the $${pick.strike} put, ${fmtDate(data.expiry)}.` : 'Suggested: wait — no put to sell right now.'}</b>{' '}
                {ai.strike_reason}
              </p>
              {ai.if_assigned && <p className="structure-why"><b>If assigned:</b> {ai.if_assigned}</p>}
              {ai.watch.length > 0 && <p className="structure-why"><b>Watch:</b> {ai.watch.join(' · ')}</p>}
            </>
          ) : (
            <p className="ivrank-note">{data.ai_error || 'AI is not configured — showing the numbers only.'}</p>
          )}

          <h4 className="sub-chart-title">Wheel checks</h4>
          <ul className="idea-checks">
            {data.quality_checks.map(c => <li key={c.text} className={c.ok ? 'positive' : 'rvol-warm'}>{c.ok ? '✓' : '⚠'} {c.text}</li>)}
            {data.expected_move_pct != null && (
              <li className={data.iv_pct > data.rv_pct * 1.1 ? 'positive' : ''}>
                Options price {data.iv_pct}% yearly volatility vs ~{data.rv_pct}% the stock shows · ±{data.expected_move_pct}% expected move by expiry
              </li>
            )}
            <li className={data.earnings_before_expiry ? 'rvol-warm' : 'positive'}>
              {data.earnings_before_expiry ? '⚠' : '✓'} {data.earnings_date ? `Earnings ${fmtDate(data.earnings_date)}${data.earnings_confirmed ? '' : ' (est.)'} ${data.earnings_before_expiry ? 'before' : 'after'} the ${fmtDate(data.expiry)} expiry` : 'No earnings date in the next 90 days'}
            </li>
            {data.last_earnings && data.days_since_earnings <= 14 && (
              <li className="positive">✓ Just reported {fmtDate(data.last_earnings)} ({data.days_since_earnings}d ago) — earnings risk is behind it</li>
            )}
            <li className={data.passes_screen ? 'positive' : ''}>{data.passes_screen ? '✓ Would make the wheel candidate list' : 'Does not pass the wheel candidate screen'}</li>
          </ul>

          {data.ladder.length > 0 && (
            <>
              <h4 className="sub-chart-title">Put ladder · {fmtDate(data.expiry)}{data.monthly ? ' (monthly)' : ''} ({data.dte}d) <Tip term="delta" /></h4>
              <div className="table-scroll">
                <table className="market-table">
                  <thead><tr><th>Strike</th><th>Δ</th><th>Premium</th><th>Annualized</th><th>Cushion</th><th>Assigned</th><th>Cost if assigned</th><th>Cash</th><th>Liquidity</th><th></th></tr></thead>
                  <tbody>
                    {data.ladder.map(l => (
                      <tr key={l.strike} className={`no-click ${pick?.strike === l.strike ? 'row-editing' : ''}`}>
                        <td><strong>${l.strike}</strong>{pick?.strike === l.strike && ' ⭐'}</td>
                        <td>{l.delta}</td>
                        <td className="positive">{money(l.premium)}</td>
                        <td>{l.annualized_pct}%</td>
                        <td>{l.cushion_pct}%</td>
                        <td>~{l.prob_assigned_pct}%</td>
                        <td>${l.breakeven}</td>
                        <td>{money(l.capital)}</td>
                        <td className={LIQ[l.liquidity]?.[1]}>{LIQ[l.liquidity]?.[0]}</td>
                        <td>
                          <button className="btn-icon" title="If tested: roll / repair" onClick={() => onManage({
                            mode: 'repair', ticker: data.ticker, strike: l.strike, expiry: data.expiry, credit: l.mid,
                          })}>🔧</button>
                          <button className="btn-icon" title="If assigned: covered calls"
                            onClick={() => onManage({ mode: 'assigned', ticker: data.ticker, costBasis: l.breakeven })}>📞</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="ivrank-note">AI analysis can be wrong. Educational only — not financial advice.</p>
        </>
      )}
    </div>
  );
}
