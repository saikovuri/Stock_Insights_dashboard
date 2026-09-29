import { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { fetchThesis, saveThesis, deleteThesis, checkThesis } from '../api/stockApi';

const STATUS = {
  intact: ['✅ Intact', 'positive'],
  weakening: ['⚠️ Weakening', ''],
  broken: ['⛔ Broken', 'negative'],
};

export default function ThesisCard({ ticker }) {
  const { user } = useAuth();
  const [thesis, setThesis] = useState(null);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  useEffect(() => {
    setThesis(null); setMsg(null); setEditing(false);
    if (!user) return;
    fetchThesis(ticker).then(t => {
      const has = t && !t.empty;
      setThesis(has ? t : null);
      setDraft(has ? t.thesis : '');
    }).catch(() => {});
  }, [ticker, user]);

  if (!user) return null;

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const t = await saveThesis(ticker, draft);
      setThesis(t); setEditing(false);
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const check = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await checkThesis(ticker);
      setThesis(t => ({ ...t, last_check: r }));
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const remove = async () => {
    try { await deleteThesis(ticker); setThesis(null); setDraft(''); } catch (e) { setMsg(e.message); }
  };

  const c = thesis?.last_check;
  const st = c ? STATUS[c.status] : null;

  return (
    <div className="card thesis-card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>📝 My thesis</h3>
        {thesis && !editing && (
          <div className="thesis-actions">
            <button className="btn-primary btn-sm" onClick={check} disabled={busy}>{busy ? 'Checking…' : '🤖 Check now'}</button>
            <button className="btn-secondary btn-sm" onClick={() => setEditing(true)}>Edit</button>
            <button className="btn-icon" onClick={remove} title="Delete thesis">✕</button>
          </div>
        )}
      </div>

      {(!thesis || editing) ? (
        <>
          <p className="market-sub">
            Why do you own (or want to own) {ticker}? What would prove you wrong? The AI re-checks it automatically after
            each earnings report and notifies you.
          </p>
          <textarea className="tool-input thesis-input" rows={3} maxLength={2000} value={draft}
            placeholder="e.g. Services revenue keeps growing 10%+ and buybacks shrink the share count; I'm wrong if margins fall two quarters in a row."
            onChange={e => setDraft(e.target.value)} />
          <div className="thesis-actions">
            <button className="btn-primary btn-sm" onClick={save} disabled={busy || draft.trim().length < 10}>Save thesis</button>
            {editing && <button className="btn-secondary btn-sm" onClick={() => { setEditing(false); setDraft(thesis.thesis); }}>Cancel</button>}
          </div>
        </>
      ) : (
        <>
          <blockquote className="thesis-text">{thesis.thesis}</blockquote>
          <p className="market-sub">
            {thesis.next_earnings ? `Auto-check after earnings on ${thesis.next_earnings}.` : 'No upcoming earnings date found.'}
          </p>
          {c && (
            <div className="thesis-check">
              <p><span className={`ai-brief-badge ${st?.[1]}`}>{st?.[0]}</span> <span className="market-sub">checked {new Date(c.checked_at).toLocaleString()}</span></p>
              <p>{c.summary}</p>
              <div className="bull-bear-grid">
                {c.supporting?.length > 0 && <div className="bull-col bull-bear-col"><div className="bull-bear-col-header">Supports</div><ul>{c.supporting.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
                {c.challenging?.length > 0 && <div className="bear-col bull-bear-col"><div className="bull-bear-col-header">Challenges</div><ul>{c.challenging.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
              </div>
              {c.watch?.length > 0 && <p className="market-sub">👀 Watch: {c.watch.join(' · ')}</p>}
            </div>
          )}
        </>
      )}
      {msg && <p className="error-text">{msg}</p>}
    </div>
  );
}
