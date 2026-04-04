import { useState, useEffect } from 'react';
import { fetchBullBear } from '../api/stockApi';

function AiSkeleton({ rows = 3 }) {
  return (
    <div className="ai-skeleton">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-line" style={{ width: `${70 + (i % 3) * 10}%` }} />
      ))}
    </div>
  );
}

export default function BullBear({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null);
    setError(null);
  }, [ticker]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchBullBear(ticker));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="card">
      <div className="bull-bear-header">
        <h3 style={{ margin: 0 }}>🐂 Bull vs 🐻 Bear</h3>
        <button
          className="btn-secondary btn-sm"
          onClick={data ? () => setData(null) : load}
          disabled={loading}
        >
          {data ? '↺ Refresh' : loading ? 'Analyzing…' : 'Generate'}
        </button>
      </div>

      {loading && <AiSkeleton rows={6} />}
      {error && <p className="error-text">{error}</p>}

      {data && !loading && (
        <>
          <div className="bull-bear-grid">
            <div className="bull-col">
              <div className="bull-bear-col-header positive">🐂 Bull Case</div>
              <ul>
                {data.bull.map((pt, i) => <li key={i}>{pt}</li>)}
              </ul>
            </div>
            <div className="bear-col">
              <div className="bull-bear-col-header negative">🐻 Bear Case</div>
              <ul>
                {data.bear.map((pt, i) => <li key={i}>{pt}</li>)}
              </ul>
            </div>
          </div>
          {data.verdict && (
            <p className="bull-bear-verdict">⚖️ {data.verdict}</p>
          )}
        </>
      )}

      {!data && !loading && !error && (
        <p className="empty-state" style={{ padding: '1rem 0 0' }}>
          Click Generate to see a structured bull and bear case for {ticker}.
        </p>
      )}
    </div>
  );
}
