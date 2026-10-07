import { useEffect, useState } from 'react';
import WheelManager from './WheelManager';
import { fetchNextSteps } from '../api/stockApi';

const ICON = { act: '🔴', warn: '⚠️', idea: '💡', info: 'ℹ️' };

export default function NextSteps({ version, onShowAlerts, onShowTax }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);

  useEffect(() => {
    let active = true;
    setData(null); setError(null);
    fetchNextSteps().then(d => { if (active) setData(d); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [version]);

  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <p className="loading-text">Reviewing positions, cash and concentration…</p>;
  if (!data.items.length) return <p className="empty-state">✅ No suggestions right now.</p>;

  const openWheel = () => { sessionStorage.setItem('ideas_tab', 'wheel'); window.location.hash = 'ideas'; };
  const action = (item, i) => {
    const link = item.link;
    if (!link) return null;
    if (link.kind === 'alerts') return <button className="link-btn" onClick={onShowAlerts}>See position alerts</button>;
    if (link.kind === 'wheel') return <button className="link-btn" onClick={openWheel}>Open Wheel ideas</button>;
    if (link.kind === 'tax') return <button className="link-btn" onClick={onShowTax}>Open tax check</button>;
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
      {data.items.map((item, i) => (
        <div key={`${item.code}-${item.account || ''}-${item.ticker || ''}`} className={`desk-item next-step next-step-${item.level}`}>
          <div className="desk-head"><span aria-hidden="true">{ICON[item.level]}</span> <strong>{item.title}</strong></div>
          {item.points?.length > 0 && <ul className="idea-checks next-step-points">{item.points.map(p => <li key={p}>{p}</li>)}</ul>}
          <p className="next-step-detail">{item.detail} {action(item, i)}</p>
          {open === i && item.link?.kind === 'covered_calls' && (
            <WheelManager preset={{ mode: 'assigned', ticker: item.link.ticker, costBasis: item.link.cost_basis, shares: item.link.shares }} />
          )}
        </div>
      ))}
    </>
  );
}
