import { useState, useEffect, useMemo } from 'react';
import { fetchDividends } from '../api/stockApi';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';

export default function DividendHistory({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setData(null);
    fetchDividends(ticker)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ticker]);

  // Annual aggregation for chart
  const annualData = useMemo(() => {
    if (!data?.history?.length) return [];
    const byYear = {};
    data.history.forEach(d => {
      const yr = d.date.slice(0, 4);
      byYear[yr] = (byYear[yr] || 0) + d.amount;
    });
    return Object.entries(byYear)
      .map(([year, total]) => ({ year, total: +total.toFixed(4) }))
      .sort((a, b) => a.year.localeCompare(b.year))
      .slice(-10);
  }, [data]);

  // Upcoming dividends (most recent + next)
  const upcoming = useMemo(() => {
    if (!data?.history?.length) return [];
    return data.history.slice(-4).reverse();
  }, [data]);

  if (!ticker) return null;
  if (loading) return <div className="glass-card dividend-card"><p className="loading-text">Loading dividend data…</p></div>;
  if (!data) return null;

  const noDividend = !data.dividend_rate && (!data.history || data.history.length === 0);
  if (noDividend) return (
    <div className="glass-card dividend-card">
      <h3>💰 Dividends</h3>
      <p className="no-data-text">This stock does not pay a dividend.</p>
    </div>
  );

  return (
    <div className="glass-card dividend-card">
      <h3>💰 Dividend History</h3>

      {/* Key stats row */}
      <div className="dividend-stats">
        {data.dividend_yield != null && (
          <div className="div-stat">
            <span className="div-stat-val">{data.dividend_yield.toFixed(2)}%</span>
            <span className="div-stat-label">Yield</span>
          </div>
        )}
        {data.dividend_rate != null && (
          <div className="div-stat">
            <span className="div-stat-val">${data.dividend_rate.toFixed(2)}</span>
            <span className="div-stat-label">Annual Rate</span>
          </div>
        )}
        {data.payout_ratio != null && (
          <div className="div-stat">
            <span className="div-stat-val">{data.payout_ratio.toFixed(1)}%</span>
            <span className="div-stat-label">Payout Ratio</span>
          </div>
        )}
        {data.ex_dividend_date && (
          <div className="div-stat">
            <span className="div-stat-val">{data.ex_dividend_date}</span>
            <span className="div-stat-label">Ex-Date</span>
          </div>
        )}
        {data.five_year_avg_yield != null && (
          <div className="div-stat">
            <span className="div-stat-val">{data.five_year_avg_yield.toFixed(2)}%</span>
            <span className="div-stat-label">5Y Avg Yield</span>
          </div>
        )}
      </div>

      {/* Annual dividend chart */}
      {annualData.length > 1 && (
        <div className="dividend-chart">
          <h4>Annual Dividend Per Share</h4>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={annualData}>
              <XAxis dataKey="year" tick={{ fill: '#b0b8c8', fontSize: 11 }} />
              <YAxis tick={{ fill: '#b0b8c8', fontSize: 11 }} tickFormatter={v => `$${v}`} width={50} />
              <Tooltip
                contentStyle={{ background: 'rgba(30,30,50,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, color: '#fff' }}
                formatter={(v) => [`$${v.toFixed(4)}`, 'Dividend']}
              />
              <Bar dataKey="total" fill="#66bb6a" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent payments */}
      {upcoming.length > 0 && (
        <div className="dividend-recent">
          <h4>Recent Payments</h4>
          <div className="dividend-list">
            {upcoming.map((d, i) => (
              <div key={i} className="dividend-item">
                <span className="div-date">{d.date}</span>
                <span className="div-amount">${d.amount.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
