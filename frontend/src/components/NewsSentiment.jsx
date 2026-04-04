import { useState } from 'react';

const sentimentColor = { Positive: '#00b894', Negative: '#d63031', Neutral: '#636e72' };
const sentimentIcon = { Positive: '🟢', Negative: '🔴', Neutral: '⚪' };
const PAGE_SIZE = 5;

function getSentimentDesc(avg) {
  if (avg >= 0.5) return 'Very Bullish';
  if (avg >= 0.25) return 'Bullish';
  if (avg >= 0.1) return 'Slightly Bullish';
  if (avg > -0.1) return 'Neutral';
  if (avg > -0.25) return 'Slightly Bearish';
  if (avg > -0.5) return 'Bearish';
  return 'Very Bearish';
}

function SentimentGauge({ value }) {
  // value is -1 to +1, map to 0-100% for the bar
  const pct = Math.round(((value + 1) / 2) * 100);
  const clampedPct = Math.max(5, Math.min(95, pct));
  const color = value > 0.1 ? '#00b894' : value < -0.1 ? '#d63031' : '#636e72';

  return (
    <div className="sentiment-gauge">
      <div className="gauge-labels">
        <span>Bearish</span>
        <span>{getSentimentDesc(value)}</span>
        <span>Bullish</span>
      </div>
      <div className="gauge-track">
        <div className="gauge-fill" style={{ width: `${clampedPct}%`, background: color }} />
        <div className="gauge-marker" style={{ left: `${clampedPct}%` }} />
      </div>
    </div>
  );
}

function ContrarianBadge({ articles }) {
  if (!articles || articles.length < 5) return null;
  const recent = articles.slice(0, 8);
  const posCount = recent.filter(a => a.sentiment_label === 'Positive').length;
  const negCount = recent.filter(a => a.sentiment_label === 'Negative').length;

  if (posCount >= 6) {
    return (
      <div className="contrarian-badge contrarian-bearish">
        <span className="contrarian-icon">⚠️</span>
        <div>
          <strong>Extreme optimism detected</strong>
          <div className="contrarian-desc">
            {posCount}/{recent.length} recent articles are bullish — a contrarian indicator of a potential pullback.
          </div>
        </div>
      </div>
    );
  }
  if (negCount >= 6) {
    return (
      <div className="contrarian-badge contrarian-bullish">
        <span className="contrarian-icon">📉</span>
        <div>
          <strong>Extreme fear detected</strong>
          <div className="contrarian-desc">
            {negCount}/{recent.length} recent articles are bearish — a contrarian indicator of a potential bounce.
          </div>
        </div>
      </div>
    );
  }
  return null;
}

export default function NewsSentiment({ newsData }) {
  const [page, setPage] = useState(0);

  if (!newsData) return null;

  const { articles, sentiment } = newsData;
  const totalPages = Math.ceil(articles.length / PAGE_SIZE);
  const sliced = articles.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="card">
      <h3>News &amp; Sentiment</h3>

      <ContrarianBadge articles={articles} />

      <div className="sentiment-summary">
        <SentimentGauge value={sentiment.avg} />
        <div className="sentiment-counts">
          <span className="count positive">🟢 {sentiment.positive} Positive</span>
          <span className="count negative">🔴 {sentiment.negative} Negative</span>
          <span className="count neutral">⚪ {sentiment.neutral} Neutral</span>
        </div>
      </div>

      <ul className="news-list">
        {sliced.map((a, i) => (
          <li key={page * PAGE_SIZE + i} className="news-item">
            <span className="news-icon">{sentimentIcon[a.sentiment_label] || '⚪'}</span>
            <div className="news-content">
              {a.url ? (
                <a href={a.url} target="_blank" rel="noopener noreferrer">{a.title}</a>
              ) : (
                <span>{a.title}</span>
              )}
              <div className="news-meta">
                {a.source && <span className="news-source-chip">{a.source}</span>}
                {a.published && <span className="news-date">{new Date(a.published).toLocaleDateString()}</span>}
              </div>
            </div>
          </li>
        ))}
      </ul>

      {totalPages > 1 && (
        <div className="pagination">
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>&laquo; Prev</button>
          <span className="page-info">{page + 1} / {totalPages}</span>
          <button disabled={page >= totalPages - 1} onClick={() => setPage(page + 1)}>Next &raquo;</button>
        </div>
      )}
    </div>
  );
}
