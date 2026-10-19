import { useCallback, useEffect, useState } from 'react';
import { fetchPaperTrades, closePaperTrade, deletePaperTrade } from '../api/stockApi';
import Skeleton from './Skeleton';

const money = value => value == null ? 'Unavailable'
  : `${value < 0 ? '-' : ''}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const pnlClass = value => (value > 0 ? 'positive' : value < 0 ? 'negative' : '');
const STATUS = { open: 'Open', closed: 'Closed', expired: 'Expired' };

/** Practice positions recorded from suggested ideas, tracked apart from real holdings and P&L. */
export default function PaperTrades() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [message, setMessage] = useState(null);
  const load = useCallback(() => {
    setError(null);
    fetchPaperTrades().then(setData).catch(reason => setError(reason.message));
  }, []);
  useEffect(() => { load(); }, [load]);
  const act = async (trade, kind) => {
    if (kind === 'delete' && !window.confirm(`Delete this ${trade.ticker} paper trade? It will drop out of your paper results.`)) return;
    setBusy(trade.id); setMessage(null);
    try {
      if (kind === 'close') {
        const result = await closePaperTrade(trade.id);
        setMessage(`Closed ${trade.ticker} ${trade.structure} at a realistic fill: ${money(result.pnl)}.`);
      } else {
        await deletePaperTrade(trade.id);
        setMessage(`Deleted the ${trade.ticker} paper trade.`);
      }
      load();
    } catch (reason) { setMessage(reason.message); }
    finally { setBusy(null); }
  };
  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <Skeleton label="Loading paper trades" lines={2} />;
  const { stats } = data;
  return <section className="portfolio-section paper-trades">
    <h3>Paper trades</h3>
    <p className="structures-intro">Test the app&apos;s ideas without real money. Use 📝 Paper trade on an idea card (Income, Wheel or Directional);
      it is recorded at a realistic fill quoted at that moment and tracked here to expiry. Paper trades never touch your portfolio, cash or real P&L.</p>
    {message && <p role="status">{message}</p>}
    <div className="doctor-stats" aria-label="Paper results">
      <div><span>Open</span><strong>{stats.open}</strong></div>
      <div><span>Closed</span><strong>{stats.closed}</strong></div>
      <div><span>Win rate</span><strong>{stats.win_rate == null ? '—' : `${stats.win_rate}%`}</strong></div>
      <div><span>Realized P&L</span><strong className={pnlClass(stats.realized)}>{money(stats.realized)}</strong></div>
      <div><span>Open P&L</span><strong className={pnlClass(stats.unrealized)}>{stats.open ? money(stats.unrealized) : '—'}</strong></div>
    </div>
    {!data.trades.length ? <p className="empty-state">No paper trades yet.</p> : <div className="table-scroll">
      <table className="market-table phone-cards" aria-label="Paper trades">
        <thead><tr><th>Trade</th><th>Opened</th><th>Expiry</th><th>Entry</th><th>Now / exit</th><th>P&L</th><th><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>{data.trades.map(t => {
          const open = t.status === 'open';
          const pnl = open ? t.unrealized : t.pnl;
          return <tr key={t.id}>
            <td><strong>{t.ticker}</strong> {t.structure} {t.strikes} <span className="market-sub">× {t.contracts}</span>
              {t.label && <div className="market-sub">{t.label}</div>}</td>
            <td data-label="Opened">{String(t.opened_at).slice(0, 10)}</td>
            <td data-label="Expiry">{t.expiry}</td>
            <td data-label="Entry">{t.style} ${Math.abs(t.entry).toFixed(2)}</td>
            <td data-label={open ? 'Mark' : STATUS[t.status]}>{open ? (t.mark == null ? 'No quote' : `$${Math.abs(t.mark).toFixed(2)}`)
              : t.status === 'expired' ? `Settled at $${t.settle_price}` : `$${Math.abs(t.exit_value).toFixed(2)}`}</td>
            <td data-label={open ? 'Open P&L' : 'P&L'} className={pnlClass(pnl)}>{money(pnl)}</td>
            <td className="closed-option-actions">
              {open && <button type="button" className="btn-secondary btn-sm" disabled={busy === t.id} aria-label={`Close ${t.ticker} paper trade`}
                onClick={() => act(t, 'close')}>Close now</button>}
              <button type="button" className="btn-icon" disabled={busy === t.id} aria-label={`Delete ${t.ticker} paper trade`} title="Delete"
                onClick={() => act(t, 'delete')}>🗑</button>
            </td>
          </tr>;
        })}</tbody>
      </table>
    </div>}
    <p className="market-sub">{data.note}</p>
  </section>;
}
