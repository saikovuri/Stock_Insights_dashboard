import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../AuthContext';
import { authFetch } from '../api/stockApi';
import { API_BASE } from '../api/config';

const money = value => value == null ? 'Unavailable' : new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(value);
const kinds = ['fee', 'deposit', 'withdrawal', 'dividend', 'valuation', 'link'];

async function request(path, body) {
  const response = await authFetch(`${API_BASE}/accounting/${path}`, body ? { method: 'POST', body: JSON.stringify(body) } : {});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Accounting request failed. Check the entry and retry.');
  return data;
}

export default function Accounting({ version }) {
  const { user } = useAuth();
  if (!user) return <p className="empty-state">Sign in to view the account ledger.</p>;
  return <AccountLedger key={user.id ?? user.username} version={version} />;
}

function AccountLedger({ version }) {
  const [report, setReport] = useState(null);
  const [events, setEvents] = useState([]);
  const [more, setMore] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ kind: 'fee', amount: '', occurred_at: '', nav_before: '', event_id: '', cycle: '', quantity: '', note: '' });
  const pending = useRef(null);
  const active = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => {
    let current = true;
    setError('');
    Promise.all([request('report'), request('events')]).then(([summary, history]) => {
      if (current) { setReport(summary); setEvents(history.events); setMore(history.events.length === 200); }
    }).catch(failure => { if (current) setError(failure.message); });
    return () => { current = false; };
  }, [version, revision]);

  const change = event => setForm(previous => ({ ...previous, [event.target.name]: event.target.value }));
  const save = async body => {
    const serialized = JSON.stringify(body);
    if (pending.current?.serialized !== serialized) pending.current = { serialized, key: crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      await request('entries', { ...body, idempotency_key: pending.current.key });
      if (!active.current) return;
      pending.current = null;
      setForm(previous => ({ ...previous, amount: '', quantity: '', note: '' }));
      setRevision(value => value + 1);
    } catch (failure) { if (active.current) setError(failure.message); }
    finally { if (active.current) setBusy(false); }
  };
  const submit = event => {
    event.preventDefault();
    const body = { kind: form.kind, occurred_at: new Date(form.occurred_at).toISOString(), note: form.note };
    if (form.kind === 'link') { body.cycle = form.cycle; body.quantity = form.quantity; }
    else body.amount = form.amount;
    if (form.event_id && ['fee', 'link'].includes(form.kind)) body.event_id = Number(form.event_id);
    if (form.nav_before && ['deposit', 'withdrawal'].includes(form.kind)) body.nav_before = form.nav_before;
    save(body);
  };
  const loadMore = async () => {
    setBusy(true);
    try {
      const data = await request(`events?after_id=${events.at(-1)?.id ?? 0}`);
      if (active.current) { setEvents(previous => [...previous, ...data.events]); setMore(data.events.length === 200); }
    } catch (failure) { if (active.current) setError(failure.message); }
    finally { if (active.current) setBusy(false); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'stockpilot-accounting.json'; anchor.click(); URL.revokeObjectURL(url);
  };
  return <section className="accounting-section">
    <div className="accounting-toolbar"><h3>Account ledger</h3><button className="btn-secondary" onClick={download} disabled={!report}>Export report</button><button className="btn-secondary" onClick={() => setRevision(value => value + 1)} disabled={busy}>Refresh</button></div>
    {error && <p className="error-text" role="alert">{error}</p>}
    {!report && !error && <p role="status">Loading accounting records...</p>}
    {report && <>
      <div className="doctor-stats">
        <div><span>Recorded fees</span><strong>{money(report.fees)}</strong></div>
        <div><span>Net external cash flow</span><strong>{money(report.external_cash_flow)}</strong></div>
        <div><span>Recorded dividends</span><strong>{money(report.dividends)}</strong></div>
        <div><span>Time-weighted return</span><strong>{report.twr.pct == null ? 'Unavailable' : `${report.twr.pct}%`}</strong></div>
      </div>
      {report.twr.reason && <p className="ivrank-note">{report.twr.reason}</p>}
      {report.has_legacy_snapshots && <p className="income-warning">Legacy opening snapshots are present. Earlier edits and deleted records cannot be reconstructed.</p>}
    </>}
    <form onSubmit={submit} className="accounting-form">
      <label>Entry<select name="kind" value={form.kind} onChange={change}>{kinds.map(kind => <option key={kind} value={kind}>{kind === 'link' ? 'Cycle allocation' : kind}</option>)}</select></label>
      <label>Occurred at<input aria-label="Occurred at" name="occurred_at" type="datetime-local" required value={form.occurred_at} onChange={change} /></label>
      {form.kind !== 'link' && <label>Amount ($)<input name="amount" type="number" min={form.kind === 'valuation' ? '0' : '0.01'} step="0.01" required value={form.amount} onChange={change} /></label>}
      {['deposit', 'withdrawal'].includes(form.kind) && <label>NAV immediately before flow ($)<input name="nav_before" type="number" min="0" step="0.01" value={form.nav_before} onChange={change} /></label>}
      {['fee', 'link'].includes(form.kind) && <label>Ledger event ID{form.kind === 'fee' ? ' (optional)' : ''}<input name="event_id" type="number" min="1" step="1" required={form.kind === 'link'} value={form.event_id} onChange={change} /></label>}
      {form.kind === 'link' && <><label>Cycle name<input name="cycle" maxLength={80} required value={form.cycle} onChange={change} /></label><label>Shares / contracts<input name="quantity" type="number" min="0.000001" step="any" required value={form.quantity} onChange={change} /></label></>}
      <label>Note<input name="note" maxLength={500} value={form.note} onChange={change} /></label>
      <button className="btn-primary" disabled={busy} type="submit">Record entry</button>
    </form>
    {report && <>
      <h4>Manual entries</h4>
      <div className="accounting-table"><table className="market-table"><thead><tr><th>ID</th><th>Date</th><th>Entry</th><th>Amount</th><th>Reference</th><th>Correction</th></tr></thead><tbody>
        {report.manual_entries.map(entry => <tr key={entry.id}><td>{entry.id}</td><td>{entry.occurred_at.slice(0, 10)}</td><td>{entry.kind}</td><td>{entry.kind === 'link' ? entry.quantity : money(entry.amount)}</td><td>{entry.cycle || entry.event_id || entry.note || '-'}</td><td><button className="btn-secondary" disabled={busy} onClick={() => save({ kind: 'reverse', event_id: entry.id, occurred_at: new Date().toISOString(), note: `Reversal of entry ${entry.id}` })}>Reverse #{entry.id}</button></td></tr>)}
      </tbody></table></div>
      <h4>US informational tax lots</h4>
      <div className="accounting-table"><table className="market-table"><thead><tr><th>Event</th><th>Ticker</th><th>Acquired</th><th>Closed</th><th>Term</th><th>Basis</th><th>Proceeds</th><th>Fees</th><th>Gain</th></tr></thead><tbody>
        {report.tax_lots.map(lot => <tr key={lot.event_id}><td>{lot.event_id}</td><td>{lot.ticker}</td><td>{lot.acquired_at || 'Unknown'}</td><td>{lot.closed_at}</td><td>{lot.term}</td><td>{money(lot.basis)}</td><td>{money(lot.proceeds)}</td><td>{money(lot.fees)}</td><td>{money(lot.gain)}</td></tr>)}
      </tbody></table></div>
      <h4>Strategy / wheel cycles</h4>
      {report.cycles.length === 0 && <p className="empty-state">No cycle allocations recorded.</p>}
      {report.cycles.map(cycle => <div key={cycle.name}><strong>{cycle.name}: {money(cycle.realized_pnl)} realized</strong><ul>{cycle.links.map(link => <li key={link.link_id}>{link.ticker} {link.quantity} ({link.source}, event {link.event_id})</li>)}</ul></div>)}
      {report.notes.map(note => <p className="ivrank-note" key={note}>{note}</p>)}
    </>}
    <h4>Immutable change history</h4>
    <div className="accounting-table"><table className="market-table"><thead><tr><th>Event</th><th>Recorded</th><th>Source</th><th>Action</th><th>Record</th></tr></thead><tbody>
      {[...events].reverse().map(event => <tr key={event.id}><td>{event.id}</td><td>{event.recorded_at}</td><td>{event.source} #{event.source_id}</td><td>{event.operation}</td><td><details><summary>{event.after?.ticker || event.before?.ticker || 'Details'}</summary><pre>{JSON.stringify({ before: event.before, after: event.after }, null, 2)}</pre></details></td></tr>)}
    </tbody></table></div>
    {more && <button className="btn-secondary" disabled={busy} onClick={loadMore}>Load more records</button>}
  </section>;
}