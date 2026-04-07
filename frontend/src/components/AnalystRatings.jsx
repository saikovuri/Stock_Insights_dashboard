import { useState, useEffect } from 'react';
import { fetchAnalyst } from '../api/stockApi';

export default function AnalystRatings({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showUpgrades, setShowUpgrades] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setData(null);
    fetchAnalyst(ticker)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (!ticker) return null;
  if (loading) return <div className="glass-card analyst-card"><p className="loading-text">Loading analyst data…</p></div>;
  if (!data) return null;

  const { price_targets: pt, recommendation, recommendation_mean, breakdown, upgrades_downgrades } = data;
  const totalRatings = Object.values(breakdown).reduce((a, b) => a + b, 0);

  const ratingColors = {
    strongBuy: '#00c853',
    buy: '#66bb6a',
    hold: '#ffa726',
    sell: '#ef5350',
    strongSell: '#c62828',
  };
  const ratingLabels = {
    strongBuy: 'Strong Buy',
    buy: 'Buy',
    hold: 'Hold',
    sell: 'Sell',
    strongSell: 'Strong Sell',
  };

  const recLabel = recommendation
    ? recommendation.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())
    : 'N/A';

  const recColor = recommendation_mean
    ? recommendation_mean <= 1.5 ? '#00c853'
      : recommendation_mean <= 2.5 ? '#66bb6a'
      : recommendation_mean <= 3.5 ? '#ffa726'
      : recommendation_mean <= 4.5 ? '#ef5350'
      : '#c62828'
    : '#999';

  return (
    <div className="glass-card analyst-card">
      <h3>📊 Analyst Ratings & Price Targets</h3>

      {/* Consensus & Price Targets */}
      <div className="analyst-top-row">
        <div className="analyst-consensus">
          <div className="analyst-consensus-label" style={{ color: recColor }}>
            {recLabel}
          </div>
          {recommendation_mean && (
            <div className="analyst-mean-score">{recommendation_mean.toFixed(1)} / 5.0</div>
          )}
          <div className="analyst-count">{pt.num_analysts || totalRatings} analyst{(pt.num_analysts || totalRatings) !== 1 ? 's' : ''}</div>
        </div>

        {pt.mean && (
          <div className="analyst-targets">
            <div className="analyst-target-row">
              <span className="target-label">Low</span>
              <span className="target-value target-low">${pt.low?.toFixed(2)}</span>
            </div>
            <div className="analyst-target-row target-mean-row">
              <span className="target-label">Mean</span>
              <span className="target-value target-mean">${pt.mean?.toFixed(2)}</span>
            </div>
            <div className="analyst-target-row">
              <span className="target-label">High</span>
              <span className="target-value target-high">${pt.high?.toFixed(2)}</span>
            </div>
            {pt.median && (
              <div className="analyst-target-row">
                <span className="target-label">Median</span>
                <span className="target-value">${pt.median?.toFixed(2)}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Rating breakdown bar */}
      {totalRatings > 0 && (
        <div className="analyst-breakdown">
          <div className="analyst-bar">
            {['strongBuy', 'buy', 'hold', 'sell', 'strongSell'].map(key => {
              const count = breakdown[key];
              if (!count) return null;
              const pct = (count / totalRatings * 100).toFixed(1);
              return (
                <div
                  key={key}
                  className="analyst-bar-seg"
                  style={{ width: `${pct}%`, background: ratingColors[key] }}
                  title={`${ratingLabels[key]}: ${count}`}
                >
                  {pct >= 12 && <span>{count}</span>}
                </div>
              );
            })}
          </div>
          <div className="analyst-bar-legend">
            {['strongBuy', 'buy', 'hold', 'sell', 'strongSell'].map(key => (
              breakdown[key] > 0 && (
                <span key={key} className="legend-item">
                  <span className="legend-dot" style={{ background: ratingColors[key] }}></span>
                  {ratingLabels[key]} ({breakdown[key]})
                </span>
              )
            ))}
          </div>
        </div>
      )}

      {/* Upgrades / Downgrades */}
      {upgrades_downgrades?.length > 0 && (
        <div className="analyst-upgrades">
          <button className="btn-toggle-sm" onClick={() => setShowUpgrades(!showUpgrades)}>
            {showUpgrades ? 'Hide' : 'Show'} Recent Upgrades/Downgrades ({upgrades_downgrades.length})
          </button>
          {showUpgrades && (
            <table className="analyst-table">
              <thead>
                <tr><th>Date</th><th>Firm</th><th>Action</th><th>From</th><th>To</th></tr>
              </thead>
              <tbody>
                {upgrades_downgrades.map((u, i) => (
                  <tr key={i}>
                    <td>{u.date}</td>
                    <td>{u.firm}</td>
                    <td className={`action-${u.action?.toLowerCase()}`}>{u.action}</td>
                    <td>{u.fromGrade || '—'}</td>
                    <td>{u.toGrade}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
