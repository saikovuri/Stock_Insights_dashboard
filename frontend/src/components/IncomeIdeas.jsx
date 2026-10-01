import { useState, useEffect } from 'react';
import { fetchIncomeIdeas } from '../api/stockApi';
import Tip from './Tip';
import RollRepair from './RollRepair';

const SAFETY = {
  safer: { text: '🛡 Passes checks', cls: 'safety-ok' },
  caution: { text: 'Caution', cls: 'safety-warn' },
  risky: { text: 'Risky', cls: 'safety-bad' },
};

function Checks({ i }) {
  if (!i.checks) return null;
  return (
    <ul className="idea-checks">
      {i.checks.map((c, k) => <li key={k} className={c.ok ? 'positive' : 'rvol-warm'}>{c.ok ? '✓' : '⚠'} {c.text}</li>)}
    </ul>
  );
}

function SafetyBadge({ i }) {
  const s = SAFETY[i.safety];
  return s ? <span className={`safety-badge ${s.cls}`}>{s.text}</span> : null;
}

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

const ER_RISK = {
  cc: 'Premium is inflated because the stock can gap. A gap up can get your shares called away; a gap down is only cushioned by the premium.',
  csp: 'A gap down can assign you shares well below today\'s price. Only sell if you\'d happily own it at the strike after a bad report.',
  pcs: 'A gap down through the short put can hit max loss overnight, with no chance to adjust.',
  ic: 'Condors are the most exposed: a gap either way can blow through a short strike overnight. Most condor traders close before earnings.',
};

const MODES = {
  cc: {
    label: 'Covered Calls', key: 'covered_calls',
    intro: 'Own 100+ shares? Sell a call above today\'s price to collect premium. If the stock ends above the strike, your shares are sold at the strike.',
  },
  csp: {
    label: 'Cash-Secured Puts', key: 'cash_secured_puts',
    intro: 'Want to buy this stock cheaper? Sell a put below today\'s price and set aside the cash. If the stock ends below the strike, you buy 100 shares per contract at the strike.',
  },
  pcs: {
    label: 'Put Credit Spreads', key: 'put_credit_spreads',
    intro: 'Neutral-to-bullish with a smaller account? Sell a put below the price and buy a cheaper put further down as insurance. You keep the credit if the stock stays above the short strike; the loss is capped at the width minus the credit.',
  },
  ic: {
    label: 'Iron Condors', key: 'iron_condors',
    intro: 'Expect the stock to stay in a range? Sell a put spread below and a call spread above. You keep the credit if it finishes between the short strikes; risk is capped on both sides.',
  },
};

function SpreadCard({ i, mode, expiry, contracts }) {
  const n = Math.max(contracts, 0);
  const legs = mode === 'ic'
    ? [['BUY', i.put_long, 'put'], ['SELL', i.put_short, 'put'], ['SELL', i.call_short, 'call'], ['BUY', i.call_long, 'call']]
    : [['SELL', i.short_strike, 'put'], ['BUY', i.long_strike, 'put']];
  const liq = LIQ[i.liquidity];
  return (
    <div className={`structure-card safety-${i.safety}`}>
      <div className="structure-title">
        {i.label} <span className="income-delta">Δ {i.delta.toFixed(2)}</span> <Tip term="delta" /> <SafetyBadge i={i} />
      </div>
      <div className="structure-legs">
        {legs.map(([action, strike, kind]) => (
          <div key={action + strike + kind} className={`structure-leg ${action === 'BUY' ? 'leg-buy' : 'leg-sell'}`}>
            {action} {n} × ${strike} {kind} · {fmtDate(expiry)}
          </div>
        ))}
      </div>
      <div className="structure-stats">
        <div><span>Credit / contract</span><strong className="positive">{money(i.premium)}</strong></div>
        <div><span>Max loss / contract</span><strong className="negative">{money(i.max_loss)}</strong></div>
        <div><span>Total credit · risk</span><strong>{money(i.premium * n)} · {money(i.max_loss * n)}</strong></div>
        <div><span>Return on risk <Tip term="return_on_risk" /></span><strong>{i.return_on_risk_pct}%</strong></div>
        <div><span>Chance of profit <Tip term="pop" /></span><strong>~{i.prob_profit_pct}% <small>(full credit ~{i.prob_max_profit_pct}%)</small></strong></div>
        {mode === 'ic'
          ? <div><span>Profit zone at expiry</span><strong>${i.breakeven_low} – ${i.breakeven_high}</strong></div>
          : <div><span>Breakeven</span><strong>${i.breakeven} <small>(−{i.breakeven_pct}%)</small></strong></div>}
      </div>
      <Checks i={i} />
      <p className="structure-notes">
        Limit ~${i.credit} net credit (natural ${i.natural_credit} <Tip term="natural_credit" />) · ${i.width} wide · OI {i.open_interest.toLocaleString()} ·{' '}
        <span className={liq.cls}>{liq.text}</span>
      </p>
    </div>
  );
}

