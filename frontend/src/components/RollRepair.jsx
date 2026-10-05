import { useState, useEffect } from 'react';
import { fetchRollIdeas } from '../api/stockApi';
import Tip from './Tip';

const STRATS = {
  cc: { label: 'Covered call', kind: 'call', away: 'up' },
  csp: { label: 'Cash-secured put', kind: 'put', away: 'down' },
  pcs: { label: 'Put credit spread', kind: 'put', away: 'down' },
};
const LIQ = { good: ['Liquid', 'positive'], ok: ['OK liquidity', ''], thin: ['Thin', 'negative'] };

const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const usd = v => `${Math.round(v) < 0 ? '−' : ''}$${Math.abs(Math.round(v)).toLocaleString()}`;

function RollCard({ r, strat, data }) {
  const s = STRATS[strat];
  const [liqText, liqCls] = LIQ[r.liquidity];
  const legs = strat === 'pcs'
    ? `Close $${data.short_strike}/$${data.long_strike} ${fmtDate(data.expiry)} → open $${r.short_strike}/$${r.long_strike} ${fmtDate(r.expiry)}`
    : `Buy back $${data.short_strike} ${s.kind} ${fmtDate(data.expiry)} → sell $${r.short_strike} ${s.kind} ${fmtDate(r.expiry)}`;
  return (
    <div className={`roll-card ${r.best ? 'structure-best' : ''}`}>
      <div className="roll-title">
        {r.type === 'out' ? 'Roll out' : `Roll out & ${s.away}`} → {fmtDate(r.expiry)} <small>(+{r.added_days}d)</small>
        {r.best && <span className="structure-best-badge">Passes roll filters</span>}
      </div>
      <div className="roll-legs">
        {legs}
      </div>
      <div className="roll-stats">
        <span>Midpoint estimate: {usd(r.net_credit)}</span>
        <span className={r.net_credit_natural >= 0 ? 'positive' : 'negative'}>Natural after estimated fees: {r.net_credit_natural == null ? 'unavailable' : usd(r.net_credit_natural)}</span>
        {r.strike_change > 0 && <span>strike {s.away} ${r.strike_change}</span>}
        <span>Δ {r.delta} <Tip term="delta" /></span>
        <span>~{r.prob_otm_pct}% expires OTM</span>
        <span className={liqCls}>{liqText}</span>
        {r.spans_earnings && <span className="negative">⚠️ holds through earnings</span>}
      </div>
      {r.outcome && <div className="roll-outcome">{r.outcome}</div>}
    </div>
  );
}

export default function RollRepair({ ticker, mode, expirations, initial, standalone = false }) {
  const [strategy, setStrategy] = useState(initial?.strategy || (STRATS[mode] ? mode : 'pcs'));
  const [expiry, setExpiry] = useState(initial?.expiry || '');
  const [shortStrike, setShortStrike] = useState(initial?.shortStrike ?? '');
  const [longStrike, setLongStrike] = useState('');
  const [credit, setCredit] = useState(initial?.credit ?? '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { if (STRATS[mode]) setStrategy(mode); }, [mode]);
  useEffect(() => { if (!initial) { setData(null); setError(null); } }, [ticker, initial]);

  const ready = expiry && Number(shortStrike) > 0 && (strategy !== 'pcs' || Number(longStrike) > 0);
  const run = async () => {
    setLoading(true); setError(null); setData(null);
    try {
      setData(await fetchRollIdeas(ticker, { strategy, expiry, shortStrike, longStrike, credit }));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  // Prefilled from a portfolio position: check it straight away
  useEffect(() => { if (initial) run(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const expiryOptions = expirations?.length ? expirations
    : expiry ? [{ date: expiry, dte: Math.max(0, Math.round((new Date(expiry + 'T16:00:00') - new Date()) / 86400000)) }] : [];
  const st = data?.status;
  const kind = STRATS[strategy].kind;
  const Wrap = standalone ? 'div' : 'details';
  return (
    <Wrap className={standalone ? 'roll-repair-standalone' : 'setup-guide roll-repair'}>
      {!standalone && <summary>🔧 Position being tested? Roll / repair it</summary>}
      <p className="structures-intro">
        Enter a short option you already hold. We find rolls to a later expiry that pay a <b>net credit</b> — ideally
        moving the strike away from the stock — plus the alternatives if no good roll exists.
      </p>
      <div className="income-controls">
        <label>Position
          <select className="candle-select" value={strategy} onChange={e => setStrategy(e.target.value)}>
            {Object.entries(STRATS).map(([k, s]) => <option key={k} value={k}>{s.label}</option>)}
          </select>
        </label>
        <label>Expiry
          {expiryOptions.length ? (
            <select className="candle-select" value={expiry} onChange={e => setExpiry(e.target.value)}>
              <option value="">Select…</option>
              {expiryOptions.map(e => <option key={e.date} value={e.date}>{fmtDate(e.date)} ({e.dte}d)</option>)}
            </select>
          ) : (
            <input type="date" className="tool-input" value={expiry} onChange={e => setExpiry(e.target.value)} />
          )}
        </label>
        <label>Short {kind} strike
          <input type="number" className="tool-input" value={shortStrike} min={0} step={0.5}
            onChange={e => setShortStrike(e.target.value)} />
        </label>
        {strategy === 'pcs' && (
          <label>Long put strike
            <input type="number" className="tool-input" value={longStrike} min={0} step={0.5}
              onChange={e => setLongStrike(e.target.value)} />
          </label>
        )}
        <label>Credit received / share
          <input type="number" className="tool-input" value={credit} min={0} step={0.05} placeholder="optional"
            onChange={e => setCredit(e.target.value)} />
        </label>
        <button className="btn-primary btn-sm" onClick={run} disabled={!ready || loading}>
          {loading ? 'Checking…' : 'Find rolls'}
        </button>
      </div>

      {error && <p className="empty-state">{error}</p>}

      {st && (
        <div className={`income-warning ${st.tested ? 'income-er' : ''}`}>
          <strong>
            Stock ${data.spot} · short ${data.short_strike} {kind} is{' '}
            {st.itm ? `in the money by ${Math.abs(st.cushion_pct)}%` : `${st.cushion_pct}% out of the money`}
            {st.delta != null && ` · Δ ${st.delta}`} · {st.dte}d left
          </strong>
          <div>
            Cost to close now ~{usd(st.close_cost)} (natural {usd(st.close_cost_natural)})
            {st.pnl != null && <> · P/L if closed <span className={st.pnl >= 0 ? 'positive' : 'negative'}>{usd(st.pnl)}</span></>}
          </div>
          {data.verdict && <div>{data.verdict}</div>}
        </div>
      )}

      {data?.rolls?.length > 0 && (
        <div className="roll-list">
          {data.rolls.map(r => <RollCard key={r.expiry + r.short_strike} r={r} strat={strategy} data={data} />)}
        </div>
      )}

      {data?.alternatives?.length > 0 && (
        <>
          <h4 className="sub-chart-title">If you don't roll</h4>
          <ul className="ivrank-help">
            {data.alternatives.map(a => <li key={a.title}><b>{a.title}</b> — {a.text}</li>)}
          </ul>
        </>
      )}
      {data && (
        <>
          <h4 className="sub-chart-title">Rolling rules</h4>
          <ul className="ivrank-help">{data.rules.map(r => <li key={r}>{r}</li>)}</ul>
        </>
      )}
      {loading && standalone && <p className="loading-text">Checking rolls…</p>}
    </Wrap>
  );
}
