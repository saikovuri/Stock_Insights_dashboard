import { useCallback, useEffect, useState } from 'react';
import { fetchBuyZones, saveBuyZone, fetchWatchlistEvents } from '../api/stockApi';

const usd = v => v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const dayLabel = d => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

export function BuyZones({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [ticker, setTicker] = useState('');
  const [price, setPrice] = useState('');
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    setError(null);
    fetchBuyZones().then(setData).catch(e => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);
  const save = async (symbol, value) => {
    setBusy(true); setError(null);
    try { await saveBuyZone(symbol, value); setTicker(''); setPrice(''); setData(null); load(); } catch (e) { setError(e.message); }
    setBusy(false);
  };
  return <div className="card buy-zones" id="buy-zones">
    <h3>🎯 Buy zones</h3>
    <p className="structures-intro">Set the price you&apos;d be happy to buy at. Until it gets there, a cash-secured put at or below that price can pay you to wait:
      if assigned you buy at the strike minus the premium; if not, you keep the premium.</p>
    <form className="alert-form" onSubmit={event => { event.preventDefault(); if (ticker && Number(price) > 0) save(ticker.trim().toUpperCase(), Number(price)); }}>
      <input className="tool-input" aria-label="Buy zone ticker" placeholder="Ticker" maxLength={10} value={ticker} onChange={e => setTicker(e.target.value)} />
      <input className="tool-input" aria-label="Buy price" type="number" min="0.01" step="any" placeholder="Buy at $" value={price} onChange={e => setPrice(e.target.value)} />
      <button className="btn-primary btn-sm" type="submit" disabled={busy || !ticker || !(Number(price) > 0)}>Set buy zone</button>
    </form>
    {error && <p className="error-text" role="alert">{error}</p>}
    {!data && !error && <p className="loading-text">Checking prices and put quotes…</p>}
    {data && !data.items.length && <p className="empty-state">No buy zones yet.</p>}
    {data?.items.length > 0 && <>
      <div className="table-scroll"><table className="market-table" aria-label="Buy zones">
        <thead><tr><th>Stock</th><th>Buy at</th><th>Price</th><th>Away</th><th>Put to wait (≈35 days)</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{data.items.map(row => <tr key={row.ticker} className="no-click">
          <td><button className="link-btn" onClick={() => onSelect?.(row.ticker)}>{row.ticker}</button></td>
          <td>{usd(row.target)}</td><td>{usd(row.price)}</td>
          <td>{row.in_zone ? <strong className="positive">In zone</strong> : row.distance_pct != null ? `${row.distance_pct}% above` : '—'}</td>
          <td>{row.put ? <>Sell ${row.put.strike} put {row.put.expiry} for ~{usd(row.put.premium)}
            <span className="trade-sub">Buy-in {usd(row.put.effective_entry)} if assigned · {usd(row.put.cash_needed)} cash · {row.put.annualized_pct}%/yr · ~{row.put.chance_assigned_pct}% assigned</span></>
            : row.in_zone ? 'At or below your price now' : <span className="market-sub">No liquid put at or below your price</span>}</td>
          <td><button className="btn-icon" title={`Remove ${row.ticker} buy zone`} aria-label={`Remove ${row.ticker} buy zone`} disabled={busy} onClick={() => save(row.ticker, null)}>✕</button></td>
        </tr>)}</tbody>
      </table></div>
      <p className="market-sub">{data.note} Selling a put obliges you to buy 100 shares per contract at the strike, even if the stock falls far below it.</p>
    </>}
  </div>;
}

export function EventWeek({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { fetchWatchlistEvents(14).then(setData).catch(e => setError(e.message)); }, []);
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  const days = {};
  (data?.events || []).forEach(event => { (days[event.date] ||= []).push(event); });
  return <div className="card event-week" id="event-week">
    <h3>📅 Earnings &amp; ex-dividend: next 2 weeks</h3>
    {!data && <p className="loading-text">Checking dates for your watchlist and holdings…</p>}
    {data && !data.events.length && <p className="empty-state">No earnings or ex-dividend dates in the next 14 days for {data.checked} tickers.</p>}
    {data && data.events.length > 0 && <div className="event-days">{Object.entries(days).map(([day, events]) => <div key={day} className="event-day">
      <strong>{dayLabel(day)}</strong>
      <ul>{events.map(event => <li key={`${event.ticker}-${event.kind}`}>
        <button className="link-btn" onClick={() => onSelect?.(event.ticker)}>{event.ticker}</button>{' '}
        {event.kind === 'earnings' ? <>earnings{event.timing ? ` (${event.timing})` : ''}{event.confirmed ? '' : '*'}</> : 'ex-dividend'}
        {event.held && <span className="account-badge">held</span>}
      </li>)}</ul>
    </div>)}</div>}
    {data && <p className="market-sub">* = providers disagree, earlier date shown. Holding shares through the ex-dividend date earns the dividend;
      short calls in the money near it risk early assignment. Dates come from Finnhub/Yahoo and can move.</p>}
  </div>;
}