export default function IncomeIdeas({ ticker }) {
  const [mode, setMode] = useState('cc');
  const [expiry, setExpiry] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [shares, setShares] = useState(100);
  const [cash, setCash] = useState('');
  const [risk, setRisk] = useState('');

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

  const ideas = data?.[MODES[mode].key] || [];
  const spread = mode === 'pcs' || mode === 'ic';
  const er = data?.earnings_date;
  const erDays = er ? Math.round((new Date(er + 'T12:00:00') - new Date()) / 86400000) : null;
  const erAhead = erDays != null && erDays >= 0;
  const spansEr = exp => erAhead && exp >= er;
  const safeExp = erAhead ? data.expirations.filter(e => e.date < er).at(-1) : null;

  return (
    <div className="card income-ideas">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>💵 Income Ideas</h3>
        <div className="chart-toggle">
          {Object.entries(MODES).map(([id, m]) => (
            <button key={id} className={mode === id ? 'active' : ''} onClick={() => setMode(id)}>{m.label}</button>
          ))}
        </div>
      </div>

      <p className="structures-intro">{MODES[mode].intro}</p>

      {data && (
        <div className="income-controls">
          <label>
            Expiry
            <select className={`candle-select ${spansEr(data.expiry) ? 'income-er-select' : ''}`} value={data.expiry}
              onChange={e => setExpiry(e.target.value)}>
              {data.expirations.map(e => (
                <option key={e.date} value={e.date}>
                  {fmtDate(e.date)} ({e.dte === 0 ? '0DTE — today' : `${e.dte}d`}){spansEr(e.date) ? ' · ⚠️ earnings' : ''}
                </option>
              ))}
            </select>
          </label>
          {mode === 'cc' ? (
            <label>
              Shares owned
              <input type="number" className="tool-input" min={0} step={100} value={shares}
                onChange={e => setShares(Math.max(0, Number(e.target.value) || 0))} />
            </label>
          ) : spread ? (
            <label>
              Max risk ($)
              <input type="number" className="tool-input" min={0} step={100} value={risk} placeholder="optional"
                onChange={e => setRisk(e.target.value)} />
            </label>
          ) : (
            <label>
              Cash available ($)
              <input type="number" className="tool-input" min={0} step={1000} value={cash} placeholder="optional"
                onChange={e => setCash(e.target.value)} />
            </label>
          )}
          <span className="structures-meta">
            Stock ${data.spot}
            {spread && data.expected_move && ` · expected move ±$${data.expected_move.move} ($${data.expected_move.low}–$${data.expected_move.high})`}
            {spread && data.expected_move && <> <Tip term="expected_move" /></>}
          </span>
        </div>
      )}

      {data && data.dte <= 6 && (
        <div className="income-warning">
          <strong>⚡ {data.dte === 0 ? 'Expires today (0DTE)' : `Expires in ${data.dte} day${data.dte === 1 ? '' : 's'}`}</strong>
          <div>Time decay is fastest now, but so is gamma risk: a normal intraday swing can push the stock through
            your short strike in minutes and turn a small credit into a full loss. Use small size and have an exit plan.</div>
        </div>
      )}
      {data && spansEr(data.expiry) && (
        <div className="income-warning income-er">
          <strong>
            ⚠️ Earnings {er === data.expiry ? 'on expiry day' : 'before this expiry'}: {fmtDate(er)}
            {' '}({erDays === 0 ? 'today' : `in ${erDays}d`}) vs expiry {fmtDate(data.expiry)}
          </strong>
          <div>{ER_RISK[mode]}</div>
          {safeExp && (
            <button className="link-btn" onClick={() => setExpiry(safeExp.date)}>
              Use {fmtDate(safeExp.date)} ({safeExp.dte}d) — last expiry before earnings
            </button>
          )}
        </div>
      )}
      {data && erAhead && !spansEr(data.expiry) && (
        <p className="income-er-clear">✓ Earnings {fmtDate(er)} ({erDays}d) is after this expiry.</p>
      )}
      {loading && <p className="loading-text">Loading option chain…</p>}
      {error && <p className="empty-state">{error}</p>}
      {data && !loading && ideas.length === 0 && <p className="empty-state">No liquid strikes found for this expiry.</p>}

      {data && !loading && ideas.length > 0 && (
        <div className="structures-grid income-grid">
          {ideas.map(i => {
            if (spread) {
              const n = risk ? Math.floor(Number(risk) / i.max_loss) : 1;
              return <SpreadCard key={i.label} i={i} mode={mode} expiry={data.expiry} contracts={n} />;
            }
            const contracts = mode === 'cc'
              ? Math.floor(shares / 100)
              : (cash ? Math.floor(Number(cash) / i.capital_required) : 1);
            const liq = LIQ[i.liquidity];
            return (
              <div key={i.strike} className={`structure-card safety-${i.safety}`}>
                <div className="structure-title">
                  {i.label} <span className="income-delta">Δ {Math.abs(i.delta).toFixed(2)}</span> <SafetyBadge i={i} />
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
                <Checks i={i} />
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

      {spread && data && risk && ideas.length > 0 && ideas.every(i => Number(risk) < i.max_loss) && (
        <p className="ivrank-note">Max risk is below one contract's max loss — raise it or pick a cheaper stock.</p>
      )}

      {data && (
        <ul className="ivrank-help">
          {(data.tips?.[mode] || []).map((t, k) => <li key={k}>{t}</li>)}
        </ul>
      )}
      {data && <RollRepair ticker={ticker} mode={mode} expirations={data.expirations} />}
      <p className="ivrank-note">Probabilities are model estimates from option prices, not guarantees. Educational only — not financial advice.</p>
    </div>
  );
}
