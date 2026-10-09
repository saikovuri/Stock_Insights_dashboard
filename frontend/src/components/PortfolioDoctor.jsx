import { useState } from 'react';
import { fetchPortfolioDoctor } from '../api/stockApi';

function scoreClass(score) {
  if (score >= 75) return 'positive';
  if (score < 50) return 'negative';
  return '';
}

export default function PortfolioDoctor() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchPortfolioDoctor());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="portfolio-health" aria-label="Portfolio health">
      <div className="bull-bear-header">
        <h4 style={{ margin: 0 }}>🩺 Portfolio health</h4>
        {data && !data.empty && (
          <span className={`health-score ${scoreClass(data.health_score)}`}>{data.health_score}<small>/100</small></span>
        )}
        <button className="btn-secondary btn-sm" onClick={run} disabled={loading}>
          {loading ? 'Checking…' : data ? '↻ Re-run' : 'Run health check'}
        </button>
      </div>

      {!data && !loading && !error && (
        <p className="market-sub" style={{ margin: '0.3rem 0 0' }}>
          A score plus beta, volatility, drawdown and correlation for your holdings. It downloads a year of prices, so it runs on request.
        </p>
      )}
      {error && <p className="error-text">{error}</p>}
      {data?.empty && <p className="market-sub">Add some holdings first.</p>}

      {data && !data.empty && (
        <>
          <p className="doctor-headline">{data.headline}</p>
          <div className="doctor-stats">
            <div><span>Effective positions</span><strong>{data.effective_positions}</strong></div>
            <div><span>Beta</span><strong>{data.portfolio_beta ?? '—'}</strong></div>
            <div><span>Volatility (1y)</span><strong>{data.risk?.annual_volatility_pct != null ? `${data.risk.annual_volatility_pct}%` : '—'}</strong></div>
            <div><span>Max drawdown (1y)</span><strong>{data.risk?.max_drawdown_1y_pct != null ? `${data.risk.max_drawdown_1y_pct}%` : '—'}</strong></div>
            <div><span>Avg correlation</span><strong>{data.risk?.avg_pairwise_correlation ?? '—'}</strong></div>
            <div><span>Largest position</span><strong>{data.positions[0].ticker} {data.positions[0].weight_pct}%</strong></div>
          </div>

          <details className="setup-guide">
            <summary>Strengths, risks and things to consider</summary>
            <div className="bull-bear-grid">
              {data.strengths?.length > 0 && (
                <div className="bull-col bull-bear-col">
                  <div className="bull-bear-col-header">Strengths</div>
                  <ul>{data.strengths.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
              )}
              {data.risks?.length > 0 && (
                <div className="bear-col bull-bear-col">
                  <div className="bull-bear-col-header">Risks</div>
                  <ul>{data.risks.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
              )}
            </div>
            {data.actions?.length > 0 && (
              <div className="bull-bear-col ai-brief-neutral">
                <div className="bull-bear-col-header">Things to consider</div>
                <ul>{data.actions.map((s, i) => <li key={i}>{s}</li>)}</ul>
              </div>
            )}
            {(data.tax_loss_candidates?.length > 0 || data.upcoming_earnings?.length > 0) && (
              <div className="doctor-extras">
                {data.tax_loss_candidates?.length > 0 && (
                  <p>💸 Tax-loss candidates: {data.tax_loss_candidates.map(t => `${t.ticker} (${t.pnl_pct.toFixed(1)}%)`).join(', ')}</p>
                )}
                {data.upcoming_earnings?.length > 0 && (
                  <p>📅 Earnings in 2 weeks: {data.upcoming_earnings.map(e => `${e.ticker} ${e.date}`).join(', ')}</p>
                )}
              </div>
            )}
            <p className="ai-brief-meta">{data.ai ? 'AI review' : 'Rule-based review'} · Educational only, not financial advice</p>
          </details>
        </>
      )}
    </section>
  );
}
