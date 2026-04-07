import { useState, useEffect, useCallback, useMemo } from 'react';
import { useAuth } from '../AuthContext';

import { API_BASE } from '../api/config';
import { fetchBatchSparklines } from '../api/stockApi';

const BASE = API_BASE;
const GUEST_KEY = 'guest_watchlist';

function getGuestList() {
  try { return JSON.parse(localStorage.getItem(GUEST_KEY) || '[]'); }
  catch { return []; }
}

function MiniSparkline({ data, up }) {
  if (!data || data.length < 2) return null;
  const w = 48, h = 20;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const points = data.map((v, i) =>
    `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`
  ).join(' ');
  return (
    <svg className="rail-sparkline" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline points={points} fill="none" stroke={up ? '#00c853' : '#ef5350'} strokeWidth="1.5" />
    </svg>
  );
}

export default function WatchlistRail({ activeTicker, onSelect, onGoToScreener }) {
  const { token, user } = useAuth();
  const isGuest = !user;

  const [rawTickers, setRawTickers] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [sparklines, setSparklines] = useState({});
  const [loading, setLoading] = useState(false);

  // Force re-sort when screener order changes
  const [orderVersion, setOrderVersion] = useState(0);

  // Apply screener sort order if available
  const tickers = useMemo(() => {
    try {
      const order = JSON.parse(sessionStorage.getItem('screener_order') || 'null');
      if (order && Array.isArray(order) && order.length) {
        const orderMap = {};
        order.forEach((t, i) => { orderMap[t] = i; });
        return [...rawTickers].sort((a, b) => (orderMap[a] ?? 999) - (orderMap[b] ?? 999));
      }
    } catch { /* ignore */ }
    return rawTickers;
  }, [rawTickers, orderVersion]);

  // Load ticker list from the right source
  const loadTickers = useCallback(async () => {
    if (isGuest) {
      setRawTickers(getGuestList());
    } else {
      try {
        const res = await fetch(`${BASE}/watchlist`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setRawTickers(data.tickers || []);
        }
      } catch { /* ignore */ }
    }
  }, [isGuest, token]);

  useEffect(() => {
    loadTickers();
    const id = setInterval(loadTickers, 30000);
    const onOrderChange = () => setOrderVersion(n => n + 1);
    window.addEventListener('storage', loadTickers);
    window.addEventListener('screener-order-changed', onOrderChange);
    return () => {
      clearInterval(id);
      window.removeEventListener('storage', loadTickers);
      window.removeEventListener('screener-order-changed', onOrderChange);
    };
  }, [loadTickers]);

  // Fetch mini-quotes for all tickers in one batch request
  const fetchQuotes = useCallback(async () => {
    if (!tickers.length) { setQuotes({}); return; }
    setLoading(true);
    try {
      const res = await fetch(`${BASE}/stock/batch-metrics`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tickers }),
      });
      if (res.ok) {
        const data = await res.json();
        const result = {};
        for (const [t, q] of Object.entries(data.quotes || {})) {
          result[t] = { price: q.price, change: q.change_pct, name: q.name || t };
        }
        setQuotes(result);
      }
    } catch { /* skip */ }
    setLoading(false);
  }, [tickers]);

  useEffect(() => {
    fetchQuotes();
    // Refresh quotes every 60s (metrics are cached server-side for 60s)
    const id = setInterval(fetchQuotes, 60000);
    return () => clearInterval(id);
  }, [fetchQuotes]);

  // Fetch sparkline data
  useEffect(() => {
    if (!tickers.length) { setSparklines({}); return; }
    fetchBatchSparklines(tickers)
      .then(d => setSparklines(d.sparklines || {}))
      .catch(() => {});
  }, [tickers.join(',')]);

  if (!tickers.length) {
    return (
      <aside className="watchlist-rail">
        <div className="rail-header">Watchlist</div>
        <div className="rail-empty">
          <p>No tickers yet</p>
          <button className="rail-add-btn" onClick={onGoToScreener}>+ Add in Screener</button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="watchlist-rail">
      <div className="rail-header">
        <span>Watchlist</span>
        <span className="rail-count">{tickers.length}</span>
      </div>

      <div className="rail-list">
        {tickers.map((t) => {
          const q = quotes[t];
          const isActive = activeTicker && activeTicker.toUpperCase() === t.toUpperCase();
          const changeClass = q?.change >= 0 ? 'positive' : 'negative';

          return (
            <button
              key={t}
              className={`rail-ticker ${isActive ? 'rail-ticker-active' : ''}`}
              onClick={() => onSelect(t)}
            >
              <div className="rail-ticker-symbol">{t}</div>
              {sparklines[t]?.length > 1 && (
                <MiniSparkline data={sparklines[t]} up={q?.change >= 0} />
              )}
              {q ? (
                <div className="rail-ticker-data">
                  <span className="rail-price">${q.price?.toFixed(2)}</span>
                  <span className={`rail-change ${changeClass}`}>
                    {q.change >= 0 ? '+' : ''}{q.change?.toFixed(2)}%
                  </span>
                </div>
              ) : (
                <div className="rail-ticker-data">
                  <span className="rail-price-loading">···</span>
                </div>
              )}
            </button>
          );
        })}
      </div>

      <button className="rail-add-btn" onClick={onGoToScreener}>+ Add tickers</button>
    </aside>
  );
}
