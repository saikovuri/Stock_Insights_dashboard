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
        const res = await fetch(`${BASE}/screener`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          const stocks = data.stocks || [];
          setTickers(stocks.map(s => s.ticker || s));
        }
      } catch { /* ignore */ }
    }
  }, [isGuest, token]);

  useEffect(() => {
    loadTickers();
    // Poll to catch changes from Screener tab
    const id = setInterval(loadTickers, 3000);
    window.addEventListener('storage', loadTickers);
    return () => { clearInterval(id); window.removeEventListener('storage', loadTickers); };
  }, [loadTickers]);

  // Fetch mini-quotes for all tickers
  const fetchQuotes = useCallback(async () => {
    if (!tickers.length) { setQuotes({}); return; }
    setLoading(true);
    const result = {};
    await Promise.all(tickers.map(async (t) => {
      try {
        const res = await fetch(`${BASE}/stock/${t}/metrics`);
        if (res.ok) {
          const m = await res.json();
          result[t] = { price: m.price, change: m.change_pct, name: m.name || t };
        }
      } catch { /* skip */ }
    }));
    setQuotes(result);
    setLoading(false);
  }, [tickers]);

  useEffect(() => { fetchQuotes(); }, [fetchQuotes]);

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
