import { useState, useEffect } from 'react';
import { fetchIncomeIdeas } from '../api/stockApi';
import PricedAt from './PricedAt';
import Tip from './Tip';
import RollRepair from './RollRepair';
import { AssignmentShare, LimitHint, PostEarningsBadge, useAccountValue } from './TradeSizing';

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
  const failed = (i.checks || []).filter(c => !c.ok).map(c => c.text);
  return s ? <span className={`safety-badge ${s.cls}`} title={failed.length ? `Failed: ${failed.join('; ')}` : 'All checks pass'}>{s.text}</span> : null;
}

const LIQ = {
  good: { text: 'Liquid', cls: 'positive' },
  ok: { text: 'OK liquidity', cls: '' },
  thin: { text: 'Execution caution', cls: 'rvol-warm' },
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

function assessIncomeIdea(idea, { mode, cash, risk, shares, earnings, expiry, noEarnings = false }) {
  const spread = mode === 'pcs' || mode === 'ic';
  const quoteValid = spread
    ? [idea.credit, idea.natural_credit, idea.width].every(Number.isFinite)
      && idea.natural_credit > 0 && idea.natural_credit <= idea.credit && idea.credit < idea.width
    : Number.isFinite(idea.bid) && Number.isFinite(idea.ask) && idea.bid > 0 && idea.ask >= idea.bid;
  const blocked = [];
  const warnings = [];
  let riskBlocks = 0;
  if (!quoteValid) blocked.push('Valid two-sided quote unavailable; sizing disabled.');
  if (!earnings && !noEarnings) blocked.push('Earnings date unavailable; sizing disabled.');
  else if (earnings && (!expiry || earnings <= expiry)) blocked.push('Earnings occur on or before expiry; sizing disabled.');
  riskBlocks = blocked.length;

  const available = Number(mode === 'cc' ? shares : mode === 'csp' ? cash : risk);
  const required = mode === 'cc' ? 100 : mode === 'csp' ? idea.capital_required : idea.max_loss;
  const affordable = Number.isFinite(available) && Number.isFinite(required) && required > 0 && available >= required;
  const resource = mode === 'cc' ? 'Shares' : mode === 'csp' ? 'Cash' : 'Risk budget';
  if (!affordable) {
    blocked.push(!Number.isFinite(required) || required <= 0
      ? 'Capital requirement unavailable; sizing disabled.'
      : `${resource} needed: ${mode === 'cc' ? required : money(required)} per contract; sizing disabled.`);
  }
  if (!spread && quoteValid) {
    const percent = (idea.ask - idea.bid) / ((idea.ask + idea.bid) / 2) * 100;
    if (percent > 20) warnings.push(`Wide spread: ${percent.toFixed(1)}% exceeds the 20% guideline.`);
  }
  if (!Number.isFinite(idea.open_interest)) warnings.push('Open interest unavailable.');
  else if (idea.open_interest < 100) warnings.push(`Low open interest: ${idea.open_interest}, below the 100-contract guideline.`);
  if (idea.liquidity === 'thin' && warnings.length === 0) warnings.push('Execution caution: wide bid/ask spread on one or more legs.');
  else if (!['good', 'ok', 'thin'].includes(idea.liquidity)) warnings.push('Liquidity assessment unavailable.');

  return {
    blocked, warnings, quoteValid,
    contracts: blocked.length ? 0 : Math.floor(available / required),
    budgetMessage: affordable ? `${resource} sufficient${warnings.length ? '; execution caution' : ''}.` : null,
    // Not having entered enough cash/shares/budget limits sizing, but says nothing about the trade's risk.
    safety: idea.safety === 'risky' ? 'risky' : riskBlocks || warnings.length ? 'caution' : idea.safety,
  };
}

export function eligibleIncomeIdeas(ideas, settings) {
  return ideas.filter(idea => assessIncomeIdea(idea, settings).contracts > 0);
}

function CandidateStatus({ assessment }) {
  return (
    <div role="status">
      {assessment.budgetMessage && <p className="structure-notes">{assessment.budgetMessage}</p>}
      {[...assessment.blocked, ...assessment.warnings].map(message => (
        <p key={message} className="rvol-warm">{message}</p>
      ))}
    </div>
  );
}

function SpreadCard({ i, mode, expiry, assessment, account }) {
  const n = assessment.contracts;
  const legs = mode === 'ic'
    ? [['BUY', i.put_long, 'put'], ['SELL', i.put_short, 'put'], ['SELL', i.call_short, 'call'], ['BUY', i.call_long, 'call']]
    : [['SELL', i.short_strike, 'put'], ['BUY', i.long_strike, 'put']];
  const liq = LIQ[i.liquidity] || { text: 'Liquidity unavailable', cls: 'rvol-warm' };
  return (
    <div className={`structure-card safety-${assessment.safety}`}>
      <div className="structure-title">
        {i.label} <span className="income-delta">Δ {i.delta.toFixed(2)}</span> <Tip term="delta" /> <SafetyBadge i={{ ...i, safety: assessment.safety }} />
      </div>
      <CandidateStatus assessment={assessment} />
      <div className="structure-legs">
        {legs.map(([action, strike, kind]) => (
          <div key={action + strike + kind} className={`structure-leg ${action === 'BUY' ? 'leg-buy' : 'leg-sell'}`}>
            {n > 0 ? `${action} ${n} ×` : action === 'BUY' ? 'Long' : 'Short'} ${strike} {kind} · {fmtDate(expiry)}
          </div>
        ))}
      </div>
      <div className="structure-stats">
        <div><span>Credit / contract</span><strong className="positive">{money(i.premium)}</strong></div>
        <div><span>Max loss / contract</span><strong className="negative">{money(i.max_loss)}</strong></div>
        {n > 0 && <div><span>Total credit · risk</span><strong>{money(i.premium * n)} · {money(i.max_loss * n)}</strong></div>}
        <div><span>Return on risk <Tip term="return_on_risk" /></span><strong>{i.return_on_risk_pct}%</strong></div>
        <div><span>Chance of profit <Tip term="pop" /></span><strong>~{i.prob_profit_pct}% <small>(full credit ~{i.prob_max_profit_pct}%)</small></strong></div>
        {mode === 'ic'
          ? <div><span>Profit zone at expiry</span><strong>${i.breakeven_low} – ${i.breakeven_high}</strong></div>
          : <div><span>Breakeven</span><strong>${i.breakeven} <small>(−{i.breakeven_pct}%)</small></strong></div>}
      </div>
      <Checks i={i} />
      <AssignmentShare amount={i.max_loss * Math.max(n, 1)} account={account} label={n > 1 ? `Max loss on ${n}` : 'Max loss'} />
      <LimitHint bid={i.natural_credit} ask={2 * i.credit - i.natural_credit} what="credit" />
      <p className="structure-notes">
        Midpoint ${i.credit} net credit (natural ${i.natural_credit} <Tip term="natural_credit" />) · ${i.width} wide · OI {i.open_interest?.toLocaleString() ?? 'Unavailable'} ·{' '}
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
  const account = useAccountValue();

  useEffect(() => { setExpiry(null); setData(null); }, [ticker]);

  useEffect(() => {
    if (!ticker) return;
    let active = true;
    setLoading(true);
    setError(null);
    fetchIncomeIdeas(ticker, expiry)
      .then(value => { if (active) setData(value); })
      .catch(e => { if (active) setError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [ticker, expiry]);

  const ideas = data?.[MODES[mode].key] || [];
  const spread = mode === 'pcs' || mode === 'ic';
  const er = data?.earnings_date;
  const erDays = er ? Math.round((new Date(er + 'T12:00:00') - new Date()) / 86400000) : null;
  const erAhead = erDays != null && erDays >= 0;
  const spansEr = exp => erAhead && exp >= er;
  const safeExp = erAhead ? data.expirations.filter(e => e.date < er).at(-1) : null;
  const settings = { mode, cash, risk, shares, earnings: er, expiry: data?.expiry, noEarnings: !!data?.no_earnings_expected };

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
                  {fmtDate(e.date)} ({e.dte === 0 ? '0DTE — today' : `${e.dte}d`}){e.monthly ? ' · monthly' : ''}{spansEr(e.date) ? ' · ⚠️ earnings' : ''}
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
              <input type="number" className="tool-input" min={0} step={100} value={risk} placeholder="Enter risk budget"
                onChange={e => setRisk(e.target.value)} />
            </label>
          ) : (
            <label>
              Cash available ($)
              <input type="number" className="tool-input" min={0} step={1000} value={cash} placeholder="Enter cash"
                onChange={e => setCash(e.target.value)} />
            </label>
          )}
          <span className="structures-meta">
            Stock ${data.spot}
            {data.expected_move && ` · expected move ±$${data.expected_move.move} ($${data.expected_move.low}–$${data.expected_move.high})`}
            {data.expected_move && <> <Tip term="expected_move" /></>}
            <PricedAt asOf={data.as_of} />
          </span>
          <PostEarningsBadge daysSince={data.days_since_earnings} timing={data.last_earnings_timing} />
        </div>
      )}
      {data && <p className="market-sub income-legend">Labels: 🛡 = every check on the card is ✓. <b>Caution</b> = exactly one ⚠ (often a strike inside the
        expected move, where an ordinary move for this stock could reach it). <b>Risky</b> = two or more. Thin quotes, low open interest or a missing
        earnings date also show Caution. Hover a badge to see what failed.</p>}

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
      {data && !er && data.no_earnings_expected && (
        <p className="income-er-clear">✓ ETF / fund: no company earnings. Macro events (Fed, CPI, jobs) can still move it.</p>
      )}
      {loading && <p className="loading-text">Loading option chain…</p>}
      {error && <p className="empty-state">{error}</p>}
      {data && !loading && ideas.length === 0 && <p className="empty-state" role="status">No candidates returned for this strategy and expiry.</p>}

      {data && !loading && ideas.length > 0 && (
        <div className="structures-grid income-grid">
          {ideas.map(i => {
            const assessment = assessIncomeIdea(i, settings);
            if (spread) {
              return <SpreadCard key={i.label} i={i} mode={mode} expiry={data.expiry} assessment={assessment} account={account} />;
            }
            const contracts = assessment.contracts;
            const liq = LIQ[i.liquidity] || { text: 'Liquidity unavailable', cls: 'rvol-warm' };
            return (
              <div key={i.strike} className={`structure-card safety-${assessment.safety}`}>
                <div className="structure-title">
                  {i.label} <span className="income-delta">Δ {Math.abs(i.delta).toFixed(2)}</span> <SafetyBadge i={{ ...i, safety: assessment.safety }} />
                </div>
                <CandidateStatus assessment={assessment} />
                <div className="structure-legs">
                  <div className="structure-leg leg-sell">
                    {contracts > 0 ? `SELL ${contracts} ×` : 'Short'} ${i.strike} {mode === 'cc' ? 'call' : 'put'} · {fmtDate(data.expiry)}
                  </div>
                </div>
                <div className="structure-stats">
                  <div><span>Premium / contract</span><strong className="positive">{money(i.premium)}</strong></div>
                  {contracts > 0 && <div><span>Total premium</span><strong className="positive">{money(i.premium * contracts)}</strong></div>}
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
                {mode === 'csp' && <AssignmentShare amount={i.capital_required * Math.max(contracts, 1)} account={account}
                  label={contracts > 1 ? `If all ${contracts} are assigned` : 'If assigned'} />}
                <LimitHint bid={i.bid} ask={i.ask} />
                <p className="structure-notes">
                  Midpoint ${i.mid} (bid {i.bid == null ? 'Unavailable' : `$${i.bid}`} / ask {i.ask == null ? 'Unavailable' : `$${i.ask}`}) · OI {i.open_interest?.toLocaleString() ?? 'Unavailable'} ·{' '}
                  <span className={liq.cls}>{liq.text}</span>
                </p>
              </div>
            );
          })}
        </div>
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
