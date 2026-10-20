import { useEffect, useState } from 'react';
import { fetchInvestOverview, setAccountRole, saveInvestPlan, deleteInvestPlan, recordSweep } from '../api/stockApi';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const ROLE = { long_term: 'Long-term', trading: 'Trading' };
const EMPTY_PLAN = { account: '', monthly: '500', day: '1', goal: '', assumed_return_pct: '7', targets: [{ ticker: 'VOO', pct: '100' }] };

function Split({ split, onChanged, setMsg }) {
  const [busy, setBusy] = useState(null);
  const change = async (account, role) => {
    setBusy(account);
    try { await setAccountRole(account, role); onChanged(); } catch (error) { setMsg(error.message); }
    finally { setBusy(null); }
  };
  const total = split.total || 0;
  const longPct = total ? split.by_role.long_term / total * 100 : 0;
  return <section className="card" aria-label="Long-term vs trading">
    <h3>Long-term vs trading</h3>
    <p className="structures-intro">Mark each account as long-term (investments you hold for years, judged by allocation) or trading (short and
      medium-term trades, judged by risk rules). App accounts are labels, so one brokerage account can be split into two here.</p>
    <div className="split-bar" aria-hidden="true"><span className="split-long" style={{ width: `${longPct}%` }} /><span className="split-trading" style={{ width: `${100 - longPct}%` }} /></div>
    <div className="doctor-stats">
      <div><span>Long-term</span><strong>{usd(split.by_role.long_term)} {total > 0 && <small>({longPct.toFixed(0)}%)</small>}</strong></div>
      <div><span>Trading</span><strong>{usd(split.by_role.trading)} {split.trading_pct != null && <small>({split.trading_pct}%)</small>}</strong></div>
      <div><span>Target trading share</span><strong>{split.target_trading_pct == null ? 'Not set' : `${split.target_trading_pct}%`}</strong></div>
      <div><span>Realized this year</span><strong><span className={split.realized_this_year.trading < 0 ? 'negative' : 'positive'}>{usd(split.realized_this_year.trading)}</span> trading
        · <span className={split.realized_this_year.long_term < 0 ? 'negative' : 'positive'}>{usd(split.realized_this_year.long_term)}</span> long-term</strong></div>
    </div>
    {split.rebalance && <p className={split.drift_pct > 0 ? 'rvol-warm' : 'market-sub'}>Trading is {split.drift_pct > 0 ? 'above' : 'below'} your target by {Math.abs(split.drift_pct)} points:
      moving about <strong>{usd(split.rebalance.amount)}</strong> from {ROLE[split.rebalance.from].toLowerCase()} to {ROLE[split.rebalance.to].toLowerCase()} would put it back.</p>}
    {split.target_trading_pct == null && <p className="market-sub">Set a target trading share under Portfolio Risk → My trading rules (for example 20%).</p>}
    <div className="table-scroll"><table className="market-table phone-cards" aria-label="Account roles">
      <thead><tr><th>Account</th><th>Value</th><th>Cash</th><th>Role</th></tr></thead>
      <tbody>{split.accounts.map(a => <tr key={a.account}>
        <td><strong>{a.account}</strong></td>
        <td data-label="Value">{usd(a.value)}</td>
        <td data-label="Cash">{a.cash == null ? 'Not entered' : usd(a.cash)}</td>
        <td data-label="Role"><select className="tool-input" aria-label={`Role for ${a.account}`} value={a.role} disabled={busy === a.account}
          onChange={event => change(a.account, event.target.value)}>
          <option value="trading">Trading{a.role_set ? '' : ' (default)'}</option><option value="long_term">Long-term</option></select></td>
      </tr>)}</tbody>
    </table></div>
    <p className="ivrank-note">{split.note}</p>
  </section>;
}

