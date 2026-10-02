import { useState, useEffect } from 'react';
import { fetchWheelIdeas } from '../api/stockApi';
import Tip from './Tip';
import WheelManager from './WheelManager';
import WheelAsk from './WheelAsk';

const LIQ = { good: ['Liquid', 'positive'], ok: ['OK liquidity', ''], thin: ['Thin', 'negative'] };
const money = v => `$${Math.round(v).toLocaleString()}`;
const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

function WheelCard({ c, onSelect, onManage }) {
  const [liqText, liqCls] = LIQ[c.liquidity] || LIQ.ok;
  return (
    <div className={`structure-card ${c.flags.length ? '' : 'safety-safer'}`}>
      <div className="structure-title">
        <button className="link-btn" onClick={() => onSelect(c.ticker)}><strong>{c.ticker}</strong></button>
        {' '}<span className="market-sub">{c.name} · ${c.price}</span>
        {!c.flags.length && <span className="safety-badge safety-ok">🛡 Passes checks</span>}
      </div>
      <div className="structure-legs">
        <div className="structure-leg leg-sell">
          SELL ${c.strike} put · {fmtDate(c.expiry)}{c.monthly ? ' (monthly)' : ''} · {c.dte}d @ ${((c.bid + c.ask) / 2).toFixed(2)}
          <span className="structure-leg-oi"> · OI {c.open_interest.toLocaleString()}</span>
        </div>
      </div>
      <div className="structure-stats">
        <div><span>Premium</span><strong className="positive">{money(c.premium)}</strong></div>
        <div><span>Annualized</span><strong>{c.annualized_pct}%</strong></div>
        <div><span>Cushion below price</span><strong>{c.cushion_pct}%</strong></div>
        <div><span>Chance of assignment</span><strong>~{c.prob_assigned_pct}%</strong></div>
        <div><span>Cost if assigned</span><strong>${c.breakeven}</strong></div>
        <div><span>Cash needed</span><strong>{money(c.capital)}</strong></div>
        <div><span>Relative strength <Tip term="rs_rating" /></span><strong>{c.rs_rating}</strong></div>
        <div><span>Liquidity <Tip term="open_interest" /></span><strong className={liqCls}>{liqText}</strong></div>
      </div>
      <ul className="idea-checks">
        <li className="positive">✓ Uptrend, {c.pct_from_high}% from 52-week high, {c.atr_pct}% average daily range</li>
        {c.outside_expected_move
          ? <li className="positive">✓ Strike below the ±{c.expected_move_pct}% expected move</li>
          : c.expected_move_pct != null && <li className="rvol-warm">⚠ Strike inside the ±{c.expected_move_pct}% expected move</li>}
        {c.iv_rich && <li className="positive">✓ Options pricing more movement ({c.iv_pct}%) than the stock shows (~{c.rv_pct}%)</li>}
        {c.earnings_before_expiry
          ? <li className="rvol-warm">⚠ Earnings {fmtDate(c.earnings_date)}{c.earnings_confirmed ? '' : ' (est.)'} before expiry — gap risk</li>
          : c.earnings_date && <li className="positive">✓ Earnings {fmtDate(c.earnings_date)}{c.earnings_confirmed ? '' : ' (est.)'} after expiry</li>}
        {c.last_earnings && c.days_since_earnings <= 14 && (
          <li className="positive">✓ Just reported {fmtDate(c.last_earnings)} — earnings risk is behind it</li>
        )}
      </ul>
      <div className="wheel-actions">
        <button className="link-btn" onClick={() => onManage({
          mode: 'repair', ticker: c.ticker, strike: c.strike, expiry: c.expiry, credit: +(c.premium / 100).toFixed(2),
        })}>🔧 If it's tested: roll / repair</button>
        <button className="link-btn" onClick={() => onManage({ mode: 'assigned', ticker: c.ticker, costBasis: c.breakeven })}>
          📞 If assigned: covered calls
        </button>
      </div>
    </div>
  );
}

export default function WheelIdeas({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [cash, setCash] = useState('');
  const [safeOnly, setSafeOnly] = useState(true);
  const [preset, setPreset] = useState(null);
  const manage = p => {
    setPreset(p);
    setTimeout(() => document.getElementById('wheel-manager')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  };

  useEffect(() => {
    let timer;
    const load = () => fetchWheelIdeas().then(d => {
      setData(d);
      if (d.status === 'building') timer = setTimeout(load, 15_000);
    }).catch(e => setError(e.message));
    load();
    return () => clearTimeout(timer);
  }, []);

  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading wheel candidates…</p></div>;
  if (data.status === 'building') {
    return <div className="card"><p className="loading-text">Screening quality stocks and their option chains — about a minute the first time…</p></div>;
  }
  const rows = data.rows
    .filter(c => !cash || c.capital <= Number(cash))
    .filter(c => !safeOnly || !c.earnings_before_expiry);

  return (
    <>
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🎡 Wheel candidates</h3>
        <span className="market-sub">Updated {new Date(data.updated_at).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</span>
      </div>
      <p className="structures-intro">
        The wheel: sell a cash-secured put on a stock you'd happily own. If it expires, keep the premium and repeat; if
        you're assigned, sell covered calls above your cost until the shares are called away. We screen the S&P 500 for
        steady uptrends near their highs with calm daily ranges ({data.quality_pool} of {data.screened} pass), then pick a
        ~{Math.round(data.target_delta * 100)}-delta put 3–7 weeks out on the most liquid strike — before earnings where
        possible — and rank by premium per unit of risk.
      </p>
      <div className="income-controls">
        <label>Cash available ($)
          <input type="number" className="tool-input" min={0} step={1000} value={cash} placeholder="any"
            onChange={e => setCash(e.target.value)} />
        </label>
        <label className="prepost-toggle">
          <input type="checkbox" checked={safeOnly} onChange={e => setSafeOnly(e.target.checked)} />
          Skip trades that hold through earnings
        </label>
      </div>
      {rows.length ? (
        <div className="structures-grid income-grid">
          {rows.slice(0, 12).map(c => <WheelCard key={c.ticker} c={c} onSelect={onSelect} onManage={manage} />)}
        </div>
      ) : (
        <p className="empty-state">No candidates match{cash ? ` ${money(Number(cash))} of cash` : ''} right now.</p>
      )}
      <ul className="ivrank-help">
        <li>Take profit at ~50% of the premium and sell the next put — don't wait for the last few cents.</li>
        <li>If the stock drops through the strike, roll down and out for a credit, or accept the shares — use <b>Manage a wheel position</b> below.</li>
        <li>Once assigned, sell covered calls at or above your cost-if-assigned price so a call-away is never a loss.</li>
        <li>Keep any one name to a small slice of your account — assignment ties up the full cash amount.</li>
      </ul>
      <p className="ivrank-note">Quotes refresh every few hours during market hours. Probabilities are model estimates, not guarantees. Not financial advice.</p>
    </div>
    <WheelAsk onManage={manage} onSelect={onSelect} />
    <WheelManager preset={preset} />
    </>
  );
}
