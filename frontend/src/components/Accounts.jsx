import { useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { fetchAccounts, saveCash, fetchNavHistory, recordNavSnapshot, fetchCorporateActions, applySplit, recordSpinoff, recordMerger } from '../api/stockApi';

const money = (value) => (value == null ? '—' : `${Number(value) < 0 ? '-' : ''}$${Math.abs(Number(value)).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const ACCOUNT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 ._&'()-]{0,39}$/;

export function AccountBar({ account, onChange, version, onCashSaved, compact = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [cash, setCash] = useState('');
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [extra, setExtra] = useState([]);

  useEffect(() => {
    let active = true;
    fetchAccounts().then(result => { if (active) { setData(result); setError(null); } })
      .catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [version]);

  const accounts = [...(data?.accounts || [])];
  extra.filter(name => !accounts.some(a => a.name === name))
    .forEach(name => accounts.push({ name, cash: null, put_collateral: 0, free_cash: null }));
  const selected = accounts.find(a => a.name === account);
  const shown = selected ? [selected] : accounts;

  useEffect(() => { setCash(selected?.cash ?? ''); }, [selected?.name, selected?.cash]);

  const addAccount = () => {
    const name = newName.trim();
    if (!ACCOUNT_PATTERN.test(name)) { setError('Account names use letters, numbers, spaces and . _ & \' ( ) - (up to 40).'); return; }
    setExtra(list => [...list, name]);
    setNewName('');
    setError(null);
    onChange(name);
  };

  const submitCash = async () => {
    const value = Number(cash);
    if (cash === '' || !Number.isFinite(value)) { setError('Enter the cash balance as a number.'); return; }
    setBusy(true);
    try {
      await saveCash(account, value);
      setData(await fetchAccounts());
      setError(null);
      onCashSaved?.();
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  if (compact) {
    return (
      <section className="account-bar-compact" aria-label="Brokerage accounts">
        <label htmlFor="account-select">Account</label>
        <select id="account-select" className="tool-input" value={account} onChange={e => onChange(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.map(a => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <span className="market-sub">Cash and new accounts are managed under Holdings.</span>
      </section>
    );
  }

  return (
    <section className="card account-bar" aria-label="Brokerage accounts">
      <div className="account-bar-row">
        <label htmlFor="account-select">Account</label>
        <select id="account-select" className="tool-input" value={account} onChange={e => onChange(e.target.value)}>
          <option value="">All accounts</option>
          {accounts.map(a => <option key={a.name} value={a.name}>{a.name}</option>)}
        </select>
        <input className="tool-input" aria-label="New account name" placeholder="New account (e.g. IRA)" value={newName} maxLength={40}
          onChange={e => setNewName(e.target.value)} onKeyDown={e => e.key === 'Enter' && addAccount()} />
        <button className="btn-secondary btn-sm" onClick={addAccount} disabled={!newName.trim()}>Add</button>
        {account && <>
          <label htmlFor="account-cash">Cash</label>
          <input id="account-cash" className="tool-input" type="number" step="any" value={cash} onChange={e => setCash(e.target.value)} />
          <button className="btn-primary btn-sm" onClick={submitCash} disabled={busy}>Save cash</button>
        </>}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {!data && !error && <div className="skeleton skeleton-line" aria-hidden="true" />}
      {data && (
        <div className="table-scroll"><table className="market-table account-table">
          <thead><tr><th>Account</th><th>Cash</th><th title="Strike × 100 × contracts for open short puts">Put collateral</th><th>Free cash</th><th>Cash updated</th></tr></thead>
          <tbody>{shown.map(a => (
            <tr key={a.name}>
              <td>{a.name}</td><td>{money(a.cash)}</td><td>{money(a.put_collateral)}</td>
              <td className={a.free_cash != null && a.free_cash < 0 ? 'negative' : ''}>{a.cash == null
                ? <button className="link-btn" onClick={() => onChange(a.name)} title={`Select ${a.name} to enter its cash balance`}>Enter cash</button>
                : money(a.free_cash)}</td>
              <td>{a.cash_updated_at ? new Date(a.cash_updated_at).toLocaleString() : '—'}</td>
            </tr>))}
          </tbody>
        </table></div>
      )}
      {!account && <p className="market-sub">Pick an account to enter its cash. New trades go into the selected account (All accounts uses Default).</p>}
    </section>
  );
}

export function NavHistory({ account }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setData(null);
    fetchNavHistory(account).then(result => active && setData(result)).catch(e => active && setError(e.message));
    return () => { active = false; };
  }, [account]);

  const record = async () => {
    setBusy(true); setMsg(null);
    try {
      const result = await recordNavSnapshot();
      const incomplete = result.snapshots.filter(s => !s.complete).map(s => s.account);
      setMsg(incomplete.length ? `Recorded. Incomplete (missing quotes or cash): ${incomplete.join(', ')}` : 'Recorded today\'s account value.');
      setData(await fetchNavHistory(account));
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const points = (data?.series || []).filter(p => p.nav != null);
  return (
    <section className="card nav-history" aria-label="Account value history">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>Account value {account ? `· ${account}` : '· all accounts'}</h3>
        <button className="btn-secondary btn-sm" onClick={record} disabled={busy}>Record value now</button>
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
      {msg && <p className="notif-msg">{msg}</p>}
      {!data && !error && <div className="skeleton skeleton-chart" aria-hidden="true" />}
      {data && (points.length < 2 ? (
        <p className="empty-state">Account value is recorded each trading day near the close (cash + stocks + option marks). Enter each account's cash and check back after two snapshots.</p>
      ) : <>
        <div className="metrics-grid">
          <div className="metric"><span className="metric-label">Latest value</span><span className="metric-value">{money(points.at(-1).nav)}</span></div>
          <div className="metric"><span className="metric-label">{data.flow_adjusted ? 'Time-weighted return' : 'Value change (not flow-adjusted)'}</span>
            <span className={`metric-value ${data.return_pct >= 0 ? 'positive' : 'negative'}`}>{data.return_pct == null ? '—' : `${data.return_pct}%`}</span></div>
          <div className="metric"><span className="metric-label">Max drawdown</span><span className="metric-value negative">{data.max_drawdown_pct == null ? '—' : `${data.max_drawdown_pct}%`}</span></div>
        </div>
        <div style={{ height: 220 }}>
          <ResponsiveContainer>
            <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `$${Math.round(v / 1000)}k`} width={56} />
              <Tooltip formatter={v => money(v)} />
              <Line type="monotone" dataKey="nav" name="Account value" stroke="var(--accent)" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </>)}
      {data && <p className="market-sub">{data.note} Days with a missing quote or cash balance are left out rather than valued at zero.</p>}
    </section>
  );
}

const EMPTY_ACTION = { kind: 'spinoff', ticker: '', new_ticker: '', date: '', ratio: '', basis_pct: '', cash: '' };

function describeAction(kind, r) {
  const options = r.options_unadjusted ? ` ${r.options_unadjusted} open ${r.ticker} option(s) were not changed; edit or close them manually.` : '';
  if (kind === 'spinoff') return `${r.ticker}: moved ${money(r.basis_moved)} of cost basis to ${r.new_ticker} across ${r.lots} lot(s).${options}`;
  const capped = r.lots_cash_above_basis ? ` Cash exceeded the cost basis on ${r.lots_cash_above_basis} lot(s); that gain is not recorded.` : '';
  return r.new_ticker
    ? `${r.ticker}: converted ${r.lots} lot(s) into ${r.new_ticker}.${capped}${options}`
    : `${r.ticker}: closed ${r.lots} lot(s) for cash, realized ${money(r.realized_pnl)}.${options}`;
}

export function CorporateActions({ version, onApplied }) {
  const [splits, setSplits] = useState([]);
  const [stale, setStale] = useState([]);
  const [applied, setApplied] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(null);
  const [form, setForm] = useState(EMPTY_ACTION);
  const [open, setOpen] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    fetchCorporateActions().then(r => {
      if (!active) return;
      setSplits(r.splits || []); setStale(r.stale || []); setApplied(r.applied || []);
    }).catch(() => {});
    return () => { active = false; };
  }, [version, reload]);

  const apply = async (split) => {
    const optionsNote = split.options && !split.options_adjustable
      ? ` ${split.options} option position(s) become adjusted contracts and will NOT be changed; edit them manually.` : '';
    if (!window.confirm(`Apply the ${split.ticker} ${split.label} split from ${split.split_date}? Shares and cost per share on ${split.lots} lot(s) acquired before that date will be adjusted.${optionsNote}`)) return;
    setBusy(split.ticker + split.split_date);
    try {
      const result = await applySplit(split.ticker, split.split_date);
      setMsg(`${result.ticker}: adjusted ${result.lots} lot(s) and ${result.options} option(s)${result.options_skipped ? `; ${result.options_skipped} adjusted contract(s) need manual edits` : ''}.`);
      setSplits(list => list.filter(s => s !== split));
      onApplied?.();
    } catch (e) { setMsg(e.message); }
    setBusy(null);
  };

  const change = (e) => setForm(f => ({ ...f, [e.target.name]: e.target.value }));
  const startMerger = (ticker) => { setForm({ ...EMPTY_ACTION, kind: 'merger', ticker }); setOpen(true); };

  const submit = async (e) => {
    e.preventDefault();
    const ticker = form.ticker.trim().toUpperCase();
    const next = form.new_ticker.trim().toUpperCase();
    const spinoff = form.kind === 'spinoff';
    const body = spinoff
      ? { ticker, new_ticker: next, action_date: form.date, ratio: Number(form.ratio), basis_pct: Number(form.basis_pct || 0) }
      : { ticker, action_date: form.date, ratio: Number(form.ratio || 0), cash_per_share: Number(form.cash || 0), ...(next ? { new_ticker: next } : {}) };
    const question = spinoff
      ? `Record the ${ticker} spin-off of ${next} on ${body.action_date}? Each lot held before that date gets ${body.ratio} ${next} share(s) per share and ${body.basis_pct}% of its cost basis moves to the new lot.`
      : `Record the ${ticker} merger on ${body.action_date}? ${body.ratio ? `Each lot becomes ${body.ratio} ${next} share(s) per share` : 'Every lot is closed'}${body.cash_per_share ? ` with $${body.cash_per_share} cash per share` : ''}.`;
    if (!window.confirm(`${question} This cannot be undone automatically.`)) return;
    setBusy('form'); setMsg(null);
    try {
      const result = spinoff ? await recordSpinoff(body) : await recordMerger(body);
      setMsg(describeAction(form.kind, result));
      setForm(EMPTY_ACTION);
      setReload(n => n + 1);
      onApplied?.();
    } catch (err) { setMsg(err.message); }
    setBusy(null);
  };

  const today = new Date().toLocaleDateString('en-CA');
  const spinoff = form.kind === 'spinoff';
  return (
    <>
      {(splits.length > 0 || stale.length > 0) && (
        <div className="split-notice" role="status">
          {splits.map(s => (
            <p key={s.ticker + s.split_date}>
              <strong>{s.ticker}</strong> had a {s.label} split on {s.split_date} affecting {s.lots} lot(s){s.options ? ` and ${s.options} option(s)` : ''} recorded before it.{' '}
              <button className="btn-primary btn-sm" disabled={busy === s.ticker + s.split_date} onClick={() => apply(s)}>Apply adjustment</button>
            </p>
          ))}
          {stale.map(s => (
            <p key={s.ticker}>
              <strong>{s.ticker}</strong> has had no quotes {s.last_quote ? `since ${s.last_quote}` : 'for at least a month'}; it may have been acquired or delisted.{' '}
              <button className="btn-secondary btn-sm" onClick={() => startMerger(s.ticker)}>Record merger</button>
            </p>
          ))}
        </div>
      )}
      {msg && <p className="notif-msg" role="status">{msg}</p>}
      <details className="card corporate-actions" open={open} onToggle={e => setOpen(e.currentTarget.open)}>
        <summary>Record a spin-off or merger</summary>
        <form className="accounting-form" onSubmit={submit} aria-label="Record corporate action">
          <label>Event<select name="kind" value={form.kind} onChange={change}>
            <option value="spinoff">Spin-off</option><option value="merger">Merger / acquisition</option>
          </select></label>
          <label>Ticker you hold<input name="ticker" required maxLength={12} value={form.ticker} onChange={change} /></label>
          <label>{spinoff ? 'Ex-date' : 'Closing date'}<input name="date" type="date" required max={today} value={form.date} onChange={change} /></label>
          {spinoff ? <>
            <label>New company ticker<input name="new_ticker" required maxLength={12} value={form.new_ticker} onChange={change} /></label>
            <label>New shares per share held<input name="ratio" type="number" required min="0.000001" step="any" value={form.ratio} onChange={change} /></label>
            <label>% of cost basis to new company<input name="basis_pct" type="number" required min="0" max="99.99" step="any" value={form.basis_pct} onChange={change} /></label>
          </> : <>
            <label>Acquirer ticker (blank if all cash)<input name="new_ticker" maxLength={12} value={form.new_ticker} onChange={change} /></label>
            <label>Acquirer shares per share<input name="ratio" type="number" min="0" step="any" required={Boolean(form.new_ticker.trim())} value={form.ratio} onChange={change} /></label>
            <label>Cash per share ($)<input name="cash" type="number" min="0" step="any" value={form.cash} onChange={change} /></label>
          </>}
          <button className="btn-primary" type="submit" disabled={busy === 'form'}>Record</button>
        </form>
        <p className="market-sub">
          {spinoff
            ? 'Lots held before the ex-date get the new shares with the same acquisition date and account; the basis split comes from the company\u2019s tax basis notice (Form 8937). Cash in lieu of fractional shares is not recorded.'
            : 'All-cash deals close every lot at the cash price on the closing date. Stock deals convert lots in place (same acquisition date and account). In cash-and-stock deals the cash reduces cost basis; any gain it triggers is not recorded \u2014 check your 1099-B.'}
          {' '}Options on the old ticker are not changed.
        </p>
        {applied.length > 0 && (
          <div className="table-scroll"><table className="market-table" aria-label="Recorded corporate actions">
            <thead><tr><th>Date</th><th>Event</th><th>Ticker</th><th>Terms</th></tr></thead>
            <tbody>{applied.map(a => (
              <tr key={a.kind + a.ticker + a.action_date}>
                <td>{a.action_date}</td><td>{a.kind === 'spinoff' ? 'Spin-off' : 'Merger'}</td><td>{a.ticker}</td>
                <td>{a.kind === 'spinoff'
                  ? `${a.details.ratio} ${a.details.new_ticker} per share, ${a.details.basis_pct}% of basis`
                  : [a.details.ratio ? `${a.details.ratio} ${a.details.new_ticker}` : null, a.details.cash_per_share ? `$${a.details.cash_per_share} cash` : null].filter(Boolean).join(' + ')}</td>
              </tr>))}
            </tbody>
          </table></div>
        )}
      </details>
    </>
  );
}
