import { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { useProfile } from '../ProfileContext';
import { fetchMarketOverview, fetchMovers, fetchMyEarnings } from '../api/stockApi';
import Skeleton from './Skeleton';
import DailyBriefing from './DailyBriefing';

function pct(v, digits = 2) {
  if (v == null) return '—';
  return `${v >= 0 ? '+' : ''}${Number(v).toFixed(digits)}%`;
}

function heat(v) {
  if (v == null) return 'var(--surface)';
  const a = Math.min(Math.abs(v) / 3, 1) * 0.55 + 0.08;
  return v >= 0 ? `rgba(38,166,154,${a})` : `rgba(239,83,80,${a})`;
}

function Movers({ onSelect }) {
  const [kind, setKind] = useState('gainers');
  const [items, setItems] = useState(null);
  useEffect(() => {
    setItems(null);
    fetchMovers(kind).then(d => setItems(d.items)).catch(() => setItems([]));
  }, [kind]);
  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🚀 Top movers</h3>
        <div className="chart-toggle">
          {[['gainers', 'Gainers'], ['losers', 'Losers'], ['active', 'Most active']].map(([k, l]) => (
            <button key={k} className={kind === k ? 'active' : ''} onClick={() => setKind(k)}>{l}</button>
          ))}
        </div>
      </div>
      {!items ? <Skeleton label="Loading movers" /> : items.length === 0 ? <p className="empty-state">No data (market may be closed).</p> : (
        <table className="market-table">
          <thead><tr><th>Symbol</th><th>Price</th><th>Change</th><th title="Volume vs 3-month average">Rel. vol</th></tr></thead>
          <tbody>
            {items.map(m => (
              <tr key={m.symbol} onClick={() => onSelect(m.symbol)}>
                <td><strong>{m.symbol}</strong><div className="market-sub">{m.name}</div></td>
                <td>${m.price?.toFixed(2)}</td>
                <td className={m.change_pct >= 0 ? 'positive' : 'negative'}>{pct(m.change_pct)}</td>
                <td className={m.rvol >= 2 ? 'positive' : ''}>{m.rvol != null ? `${m.rvol}×` : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Sectors({ sectors, onSelect }) {
  const [range, setRange] = useState('change_pct');
  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🗺️ Sectors</h3>
        <div className="chart-toggle">
          {[['change_pct', 'Today'], ['r1w', '1W'], ['r1m', '1M'], ['r3m', '3M']].map(([k, l]) => (
            <button key={k} className={range === k ? 'active' : ''} onClick={() => setRange(k)}>{l}</button>
          ))}
        </div>
      </div>
      <div className="sector-heatmap">
        {[...sectors].sort((a, b) => (b[range] ?? -99) - (a[range] ?? -99)).map(s => (
          <button key={s.symbol} className="sector-tile" style={{ background: heat(range === 'change_pct' ? s[range] : (s[range] ?? 0) / 3) }}
            onClick={() => onSelect(s.symbol)} title={`${s.name} (${s.symbol})`}>
            <span className="sector-name">{s.name}</span>
            <span className="sector-val">{pct(s[range], 1)}</span>
            <span className="sector-sym">{s.symbol}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function MarketOverview({ onSelect }) {
  const { user } = useAuth();
  const { profile } = useProfile();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [earnings, setEarnings] = useState(null);

  useEffect(() => {
    const load = () => fetchMarketOverview().then(setData).catch(e => setError(e.message));
    load();
    const id = setInterval(load, 90_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (user) fetchMyEarnings().then(d => setEarnings(d.items)).catch(() => {});
  }, [user]);

  if (error && !data) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <Skeleton label="Loading market overview" lines={1} tiles={6} card />;

  const regimeCls = data.regime.trend === 'uptrend' ? 'positive' : data.regime.trend === 'downtrend' ? 'negative' : '';
  const movers = <Movers key="movers" onSelect={onSelect} />;
  const sectors = <Sectors key="sectors" sectors={data.sectors} onSelect={onSelect} />;

  return (
    <div className="market-overview">
      <section className="card market-regime" aria-label="Today">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>☀️ Today</h3>
          <div className="market-status">
            <span className={`market-dot market-${data.status.state.replace(' ', '-')}`} />
            Market {data.status.state} · {data.status.time_et}
            {data.updated_at && <span className="as-of"> · quotes updated {new Date(data.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>}
          </div>
        </div>
        <p className={`market-regime-text ${regimeCls}`}>{data.regime.summary}</p>
        <div className="market-tiles">
          {[...data.indexes, data.vix, data.ten_year].map(t => (
            <button key={t.symbol} className="market-tile" onClick={() => !t.symbol.startsWith('^') && onSelect(t.symbol)}>
              <span className="market-tile-name">{t.name}</span>
              <span className="market-tile-price">{t.symbol === '^TNX' ? `${t.price}%` : t.price != null ? t.price.toLocaleString(undefined, { maximumFractionDigits: 2 }) : '—'}</span>
              <span className={t.change_pct >= 0 ? 'positive' : 'negative'}>{pct(t.change_pct)}</span>
              {t.r1m != null && <span className="market-sub">1M {pct(t.r1m, 1)}</span>}
            </button>
          ))}
        </div>
        {user && <DailyBriefing onSelect={onSelect} />}
        {earnings && earnings.length > 0 && (
          <div className="today-earnings">
            <h4>📅 Your stocks reporting in the next 2 weeks</h4>
            <div className="ai-brief-signals">
              {earnings.map(e => (
                <button key={e.ticker + e.date} className="signal-chip" onClick={() => onSelect(e.ticker)}>
                  {e.ticker} · {new Date(e.date + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                  {e.hour === 'bmo' ? ' (pre-market)' : e.hour === 'amc' ? ' (after close)' : ''}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <div className="two-column">
        {profile === 'long' ? [sectors, movers] : [movers, sectors]}
      </div>
    </div>
  );
}
