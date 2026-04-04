function fmt(num) {
  if (num == null) return 'N/A';
  if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
  if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
  if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
  return `$${num.toLocaleString()}`;
}

function RangeBar({ low, high, current }) {
  if (low == null || high == null || current == null || high === low) return null;
  const pct = Math.max(0, Math.min(100, ((current - low) / (high - low)) * 100));
  return (
    <div className="range-bar-wrap" title={`52W range: $${low.toFixed(2)} – $${high.toFixed(2)}`}>
      <div className="range-bar-track">
        <div className="range-bar-fill" style={{ width: `${pct}%` }} />
        <div className="range-bar-thumb" style={{ left: `${pct}%` }} />
      </div>
      <div className="range-bar-labels">
        <span>${low.toFixed(0)}</span>
        <span>${high.toFixed(0)}</span>
      </div>
    </div>
  );
}

export default function KeyMetrics({ metrics }) {
  if (!metrics) return null;

  const changeClass = metrics.change_pct >= 0 ? 'positive' : 'negative';

  return (
    <div className="card">
      <div className="card-header">
        <h2>{metrics.name}</h2>
        <span className="subtitle">{metrics.sector} &middot; {metrics.industry}</span>
      </div>

      <div className="metrics-grid">
        <div className={`metric metric-price ${metrics.change_pct >= 0 ? 'metric-positive' : 'metric-negative'}`}>
          <span className="metric-label">Price</span>
          <span className={`metric-value ${changeClass}`} style={{ fontSize: '1.35rem' }}>
            ${metrics.price?.toFixed(2)}
          </span>
          <span className={`metric-change ${changeClass}`}>
            {metrics.change_pct >= 0 ? '+' : ''}{metrics.change_pct?.toFixed(2)}%
          </span>
          <RangeBar low={metrics['52w_low']} high={metrics['52w_high']} current={metrics.price} />
        </div>
        <div className="metric">
          <span className="metric-label">Market Cap</span>
          <span className="metric-value">{fmt(metrics.market_cap)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">P/E Ratio</span>
          <span className="metric-value">{metrics.pe_ratio?.toFixed(1) ?? 'N/A'}</span>
        </div>
        <div className="metric">
          <span className="metric-label">EPS</span>
          <span className="metric-value">{metrics.eps != null ? `$${metrics.eps.toFixed(2)}` : 'N/A'}</span>
        </div>
        <div className="metric">
          <span className="metric-label">52W High</span>
          <span className="metric-value">${metrics['52w_high']?.toFixed(2)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">52W Low</span>
          <span className="metric-value">${metrics['52w_low']?.toFixed(2)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Volume</span>
          <span className="metric-value">{metrics.volume?.toLocaleString()}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Avg Volume</span>
          <span className="metric-value">{metrics.avg_volume?.toLocaleString()}</span>
        </div>
        <div className="metric">
          <span className="metric-label">50D Avg</span>
          <span className="metric-value">${metrics['50d_avg']?.toFixed(2)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">200D Avg</span>
          <span className="metric-value">${metrics['200d_avg']?.toFixed(2)}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Beta</span>
          <span className="metric-value">{metrics.beta?.toFixed(2) ?? 'N/A'}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Div Yield</span>
          <span className="metric-value">
            {metrics.dividend_yield != null ? `${metrics.dividend_yield.toFixed(2)}%` : 'N/A'}
          </span>
        </div>
      </div>
    </div>
  );
}
