import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';
import { fetchCustomAlerts, addCustomAlert, deleteCustomAlert } from '../api/stockApi';

const KINDS = [
  { value: 'price_above', label: 'Price rises above', unit: '$', suggest: p => (p * 1.05).toFixed(2) },
  { value: 'price_below', label: 'Price falls below', unit: '$', suggest: p => (p * 0.95).toFixed(2) },
  { value: 'change_up', label: 'Up today by at least', unit: '%', suggest: () => 5 },
  { value: 'change_down', label: 'Down today by at least', unit: '%', suggest: () => 5 },
  { value: 'rsi_above', label: 'RSI(14) above', unit: '', suggest: () => 70 },
  { value: 'rsi_below', label: 'RSI(14) below', unit: '', suggest: () => 30 },
  { value: 'below_high', label: 'Below 52-week high by', unit: '%', suggest: () => 20 },
];

export default function PriceAlerts({ ticker, price, onSignIn }) {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [kind, setKind] = useState('price_above');
  const [value, setValue] = useState('');
  const [note, setNote] = useState('');
  const [msg, setMsg] = useState(null);

  const load = useCallback(() => {
    if (!user) return;
    fetchCustomAlerts(ticker).then(d => setItems(d.items)).catch(() => {});
  }, [user, ticker]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const k = KINDS.find(x => x.value === kind);
    setValue(price ? String(k.suggest(price)) : String(k.suggest(100)));
  }, [kind, price, ticker]);

  if (!user) {
    return ticker ? (
      <div className="card">
        <h3>🎯 Alerts</h3>
        <p className="empty-state" style={{ padding: 0 }}>Sign in to set price and RSI alerts with phone push notifications.</p>
        {onSignIn && <button className="btn-primary btn-sm" onClick={onSignIn}>Sign in</button>}
      </div>
    ) : null;
  }

  const add = async () => {
    setMsg(null);
    try {
      await addCustomAlert({ ticker, kind, value: Number(value), note: note || null });
      setNote('');
      setMsg('Alert set. Checked every 2 minutes during market hours.');
      load();
    } catch (e) { setMsg(e.message); }
  };

  const remove = async (id) => {
    try { await deleteCustomAlert(id); load(); } catch (e) { setMsg(e.message); }
  };

  const unit = KINDS.find(x => x.value === kind)?.unit;

  return (
    <div className="card price-alerts">
      <h3>🎯 {ticker ? `Alerts for ${ticker}` : 'My alerts'}</h3>
      {ticker && (
        <div className="alert-form">
          <select className="candle-select" value={kind} onChange={e => setKind(e.target.value)}>
            {KINDS.map(k => <option key={k.value} value={k.value}>{k.label}</option>)}
          </select>
          <div className="alert-value">
            {unit === '$' && <span>$</span>}
            <input type="number" className="tool-input" value={value} step="any" min="0"
              onChange={e => setValue(e.target.value)} />
            {unit === '%' && <span>%</span>}
          </div>
          <input className="tool-input alert-note" value={note} maxLength={200} placeholder="Note (optional), e.g. breakout entry"
            onChange={e => setNote(e.target.value)} />
          <button className="btn-primary btn-sm" onClick={add} disabled={!value || Number(value) <= 0}>Add alert</button>
        </div>
      )}
      {msg && <p className="notif-msg">{msg}</p>}
      {items.length === 0 ? (
        <p className="empty-state" style={{ padding: '0.5rem 0 0' }}>No alerts yet.</p>
      ) : (
        <ul className="alert-list">
          {items.map(a => (
            <li key={a.id} className={a.active ? '' : 'alert-done'}>
              <span className="alert-list-ticker">{a.ticker}</span>
              <span>{a.description}{a.note ? ` — ${a.note}` : ''}</span>
              <span className="alert-list-status">{a.active ? 'Active' : `Triggered ${a.triggered_at ? new Date(a.triggered_at.replace(' ', 'T') + (a.triggered_at.includes('+') ? '' : 'Z')).toLocaleString() : ''}`}</span>
              <button className="btn-icon" onClick={() => remove(a.id)} title="Delete">✕</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
