import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useAuth } from '../AuthContext';
import CorrelationHeatmap from './CorrelationHeatmap';

import { API_BASE } from '../api/config';
const BASE = API_BASE;
const GUEST_KEY = 'guest_watchlist';
const ALERTS_KEY = 'screener_alerts';
const SCREENER_CACHE_KEY = 'screener_cache';
const SCREENER_CACHE_TTL = 60000; // 60 seconds

function getGuestList() {
  try { return JSON.parse(localStorage.getItem(GUEST_KEY) || '[]'); }
  catch { return []; }
}

function getAlerts() {
  try { return JSON.parse(localStorage.getItem(ALERTS_KEY) || '[]'); }
  catch { return []; }
}
function saveAlerts(list) { localStorage.setItem(ALERTS_KEY, JSON.stringify(list)); }

const ALERT_TYPES = [
  { value: 'price_above',  label: 'Price above $' },
  { value: 'price_below',  label: 'Price below $' },
  { value: 'change_above', label: 'Daily change above %' },
  { value: 'change_below', label: 'Daily change below %' },
  { value: 'rsi_above',    label: 'RSI above', authOnly: true },
  { value: 'rsi_below',    label: 'RSI below', authOnly: true },
];

function formatAlertLabel(a) {
  switch (a.type) {
    case 'price_above':  return `Price > $${a.threshold}`;
    case 'price_below':  return `Price < $${a.threshold}`;
    case 'change_above': return `Change > ${a.threshold}%`;
    case 'change_below': return `Change < ${a.threshold}%`;
    case 'rsi_above':    return `RSI > ${a.threshold}`;
    case 'rsi_below':    return `RSI < ${a.threshold}`;
    default: return 'Alert';
  }
}

function isAlertTriggeredForOne(a, s) {
  const { price, change_pct, rsi } = s;
  if (a.type === 'price_above')  return price      != null && price      > a.threshold;
  if (a.type === 'price_below')  return price      != null && price      < a.threshold;
  if (a.type === 'change_above') return change_pct != null && change_pct > a.threshold;
  if (a.type === 'change_below') return change_pct != null && change_pct < a.threshold;
  if (a.type === 'rsi_above')    return rsi        != null && rsi        > a.threshold;
  if (a.type === 'rsi_below')    return rsi        != null && rsi        < a.threshold;
  return false;
}

