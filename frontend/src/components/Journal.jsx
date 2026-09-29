import { useState, useEffect, useCallback } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts';
import { useAuth } from '../AuthContext';
import {
  fetchJournal, addJournalEntry, updateJournalEntry, deleteJournalEntry, fetchJournalCoach,
} from '../api/stockApi';

const SETUP_TAGS = ['Breakout', 'Pullback', 'Gap and go', 'Opening range', 'Reversal', 'Earnings', 'Trend follow', 'Squeeze', 'Long-term buy'];
const today = () => new Date().toISOString().slice(0, 10);
const EMPTY = { ticker: '', side: 'long', shares: '', entry_date: today(), entry_price: '', stop: '', target: '', setup: '', notes: '', exit_date: '', exit_price: '' };

function money(v) {
  if (v == null) return '—';
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function Breakdown({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div className="journal-breakdown">
      <h4>{title}</h4>
      <table className="market-table">
        <thead><tr><th></th><th>Trades</th><th>Win %</th><th>P&L</th><th>Avg R</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.key} className="no-click">
              <td>{r.key}</td><td>{r.trades}</td><td>{r.win_rate}%</td>
              <td className={r.pnl >= 0 ? 'positive' : 'negative'}>{money(r.pnl)}</td>
              <td>{r.avg_r ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Journal({ onSignIn, onSelect }) {
  const { user } = useAuth();
  const [report, setReport] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [msg, setMsg] = useState(null);
  const [coach, setCoach] = useState(null);
  const [coachLoading, setCoachLoading] = useState(false);

  const load = useCallback(() => {
    fetchJournal().then(setReport).catch(e => setMsg(e.message));
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  if (!user) {
    return (
      <div className="card">
        <h3>📓 Trade Journal</h3>
        <p className="empty-state" style={{ padding: 0 }}>Sign in to log trades and get AI coaching on your win rate, R-multiples and habits.</p>
        {onSignIn && <button className="btn-primary btn-sm" onClick={onSignIn}>Sign in</button>}
      </div>
    );
  }

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));

  const save = async () => {
    setMsg(null);
    const num = v => (v === '' || v == null ? null : Number(v));
    const payload = {
      ...form, ticker: form.ticker.trim().toUpperCase(), shares: num(form.shares), entry_price: num(form.entry_price),
      stop: num(form.stop), target: num(form.target), exit_price: num(form.exit_price),
      exit_date: form.exit_price ? (form.exit_date || today()) : null, setup: form.setup || null, notes: form.notes || null,
    };
    try {
      if (editId) await updateJournalEntry(editId, payload); else await addJournalEntry(payload);
      setForm(EMPTY); setEditId(null); setShowForm(false); load();
    } catch (e) { setMsg(e.message); }
  };

  const edit = (t) => {
    setForm(Object.fromEntries(Object.keys(EMPTY).map(k => [k, t[k] ?? ''])));
    setEditId(t.id); setShowForm(true);
  };

  const remove = async (id) => {
    if (!window.confirm('Delete this trade?')) return;
    try { await deleteJournalEntry(id); load(); } catch (e) { setMsg(e.message); }
  };

  const runCoach = async () => {
    setCoachLoading(true);
    try { setCoach(await fetchJournalCoach()); } catch (e) { setCoach({ summary: e.message, strengths: [], leaks: [], rules: [] }); }
    finally { setCoachLoading(false); }
  };

  const s = report?.stats;
  const risk = form.stop && form.entry_price && form.shares
    ? Math.abs(Number(form.entry_price) - Number(form.stop)) * Number(form.shares) : null;
  const rr = form.stop && form.target && form.entry_price
    ? Math.abs(Number(form.target) - Number(form.entry_price)) / Math.abs(Number(form.entry_price) - Number(form.stop)) : null;

  return (
    <div className="journal">
      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>📓 Trade Journal</h3>
          <button className="btn-primary btn-sm" onClick={() => { setShowForm(!showForm); setEditId(null); setForm(EMPTY); }}>
            {showForm ? 'Cancel' : '+ Log trade'}
          </button>
        </div>
        {msg && <p className="error-text">{msg}</p>}

        {showForm && (
          <div className="journal-form">
            <input className="tool-input" placeholder="Ticker" value={form.ticker} onChange={set('ticker')} />
            <select className="candle-select" value={form.side} onChange={set('side')}>
              <option value="long">Long</option><option value="short">Short</option>
            </select>
            <input className="tool-input" type="number" placeholder="Shares" value={form.shares} onChange={set('shares')} />
            <label>Entry<input className="tool-input" type="date" value={form.entry_date} onChange={set('entry_date')} /></label>
            <input className="tool-input" type="number" step="any" placeholder="Entry price" value={form.entry_price} onChange={set('entry_price')} />
            <input className="tool-input" type="number" step="any" placeholder="Stop" value={form.stop} onChange={set('stop')} />
            <input className="tool-input" type="number" step="any" placeholder="Target" value={form.target} onChange={set('target')} />
            <input className="tool-input" list="setup-tags" placeholder="Setup tag" value={form.setup} onChange={set('setup')} maxLength={40} />
            <datalist id="setup-tags">{SETUP_TAGS.map(t => <option key={t} value={t} />)}</datalist>
            <label>Exit<input className="tool-input" type="date" value={form.exit_date} onChange={set('exit_date')} /></label>
            <input className="tool-input" type="number" step="any" placeholder="Exit price (blank if open)" value={form.exit_price} onChange={set('exit_price')} />
            <textarea className="tool-input journal-notes" placeholder="Notes: why you took it, emotions, mistakes…" value={form.notes} onChange={set('notes')} maxLength={1000} />
            <div className="journal-form-footer">
              {risk != null && <span className="market-sub">Risk ${risk.toFixed(2)}{rr != null && ` · reward/risk ${rr.toFixed(1)}:1`}</span>}
              <button className="btn-primary btn-sm" onClick={save}
                disabled={!form.ticker || !form.shares || !form.entry_price || !form.entry_date}>
                {editId ? 'Update trade' : 'Save trade'}
              </button>
            </div>
          </div>
        )}

        {s && (
          <div className="doctor-stats">
            <div><span>Total P&L</span><strong className={s.total_pnl >= 0 ? 'positive' : 'negative'}>{money(s.total_pnl)}</strong></div>
            <div><span>Win rate</span><strong>{s.win_rate != null ? `${s.win_rate}%` : '—'}</strong></div>
            <div><span>Profit factor</span><strong>{s.profit_factor ?? '—'}</strong></div>
            <div><span>Expectancy / trade</span><strong>{money(s.expectancy)}</strong></div>
            <div><span>Avg R</span><strong>{s.avg_r ?? '—'}</strong></div>
            <div><span>Avg win / loss</span><strong>{money(s.avg_win)} / {money(s.avg_loss)}</strong></div>
            <div><span>Max drawdown</span><strong className="negative">{money(s.max_drawdown)}</strong></div>
            <div><span>Closed / open</span><strong>{s.closed} / {s.open}</strong></div>
          </div>
        )}
        {s && s.pct_with_stop != null && s.pct_with_stop < 80 && (
          <p className="income-warning">Only {s.pct_with_stop}% of trades have a stop logged — add stops to measure risk (R-multiples).</p>
        )}
      </div>

      {report?.equity?.length > 1 && (
        <div className="card">
          <h3>Equity curve</h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={report.equity}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickFormatter={v => `$${v}`} />
              <Tooltip formatter={v => money(v)} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)' }} />
              <ReferenceLine y={0} stroke="var(--text-muted)" />
              <Area type="monotone" dataKey="equity" stroke="#7c6cf0" fill="rgba(124,108,240,0.2)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>🧠 AI Coach</h3>
          <button className="btn-secondary btn-sm" onClick={runCoach} disabled={coachLoading}>
            {coachLoading ? 'Reviewing trades…' : coach ? '↻ Re-run' : 'Review my trading'}
          </button>
        </div>
        {!coach && <p className="market-sub">Finds your edge and your leaks from your logged trades (needs 5+ closed trades).</p>}
        {coach && (
          <>
            <p className="ai-brief-summary">{coach.summary}</p>
            <div className="bull-bear-grid">
              {coach.strengths?.length > 0 && <div className="bull-col bull-bear-col"><div className="bull-bear-col-header">What's working</div><ul>{coach.strengths.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
              {coach.leaks?.length > 0 && <div className="bear-col bull-bear-col"><div className="bull-bear-col-header">Leaks</div><ul>{coach.leaks.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
            </div>
            {coach.rules?.length > 0 && <div className="bull-bear-col ai-brief-neutral"><div className="bull-bear-col-header">Rules for next week</div><ul>{coach.rules.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          </>
        )}
      </div>

      {report?.entries?.length > 0 && (
        <div className="card">
          <h3>Trades</h3>
          <div className="table-scroll">
            <table className="market-table">
              <thead><tr><th>Entry</th><th>Ticker</th><th>Side</th><th>Shares</th><th>Entry → Exit</th><th>P&L</th><th>R</th><th>Days</th><th>Setup</th><th></th></tr></thead>
              <tbody>
                {report.entries.map(t => (
                  <tr key={t.id} className="no-click" title={t.notes || ''}>
                    <td>{t.entry_date}</td>
                    <td><a onClick={() => onSelect?.(t.ticker)} className="link">{t.ticker}</a></td>
                    <td>{t.side}</td>
                    <td>{t.shares}</td>
                    <td>${t.entry_price} → {t.exit_price != null ? `$${t.exit_price}` : <span className="market-sub">open</span>}</td>
                    <td className={t.pnl >= 0 ? 'positive' : 'negative'}>{t.pnl != null ? `${money(t.pnl)} (${t.pnl_pct}%)` : '—'}</td>
                    <td>{t.r_multiple ?? '—'}</td>
                    <td>{t.hold_days ?? '—'}</td>
                    <td>{t.setup || '—'}</td>
                    <td className="journal-actions">
                      <button className="btn-icon" onClick={() => edit(t)} title="Edit / close">✎</button>
                      <button className="btn-icon" onClick={() => remove(t.id)} title="Delete">✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report?.stats?.closed > 0 && (
        <div className="card">
          <h3>Where your edge is</h3>
          <div className="journal-breakdowns">
            <Breakdown title="By setup" rows={report.breakdowns.setup} />
            <Breakdown title="By holding period" rows={report.breakdowns.holding} />
            <Breakdown title="By weekday" rows={report.breakdowns.weekday} />
            <Breakdown title="By side" rows={report.breakdowns.side} />
          </div>
        </div>
      )}
    </div>
  );
}
