import { useState, useEffect, useRef } from 'react';
import { fetchSummary } from '../api/stockApi';

// Render a single line with **bold** support and bullet detection
function AiLine({ text }) {
  const isBullet = /^[\u2022\-\*]\s/.test(text.trimStart());
  const cleaned = isBullet ? text.replace(/^[\u2022\-\*]\s*/, '') : text;

  const parts = cleaned.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });

  return <p className={isBullet ? 'ai-bullet' : ''}>{parts}</p>;
}

function AiSkeleton() {
  return (
    <div className="ai-skeleton">
      {[80, 95, 70, 90, 55, 85, 60].map((w, i) => (
        <div key={i} className="skeleton-line" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

export default function AiSummary({ ticker, dataReady }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const lastTicker = useRef(null);

  // Auto-generate only after main data has loaded (dataReady=true)
  useEffect(() => {
    if (!ticker || !dataReady || ticker === lastTicker.current) return;
    lastTicker.current = ticker;
    generate();
  });

  const generate = async () => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    setSummary(null);
    try {
      const data = await fetchSummary(ticker);
      setSummary(data.summary);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const lines = summary
    ? summary.split('\n').filter(l => l.trim())
    : [];

  return (
    <div className="card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.5rem' }}>
        <h3 style={{ margin: 0 }}>AI Analysis</h3>
        {(summary || error) && !loading && (
          <button className="btn-secondary btn-sm" onClick={generate}>↻ Regenerate</button>
        )}
      </div>
      {loading && <AiSkeleton />}
      {error && <p className="error-text">{error}</p>}
      {summary && (
        <div className="ai-summary-content">
          {lines.map((line, i) => <AiLine key={i} text={line} />)}
        </div>
      )}
    </div>
  );
}