function formatNum(n) {
  if (n == null) return '—';
  if (n >= 1e12) return `$${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  return n.toLocaleString();
}

function formatVol(n) {
  if (n == null) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return n.toLocaleString();
}

export default function Screener() {
  const { token, user } = useAuth();
  const isGuest = !user;

  const [stocks, setStocks] = useState([]);
  const [guestTickers, setGuestTickers] = useState(getGuestList);
  const [loading, setLoading] = useState(false);
  const [addTicker, setAddTicker] = useState('');
  const [addMsg, setAddMsg] = useState('');
  const [sortCol, setSortCol] = useState('ticker');
  const [sortDir, setSortDir] = useState(1);
  const [lastUpdated, setLastUpdated] = useState(null);

  // ── Alert state ────────────────────────────────────────────────
  const [screenerAlerts, setScreenerAlerts] = useState(getAlerts);
  const [alertPanelTicker, setAlertPanelTicker] = useState(null);
  const [newAlert, setNewAlert] = useState({ type: 'price_above', threshold: '' });
  const notifiedRef = useRef(new Set());

  // ── Auth mode ──────────────────────────────────────────────────

  const fetchScreenerAuth = useCallback(async (forceRefresh = false) => {
    // Show cached data immediately (stale-while-revalidate)
    try {
      const cached = JSON.parse(sessionStorage.getItem(SCREENER_CACHE_KEY) || 'null');
      if (cached && !forceRefresh && Date.now() - cached.ts < SCREENER_CACHE_TTL) {
        setStocks(cached.stocks);
        setLastUpdated(new Date(cached.ts));
        return;  // Cache is fresh enough, skip fetch
      }
      if (cached) { setStocks(cached.stocks); setLastUpdated(new Date(cached.ts)); }
    } catch { /* ignore */ }
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/screener`, { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) {
        const data = (await res.json()).stocks || [];
        const now = Date.now();
        setStocks(data);
        setLastUpdated(new Date(now));
        sessionStorage.setItem(SCREENER_CACHE_KEY, JSON.stringify({ stocks: data, ts: now }));
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [token]);

  // ── Guest mode: fetch metrics per-ticker ──────────────────────

  const fetchScreenerGuest = useCallback(async () => {
    if (!guestTickers.length) { setStocks([]); return; }
    setLoading(true);
    try {
      const results = await Promise.all(guestTickers.map(async (t) => {
        try {
          const res = await fetch(`${BASE}/stock/${t}/metrics`);
          if (!res.ok) return { ticker: t, name: t, error: true };
          const m = await res.json();
          return {
            ticker: t, name: m.name || t,
            price: m.price, change_pct: m.change_pct,
            high_52w: m['52w_high'], low_52w: m['52w_low'],
            pe_ratio: m.pe_ratio, eps: m.eps,
            market_cap: m.market_cap, market_cap_fmt: formatNum(m.market_cap),
            volume: m.volume, dividend_yield: m.dividend_yield,
            beta: m.beta, sector: m.sector, rsi: null,
          };
        } catch { return { ticker: t, name: t, error: true }; }
      }));
      setStocks(results);
    } catch { /* ignore */ }
    setLoading(false);
  }, [guestTickers]);

  useEffect(() => {
    if (isGuest) fetchScreenerGuest();
    else fetchScreenerAuth();
  }, [isGuest, fetchScreenerAuth, fetchScreenerGuest]);

  // ── Add ticker ─────────────────────────────────────────────────

  const handleAdd = async (e) => {
    e.preventDefault();
    const t = addTicker.trim().toUpperCase();
    if (!t) return;
    setAddMsg('');

    if (isGuest) {
      if (guestTickers.includes(t)) { setAddMsg('Already in watchlist'); return; }
      try {
        const res = await fetch(`${BASE}/stock/${t}/metrics`);
        if (!res.ok) { setAddMsg(`Ticker '${t}' not found`); return; }
      } catch { setAddMsg('Network error'); return; }
      const newList = [...guestTickers, t];
      localStorage.setItem(GUEST_KEY, JSON.stringify(newList));
      setGuestTickers(newList);
      setAddTicker('');
    } else {
      try {
        const res = await fetch(`${BASE}/watchlist`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker: t }),
        });
        if (res.ok) { setAddTicker(''); sessionStorage.removeItem(SCREENER_CACHE_KEY); fetchScreenerAuth(true); }
        else { const err = await res.json(); setAddMsg(err.detail || 'Failed to add'); }
      } catch { setAddMsg('Network error'); }
    }
  };

  // ── Remove ticker ──────────────────────────────────────────────

  const handleRemove = async (ticker) => {
    if (isGuest) {
      const newList = guestTickers.filter((t) => t !== ticker);
      localStorage.setItem(GUEST_KEY, JSON.stringify(newList));
      setGuestTickers(newList);
      setStocks((prev) => prev.filter((s) => s.ticker !== ticker));
    } else {
      try {
        await fetch(`${BASE}/watchlist/${ticker}`, {
          method: 'DELETE', headers: { Authorization: `Bearer ${token}` },
        });
        sessionStorage.removeItem(SCREENER_CACHE_KEY);
        setStocks((prev) => prev.filter((s) => s.ticker !== ticker));
      } catch { /* ignore */ }
    }
  };

  // ── Alert helpers ──────────────────────────────────────────────

  const tickerAlerts = (ticker) => screenerAlerts.filter(a => a.ticker === ticker);

  const openAlertPanel = (ticker) => {
    setAlertPanelTicker(prev => prev === ticker ? null : ticker);
    setNewAlert({ type: 'price_above', threshold: '' });
  };

  const handleAddAlert = (ticker) => {
    const t = parseFloat(newAlert.threshold);
    if (isNaN(t)) return;
    const updated = [...screenerAlerts, { id: Date.now(), ticker, type: newAlert.type, threshold: t }];
    saveAlerts(updated);
    setScreenerAlerts(updated);
    setNewAlert({ type: 'price_above', threshold: '' });
  };

  const handleRemoveAlert = (id) => {
    const updated = screenerAlerts.filter(a => a.id !== id);
    saveAlerts(updated);
    setScreenerAlerts(updated);
  };

  // ── Triggered detection ────────────────────────────────────────
  // Map: ticker → [ { alert, currentVal } ]
  const triggeredMap = useMemo(() => {
    const map = {};
    screenerAlerts.forEach(a => {
      const s = stocks.find(s => s.ticker === a.ticker);
      if (!s || !isAlertTriggeredForOne(a, s)) return;
      const currentVal =
        a.type.startsWith('price')  ? (s.price       != null ? `$${s.price.toFixed(2)}`          : '—') :
        a.type.startsWith('change') ? (s.change_pct  != null ? `${s.change_pct.toFixed(2)}%`     : '—') :
        a.type.startsWith('rsi')    ? (s.rsi         != null ? s.rsi.toFixed(0)                   : '—') : '—';
      if (!map[a.ticker]) map[a.ticker] = [];
      map[a.ticker].push({ alert: a, currentVal });
    });
    return map;
  }, [stocks, screenerAlerts]);

  const triggered = useMemo(() => new Set(Object.keys(triggeredMap)), [triggeredMap]);

  // ── Browser notifications on trigger ──────────────────────────

  useEffect(() => {
    if (!triggered.size || typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
    triggered.forEach(ticker => {
      if (notifiedRef.current.has(ticker)) return;
      notifiedRef.current.add(ticker);
      const items = triggeredMap[ticker] || [];
      const body = items.map(i => `${formatAlertLabel(i.alert)} (now ${i.currentVal})`).join('\n');
      new Notification(`📈 ${ticker} alert triggered`, { body });
    });
  }, [triggered, triggeredMap]);

  const doSort = (col) => {
    if (sortCol === col) setSortDir(-sortDir);
    else { setSortCol(col); setSortDir(1); }
  };

  const sorted = [...stocks].sort((a, b) => {
    let va = a[sortCol], vb = b[sortCol];
    if (va == null) return 1;
    if (vb == null) return -1;
    if (typeof va === 'string') return va.localeCompare(vb) * sortDir;
    return (va - vb) * sortDir;
  });

  const arrow = (col) => sortCol === col ? (sortDir === 1 ? ' ▲' : ' ▼') : '';

  const rsiColor = (rsi) => {
    if (rsi == null) return {};
    if (rsi >= 70) return { color: '#d63031' };
    if (rsi <= 30) return { color: '#00b894' };
    return {};
  };

  return (
    <div className="card screener-card">
      <div className="screener-header">
        <h3>
          Screener / Watchlist {isGuest && <span className="guest-badge">Guest</span>}
          {lastUpdated && (
            <span className="screener-updated">
              Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </h3>
        <div className="screener-header-right">
          <button
            className="btn-refresh"
            onClick={() => isGuest ? fetchScreenerGuest() : fetchScreenerAuth(true)}
            disabled={loading}
            title="Refresh data"
          >
            {loading ? '⟳' : '↻'} Refresh
          </button>
          {screenerAlerts.length > 0 && typeof Notification !== 'undefined' && Notification.permission === 'default' && (
            <button className="btn-notify" onClick={() => Notification.requestPermission()} title="Get browser notifications when an alert triggers">
              🔔 Enable notifications
            </button>
          )}
          <form className="screener-add" onSubmit={handleAdd}>
            <input
              value={addTicker}
              onChange={e => setAddTicker(e.target.value)}
              placeholder="Add ticker (e.g. AAPL)"
              maxLength={10}
            />
            <button type="submit" className="btn-primary">+ Add</button>
          </form>
        </div>
      </div>
      {isGuest && (
        <p className="guest-note">
          Watchlist saved in this browser only. Sign in to sync across devices and unlock RSI data.
        </p>
      )}

      {triggered.size > 0 && (
        <div className="alert-triggered-panel">
          <span className="alert-triggered-panel-title">🔔 {triggered.size} alert{triggered.size !== 1 ? 's' : ''} triggered</span>
          <ul className="alert-triggered-list">
            {Object.entries(triggeredMap).map(([ticker, items]) =>
              items.map(({ alert, currentVal }) => (
                <li key={alert.id} className="alert-triggered-item">
                  <strong>{ticker}</strong>
                  <span className="alert-triggered-condition">{formatAlertLabel(alert)}</span>
                  <span className="alert-triggered-current">now {currentVal}</span>
                  <button className="btn-icon btn-remove" title="Delete this alert" onClick={() => handleRemoveAlert(alert.id)}>✕</button>
                </li>
              ))
            )}
          </ul>
        </div>
      )}
      {addMsg && <div className="portfolio-msg">{addMsg}</div>}

      {loading && stocks.length === 0 ? (
        <p className="loading-text">Loading watchlist...</p>
      ) : stocks.length === 0 ? (
        <p className="empty-state">Your watchlist is empty. Add tickers above to start tracking.</p>
      ) : (
        <div className="screener-table-wrap">
          <table className="portfolio-table screener-table">
            <thead>
              <tr>
                <th onClick={() => doSort('ticker')}>Ticker{arrow('ticker')}</th>
                <th onClick={() => doSort('name')}>Name{arrow('name')}</th>
                <th onClick={() => doSort('price')}>Price{arrow('price')}</th>
                <th onClick={() => doSort('change_pct')}>Chg%{arrow('change_pct')}</th>
                <th onClick={() => doSort('high_52w')}>52W H{arrow('high_52w')}</th>
                <th onClick={() => doSort('low_52w')}>52W L{arrow('low_52w')}</th>
                <th onClick={() => doSort('pe_ratio')}>P/E{arrow('pe_ratio')}</th>
                <th onClick={() => doSort('eps')}>EPS{arrow('eps')}</th>
                <th onClick={() => doSort('market_cap')}>Mkt Cap{arrow('market_cap')}</th>
                <th onClick={() => doSort('rsi')}>RSI{arrow('rsi')}</th>
                <th onClick={() => doSort('volume')}>Volume{arrow('volume')}</th>
                <th onClick={() => doSort('dividend_yield')}>Div%{arrow('dividend_yield')}</th>
                <th onClick={() => doSort('sector')}>Sector{arrow('sector')}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(s => {
                const rowAlerts = tickerAlerts(s.ticker);
                const isTriggered = triggered.has(s.ticker);
                const panelOpen = alertPanelTicker === s.ticker;
                return (
                  <React.Fragment key={s.ticker}>
                    <tr className={isTriggered ? 'alert-triggered' : ''}>
                      <td><strong>{s.ticker}</strong></td>
                      <td className="screener-name">{s.name}</td>
                      <td>${s.price?.toFixed(2) ?? '—'}</td>
                      <td className={s.change_pct >= 0 ? 'positive' : 'negative'}>
                        {s.change_pct >= 0 ? '+' : ''}{s.change_pct?.toFixed(2) ?? '—'}%
                      </td>
                      <td>${s.high_52w?.toFixed(2) ?? '—'}</td>
                      <td>${s.low_52w?.toFixed(2) ?? '—'}</td>
                      <td>{s.pe_ratio?.toFixed(1) ?? '—'}</td>
                      <td>{s.eps?.toFixed(2) ?? '—'}</td>
                      <td>{s.market_cap_fmt || '—'}</td>
                      <td style={rsiColor(s.rsi)}>
                        {s.rsi != null ? s.rsi.toFixed(0) : '—'}
                        {s.rsi != null && s.rsi >= 70 && <span className="rsi-badge overbought">OB</span>}
                        {s.rsi != null && s.rsi <= 30 && <span className="rsi-badge oversold">OS</span>}
                      </td>
                      <td>{formatVol(s.volume)}</td>
                      <td>{s.dividend_yield != null ? `${s.dividend_yield.toFixed(2)}%` : '—'}</td>
                      <td className="screener-sector">{s.sector || '—'}</td>
                      <td className="action-cell">
                        <button
                          className={`btn-icon btn-alert${rowAlerts.length ? ' has-alerts' : ''}${isTriggered ? ' alert-active' : ''}`}
                          onClick={() => openAlertPanel(s.ticker)}
                          title={rowAlerts.length ? `${rowAlerts.length} alert(s) — click to manage` : 'Add price alert'}
                        >🔔</button>
                        <button className="btn-icon btn-remove" onClick={() => handleRemove(s.ticker)} title="Remove">✕</button>
                      </td>
                    </tr>
                    {panelOpen && (
                      <tr className="alert-panel-row">
                        <td colSpan={14}>
                          <div className="alert-panel">
                            <span className="alert-panel-title">Alerts for <strong>{s.ticker}</strong></span>
                            {rowAlerts.length > 0 && (
                              <ul className="alert-list">
                                {rowAlerts.map(a => (
                                  <li key={a.id} className={`alert-item${isAlertTriggeredForOne(a, s) ? ' triggered' : ''}`}>
                                    <span className="alert-label">{formatAlertLabel(a)}</span>
                                    <button className="btn-icon btn-remove" onClick={() => handleRemoveAlert(a.id)} title="Delete alert">✕</button>
                                  </li>
                                ))}
                              </ul>
                            )}
                            <form className="alert-add-form" onSubmit={e => { e.preventDefault(); handleAddAlert(s.ticker); }}>
                              <select
                                value={newAlert.type}
                                onChange={e => setNewAlert(n => ({ ...n, type: e.target.value }))}
                              >
                                {ALERT_TYPES.filter(t => !t.authOnly || !isGuest).map(t => (
                                  <option key={t.value} value={t.value}>{t.label}</option>
                                ))}
                              </select>
                              <input
                                type="number"
                                step="any"
                                placeholder="Value"
                                value={newAlert.threshold}
                                onChange={e => setNewAlert(n => ({ ...n, threshold: e.target.value }))}
                              />
                              <button type="submit" className="btn-primary btn-sm">+ Add Alert</button>
                            </form>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {loading && stocks.length > 0 && <p className="loading-text" style={{marginTop:'0.5rem'}}>Refreshing...</p>}
      {stocks.length >= 2 && <CorrelationHeatmap tickers={stocks.map(s => s.ticker)} />}
    </div>
  );
}
