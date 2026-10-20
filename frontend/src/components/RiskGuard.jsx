import { useEffect, useState } from 'react';
import { fetchRiskHeat, setRiskStop, checkTradeRisk } from '../api/stockApi';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

function StopEditor({ row, onSaved }) {
  const [value, setValue] = useState(row.stop ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const save = async stop => {
    setBusy(true); setError(null);
    try { await setRiskStop(row.ticker, stop, row.account); onSaved(); }
    catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  const valid = value !== '' && Number(value) > 0;
  return <form className="stop-editor" onSubmit={event => { event.preventDefault(); if (valid) save(Number(value)); }}>
    <input className="tool-input" type="number" min="0.01" step="any" placeholder="Stop $" aria-label={`Stop price for ${row.ticker}`}
      value={value} onChange={event => setValue(event.target.value)} />
    <button type="submit" className="btn-secondary btn-sm" disabled={busy || !valid}>Set</button>
    {row.stop != null && <button type="button" className="link-btn" disabled={busy} onClick={() => save(null)}>Clear</button>}
    {error && <span className="error-text" role="alert">{error}</span>}
  </form>;
}

/** Total open risk in trading accounts, the per-position breakdown with stops, and the circuit breaker status. */
export function RiskGuard({ version, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError(null);
    fetchRiskHeat().then(value => { if (active) setData(value); }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [version, revision]);
  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <p className="loading-text">Measuring open risk…</p>;
  const c = data.circuit;
  const pctClass = data.pct == null ? '' : data.over_limit ? 'negative' : data.limit_pct != null && data.pct > data.limit_pct * 0.8 ? 'rvol-warm' : 'positive';
  const refresh = () => { setRevision(value => value + 1); onChanged?.(); };
  return <div className="risk-guard">
    {c.active && <div className="income-warning" role="alert"><strong>🛑 Circuit breaker on until {c.until}</strong>
      <div>{c.reasons.join('; ')}. Your rule: no new trades until then. Manage what is open and review the losses in the Journal.</div></div>}
    <div className="doctor-stats" aria-label="Open risk summary">
      <div><span>Open risk</span><strong className={pctClass}>{usd(data.total_risk)}{data.pct != null && ` · ${data.pct}%`}</strong></div>
      <div><span>Your limit</span><strong>{data.limit_pct == null ? 'Not set' : `${data.limit_pct}%`}</strong></div>
      <div><span>Trading capital</span><strong>{usd(data.trading_value)}</strong></div>
      <div><span>This month (realized)</span><strong className={c.month_net < 0 ? 'negative' : c.month_net > 0 ? 'positive' : ''}>{usd(c.month_net)}
        {c.monthly_limit_pct != null && <small> · limit −{c.monthly_limit_pct}%</small>}</strong></div>
      <div><span>Losing streak</span><strong>{c.streak}{c.streak_limit ? <small> · cooldown at {c.streak_limit}</small> : ''}</strong></div>
    </div>
    {!data.roles_set && <p className="market-sub">All accounts count as trading. Mark long-term accounts in Portfolio → Long-term plan so their holdings don&apos;t count here.</p>}
    {data.cash_missing && <p className="market-sub">Some trading accounts have no cash entered, so trading capital (and the %) is understated.</p>}
    {data.no_stop > 0 && <p className="rvol-warm">{data.no_stop} stock position{data.no_stop === 1 ? ' has' : 's have'} no stop, so the whole position counts as at risk. Set a stop to define your exit.</p>}
    {data.positions.some(r => r.flags?.includes('stop_breached')) && <p className="negative">A stock is at or below its stop: your plan was to exit. Sell, or reset the stop deliberately.</p>}
    {data.unlimited > 0 && <p className="negative">{data.unlimited} uncovered short call{data.unlimited === 1 ? '' : 's'}: unlimited risk, not included in the total.</p>}
    {!data.positions.length ? <p className="empty-state">No open positions in trading accounts.</p> : <div className="table-scroll">
      <table className="market-table phone-cards" aria-label="Open risk by position">
        <thead><tr><th>Position</th><th>Risk</th><th>Of capital</th><th>How it&apos;s measured</th><th>Stop</th></tr></thead>
        <tbody>{data.positions.map(row => <tr key={`${row.kind}:${row.account}:${row.ticker}:${row.label}`}>
          <td><strong>{row.ticker}</strong> {row.label}{row.account !== 'Default' && <span className="account-badge">{row.account}</span>}</td>
          <td data-label="Risk" className={row.risk == null ? 'negative' : ''}>{row.risk == null ? 'Unlimited' : usd(row.risk)}</td>
          <td data-label="Of capital">{row.risk == null || !data.trading_value ? '—' : `${(row.risk / data.trading_value * 100).toFixed(1)}%`}</td>
          <td data-label="Measured">{row.basis}</td>
          <td data-label="Stop">{row.kind === 'stock' ? <StopEditor row={row} onSaved={refresh} /> : <span className="market-sub">—</span>}</td>
        </tr>)}</tbody>
      </table></div>}
    <p className="ivrank-note">{data.note} Set limits under My trading rules → Risk guard.</p>
  </div>;
}

/** Live pre-trade check: the trade's risk, open risk after it, and any rules it would break. Warns, never blocks. */
export function RiskCheck({ proposal, onResult }) {
  const [state, setState] = useState(null);
  const key = proposal ? JSON.stringify(proposal) : '';
  useEffect(() => {
    if (!key) { setState(null); onResult?.(null); return undefined; }
    let active = true;
    const timer = setTimeout(() => {
      checkTradeRisk(JSON.parse(key)).then(result => { if (active) { setState({ result }); onResult?.(result); } })
        .catch(reason => { if (active) { setState({ error: reason.message }); onResult?.(null); } });
    }, 400);
    return () => { active = false; clearTimeout(timer); };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!state) return null;
  if (state.error) return <p className="market-sub form-field-wide risk-check">Risk check unavailable: {state.error}</p>;
  const r = state.result;
  return <div className={`form-field-wide risk-check ${r.warnings.length ? 'risk-check-warn' : ''}`} role="status" aria-label="Risk check">
    <span>🛡 Risk: <strong>{r.risk == null ? 'unlimited' : usd(r.risk)}</strong>{r.basis ? ` (${r.basis})` : ''}
      {r.risk_pct != null && <> · <strong>{r.risk_pct}%</strong> of trading capital</>}
      {r.heat_pct_after != null && <> · open risk {r.heat_pct_before ?? 0}% → <strong>{r.heat_pct_after}%</strong></>}</span>
    {r.warnings.map(w => <span key={w.code} className="negative">⚠ {w.text}</span>)}
    {r.notes.map(n => <span key={n} className="market-sub">{n}</span>)}
  </div>;
}
