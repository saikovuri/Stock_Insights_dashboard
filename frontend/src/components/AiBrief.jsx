import { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { fetchBrief, addCustomAlert } from '../api/stockApi';

const RULE_LEVELS = {
  prev_day_high: 'Previous day high', prev_day_low: 'Previous day low',
  high_20d: '20-day high', low_20d: '20-day low',
};

function KeyLevels({ data }) {
  const [set, setSet] = useState({});
  const price = data.price;
  const seen = new Set();
  const levels = [
    ...(data.key_levels || []),
    ...Object.entries(data.levels || {}).filter(([k]) => RULE_LEVELS[k]).map(([k, p]) => ({ price: p, label: RULE_LEVELS[k] })),
  ].filter(l => {
    const k = l.price.toFixed(2);
    if (seen.has(k) || !price) return false;
    seen.add(k);
    return true;
  }).sort((a, b) => b.price - a.price);
  if (!levels.length) return null;

  const add = async (l) => {
    const kind = l.price >= price ? 'price_above' : 'price_below';
    setSet(s => ({ ...s, [l.price]: 'saving' }));
    try {
      await addCustomAlert({ ticker: data.ticker, kind, value: l.price, note: l.label || null });
      setSet(s => ({ ...s, [l.price]: 'done' }));
    } catch (e) {
      setSet(s => ({ ...s, [l.price]: e.message }));
    }
  };

  return (
    <div className="key-levels">
      <div className="bull-bear-col-header">🎯 Key levels · now ${price}</div>
      <ul>
        {levels.map(l => {
          const state = set[l.price];
          const dist = ((l.price / price - 1) * 100).toFixed(1);
          return (
            <li key={l.price}>
              <strong className={l.price >= price ? 'positive' : 'negative'}>${l.price}</strong>
              <span className="market-sub"> ({dist > 0 ? '+' : ''}{dist}%)</span> {l.label}
              <button className="btn-secondary btn-sm key-level-btn" onClick={() => add(l)} disabled={!!state}
                title={`Alert when price ${l.price >= price ? 'rises above' : 'falls below'} $${l.price}`}>
                {state === 'done' ? '✓ Alert set' : state === 'saving' ? '…' : state ? '⚠' : '🔔 Alert me'}
              </button>
              {state && !['done', 'saving'].includes(state) && <span className="error-text"> {state}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

const STANCE = {
  bullish: { icon: '🐂', cls: 'positive', label: 'Bullish' },
  bearish: { icon: '🐻', cls: 'negative', label: 'Bearish' },
  neutral: { icon: '⚖️', cls: '', label: 'Neutral' },
};

function Skeleton() {
  return (
    <div className="ai-skeleton">
      {[85, 95, 70, 90, 60, 80].map((w, i) => (
        <div key={i} className="skeleton-line" style={{ width: `${w}%` }} />
      ))}
    </div>
  );
}

function List({ title, items, cls }) {
  if (!items?.length) return null;
  return (
    <div className={cls}>
      <div className="bull-bear-col-header">{title}</div>
      <ul>{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
    </div>
  );
}

export default function AiBrief({ ticker, profile, onSignIn }) {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchBrief(ticker, profile));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setData(null);
    setError(null);
    if (user && ticker) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, user, profile]);

  if (!user) {
    return (
      <div className="card ai-brief">
        <h3>🤖 AI Brief</h3>
        <p className="empty-state">Sign in to get an AI research brief: why {ticker} is moving, bull vs bear case, risks and catalysts.</p>
        {onSignIn && <button className="btn-primary btn-sm" onClick={onSignIn}>Sign in</button>}
      </div>
    );
  }

  const stance = STANCE[data?.stance] || STANCE.neutral;

  return (
    <div className="card ai-brief">
      <div className="bull-bear-header">
        <h3 style={{ margin: 0 }}>🤖 AI Brief</h3>
        <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? 'Analyzing…' : '↻ Refresh'}
        </button>
      </div>

      {loading && !data && <Skeleton />}
      {error && <p className="error-text">{error}</p>}

      {data && (
        <>
          <div className="ai-brief-stance">
            <span className={`ai-brief-badge ${stance.cls}`}>{stance.icon} {stance.label}</span>
            <span className="ai-brief-confidence">Confidence: {data.confidence}</span>
            {!data.ai && <span className="ai-brief-confidence">Rule-based</span>}
          </div>

          {data.summary && <p className="ai-brief-summary">{data.summary}</p>}
          {data.why_moving && (
            <div className="why-moving-panel">
              <strong>{data.change_pct >= 0 ? '▲' : '▼'} {Math.abs(data.change_pct ?? 0).toFixed(2)}% today — </strong>
              {data.why_moving}
            </div>
          )}

          {data.signals?.length > 0 && (
            <div className="ai-brief-signals">
              {data.signals.map((s, i) => (
                <span key={i} className={`signal-chip signal-${s.stance}`}>{s.label}</span>
              ))}
            </div>
          )}

          <div className="bull-bear-grid">
            <List title="🐂 Bull case" items={data.bull} cls="bull-col bull-bear-col" />
            <List title="🐻 Bear case" items={data.bear} cls="bear-col bull-bear-col" />
          </div>
          <div className="bull-bear-grid">
            <List title="⚠️ Risks" items={data.risks} cls="bull-bear-col ai-brief-neutral" />
            <List title="👀 What to watch" items={data.watch} cls="bull-bear-col ai-brief-neutral" />
          </div>

          <KeyLevels data={data} />

          {data.verdict && <p className="bull-bear-verdict">⚖️ {data.verdict}</p>}

          {data.citations?.length > 0 && (
            <div className="ai-brief-sources">
              Sources:{' '}
              {data.citations.map(n => {
                const h = data.headlines.find(x => x.n === n);
                if (!h) return null;
                return h.url
                  ? <a key={n} href={h.url} target="_blank" rel="noopener noreferrer" title={h.title}>[{n}] {h.source}</a>
                  : <span key={n} title={h.title}>[{n}] {h.source}</span>;
              })}
            </div>
          )}

          <p className="ai-brief-meta">
            {data.model ? `${data.model} · ` : ''}updated {new Date(data.generated_at).toLocaleTimeString()} · Not financial advice
          </p>
        </>
      )}
    </div>
  );
}
