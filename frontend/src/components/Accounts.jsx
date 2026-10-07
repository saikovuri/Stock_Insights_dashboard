import { useEffect, useState } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { fetchAccounts, saveCash, fetchNavHistory, recordNavSnapshot, fetchCorporateActions, applySplit } from '../api/stockApi';

const money = (value) => (value == null ? '—' : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
const ACCOUNT_PATTERN = /^[A-Za-z0-9][A-Za-z0-9 ._&'()-]{0,39}$/;

export function AccountBar({ account, onChange, version, onCashSaved }) {
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
              <td className={a.free_cash != null && a.free_cash < 0 ? 'negative' : ''}>{a.cash == null ? 'Enter cash' : money(a.free_cash)}</td>
              <td>{a.cash_updated_at ? new Date(a.cash_updated_at).toLocaleString() : '—'}</td>
            </tr>))}
          </tbody>
        </table></div>
      )}
      {!account && <p className="market-sub">Choose an account to enter its cash balance. New lots and options are recorded in the selected account; "All accounts" uses Default.</p>}
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

export function SplitNotice({ version, onApplied }) {
  const [splits, setSplits] = useState([]);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    let active = true;
    fetchCorporateActions().then(r => active && setSplits(r.splits || [])).catch(() => {});
    return () => { active = false; };
  }, [version]);

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

  if (!splits.length && !msg) return null;
  return (
    <div className="split-notice" role="status">
      {splits.map(s => (
        <p key={s.ticker + s.split_date}>
          <strong>{s.ticker}</strong> had a {s.label} split on {s.split_date} affecting {s.lots} lot(s){s.options ? ` and ${s.options} option(s)` : ''} recorded before it.{' '}
          <button className="btn-primary btn-sm" disabled={busy === s.ticker + s.split_date} onClick={() => apply(s)}>Apply adjustment</button>
        </p>
      ))}
      {msg && <p className="notif-msg">{msg}</p>}
    </div>
  );
}