function PlanEditor({ initial, accounts, onSaved, onCancel }) {
  const [form, setForm] = useState(initial);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const total = form.targets.reduce((sum, t) => sum + (Number(t.pct) || 0), 0);
  const valid = Number(form.monthly) > 0 && form.targets.length > 0 && form.targets.every(t => t.ticker.trim() && Number(t.pct) > 0)
    && Math.abs(total - 100) < 0.01;
  const set = key => event => setForm(value => ({ ...value, [key]: event.target.value }));
  const setTarget = (i, key, value) => setForm(f => ({ ...f, targets: f.targets.map((t, j) => (j === i ? { ...t, [key]: value } : t)) }));
  const save = async event => {
    event.preventDefault();
    if (!valid) return;
    setBusy(true); setError(null);
    try {
      await saveInvestPlan({ account: form.account || null, monthly: Number(form.monthly), day: Number(form.day) || 1,
        goal: form.goal === '' ? null : Number(form.goal), assumed_return_pct: Number(form.assumed_return_pct) || 7,
        targets: form.targets.map(t => ({ ticker: t.ticker.trim().toUpperCase(), pct: Number(t.pct) })) });
      onSaved();
    } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  return <form className="plan-editor" onSubmit={save} aria-label="Monthly investing plan">
    <div className="income-controls">
      <label>Account<select className="tool-input" value={form.account} onChange={set('account')}>
        {accounts.map(a => <option key={a.account} value={a.account === 'Default' ? '' : a.account}>{a.account} ({ROLE[a.role]})</option>)}</select></label>
      <label>Invest each month ($)<input className="tool-input" type="number" min="1" step="any" value={form.monthly} onChange={set('monthly')} /></label>
      <label>On day<input className="tool-input" type="number" min="1" max="28" step="1" value={form.day} onChange={set('day')} /></label>
      <label>Goal ($, optional)<input className="tool-input" type="number" min="1" step="any" value={form.goal} onChange={set('goal')} /></label>
      <label>Assumed yearly return (%)<input className="tool-input" type="number" min="0" max="20" step="0.5" value={form.assumed_return_pct} onChange={set('assumed_return_pct')} /></label>
    </div>
    <h4>Target mix <span className={Math.abs(total - 100) < 0.01 ? 'positive' : 'negative'}>({total}% of 100%)</span></h4>
    {form.targets.map((t, i) => <div key={i} className="plan-target">
      <input className="tool-input" placeholder="Ticker" aria-label={`Target ${i + 1} ticker`} maxLength={10} value={t.ticker} onChange={e => setTarget(i, 'ticker', e.target.value)} />
      <input className="tool-input" type="number" min="1" max="100" step="any" aria-label={`Target ${i + 1} percent`} value={t.pct} onChange={e => setTarget(i, 'pct', e.target.value)} />
      <span>%</span>
      {form.targets.length > 1 && <button type="button" className="btn-icon" aria-label={`Remove target ${i + 1}`}
        onClick={() => setForm(f => ({ ...f, targets: f.targets.filter((_, j) => j !== i) }))}>✕</button>}
    </div>)}
    {form.targets.length < 20 && <button type="button" className="link-btn" onClick={() => setForm(f => ({ ...f, targets: [...f.targets, { ticker: '', pct: '' }] }))}>+ Add holding</button>}
    <p className="market-sub">A broad index fund (for example VOO or VTI) as the core keeps one stock&apos;s bad year from sinking the plan. Not advice.</p>
    {error && <p className="error-text" role="alert">{error}</p>}
    <div className="form-actions"><button type="submit" className="btn-primary btn-sm" disabled={!valid || busy}>{busy ? 'Saving…' : 'Save plan'}</button>
      {onCancel && <button type="button" className="btn-secondary btn-sm" onClick={onCancel}>Cancel</button>}</div>
  </form>;
}

function Plan({ status, accounts, onChanged, setMsg }) {
  const [editing, setEditing] = useState(false);
  const preferred = accounts.find(a => a.role === 'long_term')?.account;
  if (!status || editing) {
    const initial = status ? { account: status.account === 'Default' ? '' : status.account, monthly: String(status.plan.monthly), day: String(status.plan.day || 1),
      goal: status.plan.goal ? String(status.plan.goal) : '', assumed_return_pct: String(status.plan.assumed_return_pct ?? 7),
      targets: status.plan.targets.map(t => ({ ticker: t.ticker, pct: String(t.pct) })) }
      : { ...EMPTY_PLAN, account: preferred && preferred !== 'Default' ? preferred : '' };
    return <section className="card" aria-label="Monthly investing plan section">
      <h3>Monthly investing plan</h3>
      <p className="structures-intro">Pick how much to invest each month and your target mix. Each month the app suggests what to buy to stay on target,
        tracks what you have invested, and reminds you once a month.</p>
      <PlanEditor initial={initial} accounts={accounts} onSaved={() => { setEditing(false); onChanged(); }} onCancel={status ? () => setEditing(false) : null} />
    </section>;
  }
  const remove = async () => {
    if (!window.confirm('Delete your monthly investing plan?')) return;
    try { await deleteInvestPlan(); onChanged(); } catch (error) { setMsg(error.message); }
  };
  const done = status.plan.monthly - status.remaining;
  const projection = status.projection.find(p => p.rate_pct === Number(status.plan.assumed_return_pct ?? 7)) || status.projection[0];
  return <section className="card" aria-label="Monthly investing plan section">
    <div className="ivrank-header"><h3 style={{ margin: 0 }}>Monthly investing plan</h3>
      <span><button className="link-btn" onClick={() => setEditing(true)}>Edit</button> · <button className="link-btn" onClick={remove}>Delete</button></span></div>
    <p className="market-sub">{usd(status.plan.monthly)} a month into <strong>{status.account}</strong> ({ROLE[status.role]}), on day {status.plan.day || 1}.</p>
    <div className="plan-progress" aria-label="This month's progress"><span style={{ width: `${Math.min(done / status.plan.monthly * 100, 100)}%` }} /></div>
    <p>{status.month}: <strong>{usd(status.invested_this_month)}</strong> invested{status.remaining > 0 ? <>, <strong>{usd(status.remaining)}</strong> to go</> : ' · ✓ done for this month'}</p>
    <div className="table-scroll"><table className="market-table phone-cards" aria-label="Suggested buys">
      <thead><tr><th>Holding</th><th>Target</th><th>Now</th><th>{status.remaining > 0 ? 'Buy this month' : 'Next month'}</th></tr></thead>
      <tbody>{status.buys.map(b => <tr key={b.ticker}>
        <td><strong>{b.ticker}</strong> <span className="market-sub">{usd(b.value)}</span></td>
        <td data-label="Target">{b.target_pct}%</td>
        <td data-label="Now">{b.current_pct == null ? '—' : `${b.current_pct}%`}</td>
        <td data-label="Buy">{usd(b.buy)}{b.shares ? <span className="market-sub"> ≈ {b.shares} sh at ${b.price}</span> : ''}</td>
      </tr>)}</tbody>
    </table></div>
    {Object.keys(status.outside_plan).length > 0 && <p className="market-sub">Also in this account, outside the plan: {Object.entries(status.outside_plan).map(([t, v]) => `${t} ${usd(v)}`).join(', ')}.</p>}
    <h4>Where this could go</h4>
    <div className="table-scroll"><table className="market-table phone-cards" aria-label="Projection">
      <thead><tr><th>Yearly return</th><th>In 5 years</th><th>In 10 years</th><th>In 20 years</th>{status.plan.goal ? <th>Years to {usd(status.plan.goal)}</th> : null}</tr></thead>
      <tbody>{status.projection.map(p => <tr key={p.rate_pct} className={p === projection ? 'projection-main' : ''}>
        <td><strong>{p.rate_pct}%</strong></td><td data-label="5 years">{usd(p.years[5])}</td><td data-label="10 years">{usd(p.years[10])}</td>
        <td data-label="20 years">{usd(p.years[20])}</td>{status.plan.goal ? <td data-label="Years to goal">{p.years_to_goal ?? '50+'}</td> : null}
      </tr>)}</tbody>
    </table></div>
    <p className="ivrank-note">Starting from {usd(status.start_value)} in {status.account}. {status.note}</p>
  </section>;
}

function Sweep({ sweep, accounts, onChanged, setMsg }) {
  const trading = accounts.filter(a => a.role === 'trading');
  const longTerm = accounts.filter(a => a.role === 'long_term');
  const [from, setFrom] = useState(trading[0]?.account || '');
  const [to, setTo] = useState(longTerm[0]?.account || '');
  const [busy, setBusy] = useState(false);
  if (!sweep) return <section className="card"><h3>Move trading profits to long-term</h3>
    <p className="market-sub">Set &quot;Each month, move this % of the trading profit to long-term&quot; under Portfolio Risk → My trading rules to get a monthly reminder here.</p></section>;
  const record = async () => {
    setBusy(true);
    try {
      const result = await recordSweep({ from_account: from, to_account: to, amount: sweep.amount });
      setMsg(`Recorded moving ${usd(sweep.amount)} from ${from} to ${to}${result.cash_updated.length ? ' (cash balances updated)' : ' (cash balances unchanged: both accounts need an entered cash balance)'}. Make the transfer at your broker too.`);
      onChanged();
    } catch (error) { setMsg(error.message); }
    finally { setBusy(false); }
  };
  return <section className="card" aria-label="Profit sweep">
    <h3>Move trading profits to long-term</h3>
    <p>{sweep.month}: trading accounts made <strong className={sweep.trading_net >= 0 ? 'positive' : 'negative'}>{usd(sweep.trading_net)}</strong> net.
      Your rule moves {sweep.pct}%: <strong>{usd(sweep.amount)}</strong>.</p>
    {sweep.done ? <p className="positive">✓ Recorded {usd(sweep.done_detail.amount)} from {sweep.done_detail.from} to {sweep.done_detail.to}.</p>
      : sweep.amount < 1 ? <p className="market-sub">Nothing to move: last month&apos;s trading wasn&apos;t profitable.</p>
        : !trading.length || !longTerm.length ? <p className="market-sub">Mark at least one account as trading and one as long-term above to record the move.</p>
          : <div className="income-controls">
            <label>From<select className="tool-input" value={from} onChange={e => setFrom(e.target.value)}>{trading.map(a => <option key={a.account}>{a.account}</option>)}</select></label>
            <label>To<select className="tool-input" value={to} onChange={e => setTo(e.target.value)}>{longTerm.map(a => <option key={a.account}>{a.account}</option>)}</select></label>
            <button className="btn-primary btn-sm" disabled={busy} onClick={record}>Record the move</button>
          </div>}
    <p className="ivrank-note">Recording adjusts the entered cash balances in the app (when both have one); it does not move money at your broker.</p>
  </section>;
}

export default function LongTermPlan({ version, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError(null);
    fetchInvestOverview().then(value => { if (active) setData(value); }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [version, revision]);
  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <p className="loading-text">Loading your long-term plan…</p>;
  const reload = () => { setRevision(value => value + 1); onChanged?.(); };
  return <div className="long-term-plan">
    {msg && <p role="status">{msg}</p>}
    <Split split={data.split} onChanged={reload} setMsg={setMsg} />
    <Plan status={data.plan} accounts={data.split.accounts} onChanged={reload} setMsg={setMsg} />
    <Sweep key={JSON.stringify(data.split.accounts.map(a => [a.account, a.role]))} sweep={data.sweep} accounts={data.split.accounts} onChanged={reload} setMsg={setMsg} />
  </div>;
}
