import { useEffect, useState } from 'react';
import WheelManager from './WheelManager';
import { fetchNextSteps } from '../api/stockApi';

const ICON = { act: '🔴', warn: '⚠️', idea: '💡', info: 'ℹ️' };
const DISMISS_KEY = 'next_steps_dismissed';
const DISMISS_MS = 7 * 86400_000;
const itemKey = item => `${item.code}|${item.account || ''}|${item.ticker || ''}`;

function loadDismissed() {
  try {
    const now = Date.now();
    return Object.fromEntries(Object.entries(JSON.parse(localStorage.getItem(DISMISS_KEY) || '{}')).filter(([, until]) => until > now));
  } catch { return {}; }
}

export default function NextSteps({ version, account = '', onShowAlerts, onShowTax, onTrim, onRepair }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [dismissed, setDismissed] = useState(loadDismissed);
  const [showHidden, setShowHidden] = useState(false);

  useEffect(() => {
    let active = true;
    setData(null); setError(null);
    fetchNextSteps(account).then(d => { if (active) setData(d); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [version, account]);

  const saveDismissed = next => {
    setDismissed(next);
    try { localStorage.setItem(DISMISS_KEY, JSON.stringify(next)); } catch { /* private mode */ }
  };
  const dismiss = item => saveDismissed({ ...dismissed, [itemKey(item)]: Date.now() + DISMISS_MS });
  const restore = item => { const next = { ...dismissed }; delete next[itemKey(item)]; saveDismissed(next); };

  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <p className="loading-text">Reviewing positions, cash and concentration…</p>;
  if (!data.items.length) return <p className="empty-state">✅ No suggestions right now.</p>;
  // Must-act items cannot be hidden
  const hidden = data.items.filter(item => item.level !== 'act' && dismissed[itemKey(item)]);
  const shown = data.items.filter(item => showHidden || !hidden.includes(item));

  const openWheel = () => { sessionStorage.setItem('ideas_tab', 'wheel'); window.location.hash = 'ideas'; };
  const action = (item, i) => {
    const link = item.link;
    if (!link) return null;
    if (link.kind === 'alerts') return <button className="link-btn" onClick={onShowAlerts}>See option alerts</button>;
    if (link.kind === 'wheel') return <button className="link-btn" onClick={openWheel}>Open Wheel ideas</button>;
    if (link.kind === 'tax') return <button className="link-btn" onClick={onShowTax}>Open tax check</button>;
    if (link.kind === 'trim' && onTrim) return <button className="link-btn" onClick={() => onTrim(link.ticker)}>Plan a trim</button>;
    if (link.kind === 'covered_calls') {
      return <button className="link-btn" aria-expanded={open === i} onClick={() => setOpen(open === i ? null : i)}>
        {open === i ? 'Hide covered calls' : 'Show covered calls'}
      </button>;
    }
    return null;
  };

  return (
    <>
      <p className="structures-intro">{data.note}</p>
      {shown.length === 0 && <p className="empty-state">✅ Nothing new. {hidden.length} suggestion{hidden.length === 1 ? ' is' : 's are'} dismissed for now.</p>}
      {shown.map((item, i) => (
        <div key={itemKey(item)} className={`desk-item next-step next-step-${item.level}`}>
          <div className="desk-head"><span aria-hidden="true">{ICON[item.level]}</span> <strong>{item.title}</strong>
            {item.level !== 'act' && (dismissed[itemKey(item)]
              ? <button className="link-btn next-step-dismiss" onClick={() => restore(item)}>Restore</button>
              : <button className="link-btn next-step-dismiss" title="Hide this suggestion for 7 days (it returns if it still applies)" onClick={() => dismiss(item)}>Dismiss 7 days</button>)}
          </div>
          {item.points?.length > 0 && <ul className="idea-checks next-step-points">{item.points.map(p => <li key={p}>{p}</li>)}</ul>}
          <p className="next-step-detail">{item.detail} {action(item, i)}</p>
          {onRepair && item.repairs?.length > 0 && (
            <div className="next-step-repairs">
              {item.repairs.map(r => <button key={r.id} className="btn-secondary btn-sm" onClick={() => onRepair(r.id)}>🔧 Repair {r.label}</button>)}
            </div>
          )}
          {open === i && item.link?.kind === 'covered_calls' && (
            <WheelManager preset={{ mode: 'assigned', ticker: item.link.ticker, costBasis: item.link.cost_basis, shares: item.link.shares }} />
          )}
        </div>
      ))}
      {hidden.length > 0 && (
        <button className="link-btn" onClick={() => setShowHidden(v => !v)}>
          {showHidden ? 'Hide dismissed suggestions' : `Show ${hidden.length} dismissed suggestion${hidden.length === 1 ? '' : 's'}`}
        </button>
      )}
    </>
  );
}
