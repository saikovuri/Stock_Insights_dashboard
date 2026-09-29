import { useState, useEffect } from 'react';
import { fetchIncomeIdeas } from '../api/stockApi';

const LIQ = {
  good: { text: 'Liquid', cls: 'positive' },
  ok: { text: 'OK liquidity', cls: '' },
  thin: { text: 'Thin — wide spread', cls: 'negative' },
};

function money(v) {
  return `$${Math.round(Number(v)).toLocaleString()}`;
}

function fmtDate(d) {
  return new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function IncomeIdeas({ ticker }) {
  const [mode, setMode] = useState('cc');
  const [expiry, setExpiry] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [shares, setShares] = useState(100);
  const [cash, setCash] = useState('');

  useEffect(() => { setExpiry(null); setData(null); }, [ticker]);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    fetchIncomeIdeas(ticker, expiry)
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker, expiry]);

  const ideas = data ? (mode === 'cc' ? data.covered_calls : data.cash_secured_puts) : [];

  return (
    <div className="card income-ideas">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>💵 Income Ideas</h3>
        <div className="chart-toggle">
          <button className={mode === 'cc' ? 'active' : ''} onClick={() => setMode('cc')}>Covered Calls</button>
          <button className={mode === 'csp' ? 'active' : ''} onClick={() => setMode('csp')}>Cash-Secured Puts</button>
        </div>
      </div>

      <p className="structures-intro">
        {mode === 'cc'
          ? 'Own 100+ shares? Sell a call above today\'s price to collect premium. If the stock ends above the strike, your shares are sold at the strike.'
          : 'Want to buy this stock cheaper? Sell a put below today\'s price and set aside the cash. If the stock ends below the strike, you buy 100 shares per contract at the strike.'}
      </p>

      {data && (
        <div className="income-controls">
          <label>
            Expiry
            <select className="candle-select" value={data.expiry} onChange={e => setExpiry(e.target.value)}>
              {data.expirations.map(e => <option key={e.date} value={e.date}>{fmtDate(e.date)} ({e.dte}d)</option>)}
            </select>
          </label>
          {mode === 'cc' ? (
            <label>
              Shares owned
              <input type="number" className="tool-input" min={0} step={100} value={shares}
                onChange={e => setShares(Math.max(0, Number(e.target.value) || 0))} />
            </label>
          ) : (
            <label>
              Cash available ($)
              <input type="number" className="tool-input" min={0} step={1000} value={cash} placeholder="optional"
                onChange={e => setCash(e.target.value)} />
            </label>
          )}
          <span className="structures-meta">Stock ${data.spot}</span>
        </div>
      )}

      {data?.earnings_before_expiry && (
        <div className="income-warning">⚠️ Earnings on {fmtDate(data.earnings_date)} fall before this expiry — bigger premium, but gap risk.</div>
      )}
      {loading && <p className="loading-text">Loading option chain…</p>}
      {error && <p className="empty-state">{error}</p>}
      {data && !loading && ideas.length === 0 && <p className="empty-state">No liquid strikes found for this expiry.</p>}

      {data && !loading && ideas.length > 0 && (
        <div className="structures-grid income-grid">
          {ideas.map(i => {
            const contracts = mode === 'cc'
              ? Math.floor(shares / 100)
              : (cash ? Math.floor(Number(cash) / i.capital_required) : 1);
            const liq = LIQ[i.liquidity];
            return (
              <div key={i.strike} className="structure-card">
                <div className="structure-title">
                  {i.label} <span className="income-delta">Δ {Math.abs(i.delta).toFixed(2)}</span>
                </div>
                <div className="structure-legs">
                  <div className="structure-leg leg-sell">
                    SELL {Math.max(contracts, 0)} × ${i.strike} {mode === 'cc' ? 'call' : 'put'} · {fmtDate(data.expiry)}
                  </div>
                </div>
                <div className="structure-stats">
                  <div><span>Premium / contract</span><strong className="positive">{money(i.premium)}</strong></div>
                  <div><span>Total premium</span><strong className="positive">{money(i.premium * Math.max(contracts, 0))}</strong></div>
                  <div><span>Return</span><strong>{i.return_pct}% <small>({i.annualized_pct}%/yr)</small></strong></div>
                  <div><span>Chance of {mode === 'cc' ? 'shares called away' : 'buying shares'}</span><strong>~{i.prob_assigned_pct}%</strong></div>
                  {mode === 'cc' ? (
                    <>
                      <div><span>Strike above price</span><strong>+{i.otm_pct}%</strong></div>
                      <div><span>Total gain if called</span><strong>{i.if_called_pct}%</strong></div>
                    </>
                  ) : (
                    <>
                      <div><span>Cash needed / contract</span><strong>{money(i.capital_required)}</strong></div>
                      <div><span>Net buy price if assigned</span><strong>${i.effective_buy_price} <small>(−{i.discount_pct}%)</small></strong></div>
                    </>
                  )}
                </div>
                <p className="structure-notes">
                  Limit ~${i.mid} (bid ${i.bid} / ask ${i.ask}) · OI {i.open_interest.toLocaleString()} ·{' '}
                  <span className={liq.cls}>{liq.text}</span>
                </p>
              </div>
            );
          })}
        </div>
      )}

      {mode === 'cc' && data && shares < 100 && (
        <p className="ivrank-note">You need at least 100 shares per covered call contract.</p>
      )}
      {mode === 'csp' && data && cash && ideas.length > 0 && Math.floor(Number(cash) / ideas[0].capital_required) < 1 && (
        <p className="ivrank-note">Not enough cash for one contract at these strikes — try a lower-priced stock.</p>
      )}

      {data && (
        <ul className="ivrank-help">
          {data.tips.filter(t => !t.startsWith('⚠️')).filter(t => (mode === 'cc' ? !t.startsWith('Cash-secured') : !t.startsWith('Covered'))).map((t, k) => <li key={k}>{t}</li>)}
        </ul>
      )}
      <p className="ivrank-note">Probabilities are model estimates from option prices, not guarantees. Educational only — not financial advice.</p>
    </div>
  );
}
