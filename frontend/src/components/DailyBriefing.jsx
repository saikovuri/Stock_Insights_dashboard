import { useState, useEffect } from 'react';
import { fetchBriefing } from '../api/stockApi';

export default function DailyBriefing({ onSelect }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async (refresh = false) => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchBriefing(refresh));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  if (data?.empty) {
    return <p className="market-sub briefing-empty">Add holdings or watchlist stocks to get a personal daily briefing here.</p>;
  }

  const movers = data?.data?.movers || [];

  return (
    <section className="daily-briefing" aria-label="Your briefing">
      <div className="bull-bear-header">
        <h4 style={{ margin: 0 }}>📰 {data?.title || 'Your briefing'}</h4>
        <button className="btn-secondary btn-sm" onClick={() => load(true)} disabled={loading}>
          {loading ? 'Loading…' : '↻ Refresh'}
        </button>
      </div>
      {loading && !data && <div className="ai-skeleton"><div className="skeleton-line" style={{ width: '90%' }} /><div className="skeleton-line" style={{ width: '70%' }} /></div>}
      {error && <p className="error-text">{error}</p>}
      {data && (
        <>
          <p className="briefing-body">{data.body}</p>
          {movers.length > 0 && (
            <div className="ai-brief-signals">
              {movers.map(q => (
                <button key={q.ticker} className={`signal-chip ${q.change_pct >= 0 ? 'signal-bullish' : 'signal-bearish'}`}
                  onClick={() => onSelect?.(q.ticker)}>
                  {q.ticker} {q.change_pct >= 0 ? '+' : ''}{q.change_pct?.toFixed(2)}%
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
