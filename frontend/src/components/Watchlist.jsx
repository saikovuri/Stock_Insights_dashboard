import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useAuth } from '../AuthContext';
import PriceAlerts from './PriceAlerts';
import { authFetch, fetchWatchlistItems, fetchWatchlistEarnings, updateWatchlistItem } from '../api/stockApi';

import { API_BASE } from '../api/config';
const BASE = API_BASE;
const GUEST_KEY = 'guest_watchlist';
const SCREENER_CACHE_KEY = 'screener_cache';
const SCREENER_CACHE_TTL = 60000; // 60 seconds

function getGuestList() {
  try { return JSON.parse(localStorage.getItem(GUEST_KEY) || '[]'); }
  catch { return []; }
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

export default function Watchlist(props) {
  const session = useAuth();
  const accountKey = session.user ? `user:${session.user.id ?? session.user.username}` : 'guest';
  return <AccountWatchlist key={accountKey} {...props} session={session} />;
}

function AccountWatchlist({ onSelect, onSignIn, session }) {
  const { token, user } = session;
  const isGuest = !user;
  const cacheKey = `${SCREENER_CACHE_KEY}:${user?.id ?? user?.username ?? 'guest'}`;

  const [stocks, setStocks] = useState([]);
  const [guestTickers, setGuestTickers] = useState(getGuestList);
  const [loading, setLoading] = useState(false);
  const [addTicker, setAddTicker] = useState('');
  const [addMsg, setAddMsg] = useState('');
  const [sortCol, setSortCol] = useState('custom');
  const [sortDir, setSortDir] = useState(1);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [customOrder, setCustomOrder] = useState([]);
  const [alertPanelTicker, setAlertPanelTicker] = useState(null);
  const [items, setItems] = useState({});
  const [earnings, setEarnings] = useState({});
  const [group, setGroup] = useState('');
  const [notePanel, setNotePanel] = useState(null);
  const [draft, setDraft] = useState({ list_name: '', note: '' });
  const active = useRef(false);
  const loadGeneration = useRef(0);

  useEffect(() => {
    active.current = true;
    return () => { active.current = false; loadGeneration.current += 1; };
  }, []);

  // ── Auth mode ──────────────────────────────────────────────────

  const fetchScreenerAuth = useCallback(async (forceRefresh = false) => {
    if (!active.current) return;
    const generation = ++loadGeneration.current;
    // Show cached data immediately (stale-while-revalidate)
    try {
      const cached = JSON.parse(sessionStorage.getItem(cacheKey) || 'null');
      if (cached && !forceRefresh && Date.now() - cached.ts < SCREENER_CACHE_TTL) {
        setStocks(cached.stocks);
        setLastUpdated(new Date(cached.ts));
        setLoading(false);
        return;  // Cache is fresh enough, skip fetch
      }
      if (cached) { setStocks(cached.stocks); setLastUpdated(new Date(cached.ts)); }
    } catch { /* ignore */ }
    setLoading(true);
    try {
      const res = await authFetch(`${BASE}/screener`);
      if (!active.current || generation !== loadGeneration.current) return;
      if (res.ok) {
        const data = (await res.json()).stocks || [];
        if (!active.current || generation !== loadGeneration.current) return;
        const now = Date.now();
        setStocks(data);
        setLastUpdated(new Date(now));
        sessionStorage.setItem(cacheKey, JSON.stringify({ stocks: data, ts: now }));
      }
      else setAddMsg('Watchlist unavailable. Please retry.');
    } catch (error) {
      if (active.current && generation === loadGeneration.current) setAddMsg(error.message);
    } finally {
      if (active.current && generation === loadGeneration.current) setLoading(false);
    }
  }, [token, cacheKey]);

  // ── Guest mode: fetch metrics per-ticker ──────────────────────

  const fetchScreenerGuest = useCallback(async () => {
    if (!active.current) return;
    const generation = ++loadGeneration.current;
    if (!guestTickers.length) { setStocks([]); setLoading(false); return; }
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
      if (active.current && generation === loadGeneration.current) setStocks(results);
    } catch { /* ignore */ }
    if (active.current && generation === loadGeneration.current) setLoading(false);
  }, [guestTickers]);

  useEffect(() => {
    if (isGuest) fetchScreenerGuest();
    else fetchScreenerAuth();
  }, [isGuest, fetchScreenerAuth, fetchScreenerGuest]);

  const tickerKey = stocks.map(s => s.ticker).sort().join(',');
  useEffect(() => {
    if (isGuest || !tickerKey) return undefined;
    let current = true;
    fetchWatchlistItems().then(data => {
      if (current) setItems(Object.fromEntries((data.items || []).map(item => [item.ticker, item])));
    }).catch(() => {});
    fetchWatchlistEarnings().then(data => {
      if (current) setEarnings(Object.fromEntries((data.items || []).map(item => [item.ticker, item])));
    }).catch(() => {});
    return () => { current = false; };
  }, [isGuest, tickerKey]);

  const groups = [...new Set(Object.values(items).map(item => item.list_name || 'Main'))].sort();

  const openNotes = (ticker) => {
    setNotePanel(prev => (prev === ticker ? null : ticker));
    setDraft({ list_name: items[ticker]?.list_name || 'Main', note: items[ticker]?.note || '' });
  };

  const saveNotes = async (ticker) => {
    try {
      await updateWatchlistItem(ticker, draft.list_name.trim() || 'Main', draft.note);
      setItems(prev => ({ ...prev, [ticker]: { ticker, list_name: draft.list_name.trim() || 'Main', note: draft.note.trim() } }));
      setNotePanel(null);
    } catch (error) { setAddMsg(error.message); }
  };

  const earningsCell = (ticker) => {
    const next = earnings[ticker]?.next;
    if (!next) return '—';
    const days = Math.round((Date.parse(`${next}T12:00:00`) - Date.now()) / 86400000);
    const label = new Date(`${next}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return <span className={days <= 14 ? 'earnings-soon' : ''} title={`${earnings[ticker].timing || 'time unknown'}${earnings[ticker].confirmed ? '' : ' · unconfirmed'}`}>
      {label}{days >= 0 && days <= 14 ? ` (${days}d)` : ''}{earnings[ticker].confirmed ? '' : '*'}</span>;
  };

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
        if (!active.current) return;
        if (!res.ok) { setAddMsg(`Ticker '${t}' not found`); return; }
      } catch { if (active.current) setAddMsg('Network error'); return; }
      const newList = [...guestTickers, t];
      localStorage.setItem(GUEST_KEY, JSON.stringify(newList));
      setGuestTickers(newList);
      setAddTicker('');
    } else {
      try {
        const res = await authFetch(`${BASE}/watchlist`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker: t, ...(group ? { list_name: group } : {}) }),
        });
        if (!active.current) return;
        if (res.ok) { setAddTicker(''); sessionStorage.removeItem(cacheKey); fetchScreenerAuth(true); }
        else { const err = await res.json(); if (active.current) setAddMsg(err.detail || 'Failed to add'); }
      } catch { if (active.current) setAddMsg('Network error'); }
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
        const response = await authFetch(`${BASE}/watchlist/${ticker}`, {
          method: 'DELETE', headers: { Authorization: `Bearer ${token}` },
        });
        if (!active.current) return;
        if (!response.ok) throw new Error('Could not remove ticker. Please retry.');
        loadGeneration.current += 1;
        setLoading(false);
        sessionStorage.removeItem(cacheKey);
        setStocks((prev) => prev.filter((s) => s.ticker !== ticker));
      } catch (error) { if (active.current) setAddMsg(error.message); }
    }
  };

  // ── Sync customOrder with stocks ─────────────────────────────
  useEffect(() => {
    if (stocks.length && customOrder.length === 0) {
      setCustomOrder(stocks.map(s => s.ticker));
    } else if (stocks.length) {
      // Add any new tickers, remove deleted ones
      const current = new Set(stocks.map(s => s.ticker));
      const ordered = customOrder.filter(t => current.has(t));
      stocks.forEach(s => { if (!ordered.includes(s.ticker)) ordered.push(s.ticker); });
      if (ordered.join(',') !== customOrder.join(',')) setCustomOrder(ordered);
    }
  }, [stocks]);

  // ── Drag and Drop ──────────────────────────────────────────────
  const dragIdxRef = useRef(null);
  const dragOverIdxRef = useRef(null);

  const handleDragStart = (idx) => { dragIdxRef.current = idx; };
  const handleDragOver = (e, idx) => { e.preventDefault(); dragOverIdxRef.current = idx; };
  const handleDrop = () => {
    const from = dragIdxRef.current;
    const to = dragOverIdxRef.current;
    if (from == null || to == null || from === to) return;
    const list = sortCol === 'custom' ? [...customOrder] : sorted.map(s => s.ticker);
    const [moved] = list.splice(from, 1);
    list.splice(to, 0, moved);
    setCustomOrder(list);
    setSortCol('custom');
    dragIdxRef.current = null;
    dragOverIdxRef.current = null;
  };

  // ── Touch drag support ─────────────────────────────────────────
  const touchStartRef = useRef(null);
  const handleTouchStart = (idx, e) => {
    touchStartRef.current = { idx, y: e.touches[0].clientY };
  };
  const handleTouchEnd = (e) => {
    if (!touchStartRef.current) return;
    const endY = e.changedTouches[0].clientY;
    const rows = document.querySelectorAll('.screener-table tbody tr:not(.alert-panel-row)');
    let targetIdx = null;
    rows.forEach((row, i) => {
      const rect = row.getBoundingClientRect();
      if (endY >= rect.top && endY <= rect.bottom) targetIdx = i;
    });
    if (targetIdx != null && targetIdx !== touchStartRef.current.idx) {
      dragIdxRef.current = touchStartRef.current.idx;
      dragOverIdxRef.current = targetIdx;
      handleDrop();
    }
    touchStartRef.current = null;
  };

  const doSort = (col) => {
    if (col === 'custom') { setSortCol('custom'); setSortDir(1); return; }
    if (sortCol === col) setSortDir(-sortDir);
    else { setSortCol(col); setSortDir(1); }
  };

  const SORT_OPTIONS = [
    { value: 'custom', label: 'Manual Order' },
    { value: 'ticker', label: 'Ticker' },
    { value: 'name', label: 'Name' },
    { value: 'price', label: 'Price' },
    { value: 'change_pct', label: 'Change %' },
    { value: 'market_cap', label: 'Market Cap' },
    { value: 'pe_ratio', label: 'P/E Ratio' },
    { value: 'rsi', label: 'RSI' },
    { value: 'volume', label: 'Volume' },
    { value: 'dividend_yield', label: 'Dividend %' },
    { value: 'sector', label: 'Sector' },
  ];

  const sorted = useMemo(() => {
    const visible = group ? stocks.filter(s => (items[s.ticker]?.list_name || 'Main') === group) : stocks;
    if (sortCol === 'custom') {
      const orderMap = {};
      customOrder.forEach((t, i) => { orderMap[t] = i; });
      return [...visible].sort((a, b) => (orderMap[a.ticker] ?? 999) - (orderMap[b.ticker] ?? 999));
    }
    return [...visible].sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === 'string') return va.localeCompare(vb) * sortDir;
      return (va - vb) * sortDir;
    });
  }, [stocks, sortCol, sortDir, customOrder, group, items]);

  // Broadcast order to WatchlistRail (must be in useEffect, not useMemo, to avoid
  // triggering setState in WatchlistRail during Screener's render phase)
  useEffect(() => {
    const order = sorted.map(s => s.ticker);
    sessionStorage.setItem('screener_order', JSON.stringify(order));
    window.dispatchEvent(new Event('screener-order-changed'));
  }, [sorted]);

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
          👀 Watchlist {isGuest && <span className="guest-badge">Guest</span>}
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
          {!isGuest && groups.length > 0 && (
            <div className="screener-sort-dropdown">
              <label htmlFor="watchlist-group">List:</label>
              <select id="watchlist-group" value={group} onChange={e => setGroup(e.target.value)}>
                <option value="">All lists</option>
                {groups.map(name => <option key={name} value={name}>{name}</option>)}
              </select>
            </div>
          )}
          <div className="screener-sort-dropdown">
            <label>Sort:</label>
            <select
              value={sortCol}
              onChange={e => { setSortCol(e.target.value); setSortDir(1); }}
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {sortCol !== 'custom' && (
              <button
                className="btn-sort-dir"
                onClick={() => setSortDir(-sortDir)}
                title="Toggle sort direction"
              >{sortDir === 1 ? '▲' : '▼'}</button>
            )}
          </div>
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
          Watchlist saved in this browser only. Sign in to sync across devices, unlock RSI and get phone alerts.
        </p>
      )}
      {addMsg && <div className="portfolio-msg">{addMsg}</div>}

      {loading && stocks.length === 0 ? (
        <p className="loading-text">Loading watchlist...</p>
      ) : stocks.length === 0 ? (
        <p className="empty-state">Your watchlist is empty. Add tickers above to start tracking.</p>
      ) : (
        <div className="screener-table-wrap">
          <table className="portfolio-table screener-table watchlist-table">
            <thead>
              <tr>
                <th className="drag-handle-col"></th>
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
                {!isGuest && <th title="Next earnings date (* = providers disagree / unconfirmed)">Earnings</th>}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((s, idx) => {
                const panelOpen = alertPanelTicker === s.ticker;
                return (
                  <React.Fragment key={s.ticker}>
                    <tr
                      draggable
                      onDragStart={() => handleDragStart(idx)}
                      onDragOver={(e) => handleDragOver(e, idx)}
                      onDrop={handleDrop}
                      onTouchStart={(e) => handleTouchStart(idx, e)}
                      onTouchEnd={handleTouchEnd}
                    >
                      <td className="drag-handle" title="Drag to reorder">⠿</td>
                      <td><button className="link-btn" onClick={() => onSelect?.(s.ticker)} title="Open on dashboard"><strong>{s.ticker}</strong></button></td>
                      <td className="screener-name">{s.name}{items[s.ticker]?.note && <div className="market-sub watchlist-note">{items[s.ticker].note}</div>}</td>
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
                      {!isGuest && <td>{earningsCell(s.ticker)}</td>}
                      <td className="action-cell">
                        {!isGuest && <button className="btn-icon" onClick={() => openNotes(s.ticker)}
                          title="List and notes" aria-label={`List and notes for ${s.ticker}`}>📝</button>}
                        <button
                          className="btn-icon btn-alert"
                          onClick={() => setAlertPanelTicker(prev => prev === s.ticker ? null : s.ticker)}
                          title="Price & RSI alerts (phone push)"
                        >🔔</button>
                        <button className="btn-icon btn-remove" onClick={() => handleRemove(s.ticker)} title="Remove">✕</button>
                      </td>
                    </tr>
                    {notePanel === s.ticker && (
                      <tr className="alert-panel-row">
                        <td colSpan={16}>
                          <div className="watchlist-note-editor">
                            <label>List<input className="tool-input" value={draft.list_name} maxLength={40} list="watchlist-groups"
                              onChange={e => setDraft(d => ({ ...d, list_name: e.target.value }))} /></label>
                            <datalist id="watchlist-groups">{groups.map(name => <option key={name} value={name} />)}</datalist>
                            <label>Note<textarea className="tool-input" value={draft.note} maxLength={500} rows={2}
                              onChange={e => setDraft(d => ({ ...d, note: e.target.value }))} /></label>
                            <button className="btn-primary btn-sm" onClick={() => saveNotes(s.ticker)}>Save</button>
                            <button className="btn-secondary btn-sm" onClick={() => setNotePanel(null)}>Cancel</button>
                          </div>
                        </td>
                      </tr>
                    )}
                    {panelOpen && (
                      <tr className="alert-panel-row">
                        <td colSpan={16}>
                          <PriceAlerts ticker={s.ticker} price={s.price} onSignIn={onSignIn} />
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
    </div>
  );
}
