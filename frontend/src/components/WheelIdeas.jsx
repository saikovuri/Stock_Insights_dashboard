import { useState, useEffect } from 'react';
import { fetchWheelIdeas, fetchWheelPlan } from '../api/stockApi';
import Tip from './Tip';
import WheelManager from './WheelManager';
import WheelAsk from './WheelAsk';
import { usePortfolioFit, FitBadge } from './PortfolioFit';

const LIQ = { good: ['Liquid', 'positive'], ok: ['OK liquidity', ''], thin: ['Thin', 'negative'] };
const money = v => `$${Math.round(v).toLocaleString()}`;
const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

function WheelCard({ c, onSelect, onManage, fit }) {
  const [liqText, liqCls] = LIQ[c.liquidity] || LIQ.ok;
  return (
    <div className={`structure-card ${c.flags.length ? '' : 'safety-safer'}`}>
      <div className="structure-title">
        <button className="link-btn" onClick={() => onSelect(c.ticker)}><strong>{c.ticker}</strong></button>
        {' '}<span className="market-sub">{c.name} · ${c.price}</span>
        {!c.flags.length && <span className="safety-badge safety-ok">🛡 Passes checks</span>}
      </div>
      {fit && <FitBadge fit={fit} detailed />}
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

function WheelPlan({ onSelect, shortDated }) {
  const [capital, setCapital] = useState(50000);
  const [maxPct, setMaxPct] = useState(25);
  const [perSector, setPerSector] = useState(2);
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const build = () => {
    setBusy(true); setErr(null);
    fetchWheelPlan(capital, maxPct, perSector, shortDated).then(setPlan).catch(e => setErr(e.message)).finally(() => setBusy(false));
  };
  return (
    <div className="card">
      <h3 style={{ margin: 0 }}>🧮 Wheel capital planner</h3>
      <p className="structures-intro">
        Spread your cash across several puts instead of one big one, so a single bad stock or sector can't sink the account.
      </p>
      <div className="income-controls">
        <label>Total account cash, including reserves ($)
          <input type="number" className="tool-input" min={1000} step={5000} value={capital} onChange={e => setCapital(+e.target.value)} />
        </label>
        <label>Max per stock (%)
          <input type="number" className="tool-input" min={5} max={100} step={5} value={maxPct} onChange={e => setMaxPct(+e.target.value)} />
        </label>
        <label>Max stocks per sector
          <input type="number" className="tool-input" min={1} max={10} value={perSector} onChange={e => setPerSector(+e.target.value)} />
        </label>
        <button className="btn-primary btn-sm" onClick={build} disabled={busy || capital < 1000}>{busy ? 'Planning…' : 'Build plan'}</button>
      </div>
      {err && <p className="error-text">{err}</p>}
      {plan?.blocked?.map(reason => <p key={reason} className="error-text">{reason}</p>)}
      {plan && <p className="market-sub">Already reserved: {money(plan.reserved_cash || 0)}. Cash left: {money(plan.cash_left)}.</p>}
      {plan && (plan.picks.length === 0 ? (
        <p className="empty-state">No candidates fit {money(plan.capital)} with these limits.
          {plan.skipped_expensive.length > 0 && ` ${plan.skipped_expensive[0].reason}.`}</p>
      ) : (
        <>
          <div className="doctor-stats">
            <div><span>Cash used</span><strong>{money(plan.used)} <small className="market-sub">({money(plan.cash_left)} left)</small></strong></div>
            <div><span>Premium now</span><strong className="positive">{money(plan.income)}</strong></div>
            <div><span>~ per month</span><strong className="positive">{money(plan.monthly_income)}</strong></div>
            <div><span>Annualized on cash used</span><strong>{plan.annualized_pct}%</strong></div>
          </div>
          <table className="market-table">
            <thead><tr><th>Stock</th><th>Sell put</th><th>Contracts</th><th>Cash</th><th>Premium</th><th>Cushion</th></tr></thead>
            <tbody>
              {plan.picks.map(p => (
                <tr key={p.ticker}>
                  <td><button className="link-btn" onClick={() => onSelect(p.ticker)}><strong>{p.ticker}</strong></button>
                    <div className="market-sub">{p.sector}</div></td>
                  <td>${p.strike} · {fmtDate(p.expiry)} <span className="market-sub">Δ {p.delta}</span></td>
                  <td>{p.contracts}</td>
                  <td>{money(p.capital)}</td>
                  <td className="positive">{money(p.income)}</td>
                  <td>{p.cushion_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {plan.skipped_expensive.length > 0 && (
            <p className="market-sub">Too expensive for the per-stock cap: {plan.skipped_expensive.map(s => s.ticker).join(', ')}</p>
          )}
          <p className="ivrank-note">{plan.note}</p>
        </>
      ))}
    </div>
  );
}

export default function WheelIdeas({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [cash, setCash] = useState('');
  const [safeOnly, setSafeOnly] = useState(true);
  const [shortDated, setShortDated] = useState(false);
  const [preset, setPreset] = useState(null);
  const manage = p => {
    setPreset(p);
    setTimeout(() => document.getElementById('wheel-manager')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  };

  useEffect(() => {
    let timer;
    let active = true;
    const load = () => fetchWheelIdeas(shortDated).then(d => {
      if (!active) return;
      setData(d);
      if (d.status === 'building' || d.status === 'running') timer = setTimeout(load, 15_000);
    }).catch(e => { if (active) setError(e.message); });
    load();
    return () => { active = false; clearTimeout(timer); };
  }, [shortDated]);

  const loading = !error && (!data || data.status === 'building');
  const rows = (data?.rows || [])
    .filter(c => !cash || c.capital <= Number(cash))
    .filter(c => c.earnings_date && c.liquidity !== 'thin')
    .filter(c => !safeOnly || !c.earnings_before_expiry);
  const fits = usePortfolioFit(rows.slice(0, 12).map(c => ({ ticker: c.ticker, cash_needed: c.capital })));

  return (
    <>
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🎡 Wheel candidates</h3>
        {data?.updated_at && <span className="market-sub">Updated {new Date(data.updated_at).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</span>}
      </div>
      <p className="structures-intro">
        The wheel: sell a cash-secured put on a stock you'd happily own. If it expires, keep the premium and repeat; if
        you're assigned, sell covered calls above your cost until the shares are called away. We screen the S&P 500 and Nasdaq-100 for
        steady uptrends near their highs with calm daily ranges{data?.screened != null && ` (${data.quality_pool} of ${data.screened} pass)`}, then pick a
        ~{Math.round((data?.target_delta ?? .15) * 100)}-delta put {shortDated ? '7–20' : '21–50'} days out on the most liquid strike — before earnings where
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
        <label className="prepost-toggle">
          <input type="checkbox" checked={shortDated} onChange={e => {
            setData(null); setError(null); setShortDated(e.target.checked);
          }} />
          Short-dated: 7–20 days
        </label>
      </div>
      {shortDated && <p className="income-warning" role="status">Short-dated options carry higher near-expiry gamma risk and less time to adjust. Annualized premiums are not expected annual returns.</p>}
      {error && <p className="error-text">{error}</p>}
      {loading && <p className="loading-text">Screening wheel candidates for {shortDated ? '7–20' : '21–50'} days to expiry…</p>}
      {!loading && !error && (rows.length ? (
        <div className="structures-grid income-grid">
          {rows.slice(0, 12).map(c => <WheelCard key={c.ticker} c={c} onSelect={onSelect} onManage={manage} fit={fits[c.ticker]} />)}
        </div>
      ) : (
        <p className="empty-state">No candidates match{cash ? ` ${money(Number(cash))} of cash` : ''} right now.</p>
      ))}
      <ul className="ivrank-help">
        <li>Take profit at ~50% of the premium and sell the next put — don't wait for the last few cents.</li>
        <li>If the stock drops through the strike, roll down and out for a credit, or accept the shares — use <b>Manage a wheel position</b> below.</li>
        <li>Once assigned, sell covered calls at or above your cost-if-assigned price so a call-away is never a loss.</li>
        <li>Keep any one name to a small slice of your account — assignment ties up the full cash amount.</li>
      </ul>
      <p className="ivrank-note">Quotes refresh every few hours during market hours. Probabilities are model estimates, not guarantees. Not financial advice.</p>
    </div>
    <WheelPlan key={String(shortDated)} onSelect={onSelect} shortDated={shortDated} />
    <WheelAsk onManage={manage} onSelect={onSelect} />
    <WheelManager preset={preset} />
    </>
  );
}
