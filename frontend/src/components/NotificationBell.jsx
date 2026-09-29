import { useState, useEffect, useRef, useCallback } from 'react';
import {
  fetchNotifications, markNotificationsRead, fetchNotificationSettings, saveNotificationSettings,
} from '../api/stockApi';

const POLL_MS = 120_000;

// SQLite returns naive UTC ('YYYY-MM-DD HH:MM:SS'); Postgres includes an offset
function parseTs(s) {
  const iso = s.replace(' ', 'T');
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
}

export default function NotificationBell() {
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [topic, setTopic] = useState('');
  const [msg, setMsg] = useState(null);
  const ref = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchNotifications();
      setItems(data.items);
      setUnread(data.unread);
    } catch { /* offline or signed out */ }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  useEffect(() => {
    const onClick = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && unread > 0) {
      setUnread(0);
      try { await markNotificationsRead(); } catch { /* ignore */ }
    }
  };

  const openSettings = async () => {
    setShowSettings(s => !s);
    setMsg(null);
    try { setTopic((await fetchNotificationSettings()).ntfy_topic || ''); } catch { /* ignore */ }
  };

  const save = async () => {
    try {
      await saveNotificationSettings(topic.trim() || null);
      setMsg(topic.trim() ? 'Saved. Subscribe to this topic in the ntfy app.' : 'Push notifications disabled.');
    } catch (e) {
      setMsg(e.message);
    }
  };

  const suggestTopic = () => {
    const rand = crypto.getRandomValues(new Uint8Array(12));
    setTopic('stockinsights-' + Array.from(rand, b => b.toString(16).padStart(2, '0')).join(''));
  };

  return (
    <div className="notif-wrap" ref={ref}>
      <button className="btn-theme notif-bell" onClick={toggle} title="Notifications">
        🔔{unread > 0 && <span className="notif-count">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className="notif-panel">
          <div className="notif-panel-header">
            <strong>Notifications</strong>
            <button className="btn-secondary btn-sm" onClick={openSettings}>⚙️ Push</button>
          </div>

          {showSettings && (
            <div className="notif-settings">
              <p>
                Free phone push via <a href="https://ntfy.sh" target="_blank" rel="noopener noreferrer">ntfy</a>:
                install the app, subscribe to a hard-to-guess topic, and paste it here.
              </p>
              <div className="notif-settings-row">
                <input value={topic} onChange={e => setTopic(e.target.value)} placeholder="your-secret-topic" maxLength={64} />
                <button className="btn-secondary btn-sm" onClick={suggestTopic} title="Generate a random topic">🎲</button>
                <button className="btn-primary btn-sm" onClick={save}>Save</button>
              </div>
              {msg && <p className="notif-msg">{msg}</p>}
            </div>
          )}

          {items.length === 0 ? (
            <p className="empty-state">No alerts yet. Alerts are checked every 15 min during market hours for your holdings and watchlist.</p>
          ) : (
            <ul className="notif-list">
              {items.map(n => (
                <li key={n.id} className={`notif-item notif-${n.kind}`}>
                  <div className="notif-title">{n.kind === 'briefing' ? '📰' : '⚡'} {n.title}</div>
                  <div className="notif-body">{n.body}</div>
                  <div className="notif-time">{parseTs(n.created_at).toLocaleString()}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
