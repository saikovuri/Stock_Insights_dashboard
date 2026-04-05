import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';

import { API_BASE } from '../api/config';

const BASE = API_BASE;
const GUEST_KEY = 'guest_watchlist';

function getGuestList() {
  try { return JSON.parse(localStorage.getItem(GUEST_KEY) || '[]'); }
  catch { return []; }
}

export default function WatchlistRail({ activeTicker, onSelect, onGoToScreener }) {
  const { token, user } = useAuth();
  const isGuest = !user;

  const [tickers, setTickers] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [loading, setLoading] = useState(false);

  // Load ticker list from the right source
  const loadTickers = useCallback(async () => {
    if (isGuest) {
      setTickers(getGuestList());
    } else {
      try {
        const res = await fetch(`${BASE}/watchlist`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setTickers(data.tickers || []);
        }
      } catch { /* ignore */ }
    }
  }, [isGuest, token]);

  useEffect(() => {
    loadTickers();
    // Poll for watchlist changes every 30s (lightweight DB-only call)
    const id = setInterval(loadTickers, 30000);
    window.addEventListener('storage', loadTickers);
    return () => { clearInterval(id); window.removeEventListener('storage', loadTickers); };
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
