import { useState, useEffect } from 'react';
import { fetchWhyMoving } from '../api/stockApi';

export default function WhyMoving({ ticker, changePct }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setData(null);
    setOpen(false);
    setError(null);
  }, [ticker]);

  const handle = async () => {
    if (open) { setOpen(false); return; }
    setOpen(true);
    if (data) return;
    setLoading(true);
    setError(null);
    try {
      setData(await fetchWhyMoving(ticker));
    } catch (e) {
      setError('Could not fetch explanation.');
    } finally {
      setLoading(false);
    }
  };

  const direction = changePct >= 0 ? 'up' : 'down';
  const cls = changePct >= 0 ? 'positive' : 'negative';

  return (
    <div className="why-moving-wrap">
      <button className={`btn-why ${cls}`} onClick={handle} title="AI explanation of today's move">
        {changePct >= 0 ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}% today — Why?
      </button>
      {open && (
        <div className="why-moving-panel">
          {loading && <span className="loading-text">Analyzing today's move…</span>}
          {error && <span className="error-text">{error}</span>}
          {data && !loading && <p>{data.explanation}</p>}
        </div>
      )}
    </div>
  );
}
