import { useState, useEffect } from 'react';
import { fetchRelativeStrength } from '../api/stockApi';

const SHORT = { breakout: 'Breakout', pullback: 'Pullback', squeeze: 'Squeeze', oversold: 'Oversold', golden_cross: 'Golden cross' };

export default function RelativeStrength({ ticker }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    setData(null);
    fetchRelativeStrength(ticker).then(setData).catch(() => setData(null));
  }, [ticker]);

  if (!data) return null;
  const rs = data.rs_rating;
  const label = rs == null ? 'Not ranked yet' : rs >= 80 ? 'Market leader' : rs >= 60 ? 'Above average' : rs >= 40 ? 'Average' : 'Laggard';

  return (
    <div className="card rs-card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>💪 Relative Strength</h3>
        {rs != null && <span className={`rs-badge rs-big ${rs >= 80 ? 'rs-strong' : rs >= 50 ? 'rs-mid' : 'rs-weak'}`}>RS {rs}</span>}
      </div>
      <p className="ivrank-verdict-desc">
        {label}
        {rs != null && ` — outperformed ${rs}% of S&P 500 stocks over the past year (recent months weighted more).`}
        {data.sector && data.sector_rank && ` Sector: ${data.sector} (#${data.sector_rank} of ${data.sector_count}).`}
      </p>
      <div className="doctor-stats">
        {Object.entries(data.vs_spy).map(([k, v]) => (
          <div key={k}><span>{k.toUpperCase()} vs S&P 500</span><strong className={v >= 0 ? 'positive' : 'negative'}>{v != null ? `${v > 0 ? '+' : ''}${v}%` : '—'}</strong></div>
        ))}
      </div>
      {data.setups?.length > 0 && (
        <div className="ai-brief-signals">
          {data.setups.map(s => <span key={s} className="signal-chip signal-bullish">Setup: {SHORT[s] || s}</span>)}
        </div>
      )}
    </div>
  );
}
