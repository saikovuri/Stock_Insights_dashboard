import { useState } from 'react';
import { fetchHistory } from '../api/stockApi';

export default function DcaSimulator() {
  const [ticker, setTicker] = useState('');
  const [monthly, setMonthly] = useState('');
  const currentYear = new Date().getFullYear();
  const [startYear, setStartYear] = useState(String(currentYear - 5));
  const [startMonth, setStartMonth] = useState('01');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const months = [
    '01','02','03','04','05','06','07','08','09','10','11','12'
  ];
  const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const years = Array.from({ length: currentYear - 2005 }, (_, i) => String(2006 + i));

  const simulate = async () => {
    if (!ticker || !monthly) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await fetchHistory(ticker.toUpperCase(), 'max', '1mo');
      if (!data || data.length === 0) throw new Error('No history data');

      const startDate = new Date(`${startYear}-${startMonth}-01`);
      const monthlyAmt = parseFloat(monthly);

      let totalInvested = 0;
      let totalShares = 0;
      const rows = [];

      data.forEach(p => {
        const d = new Date(p.date);
        if (d < startDate || p.close == null) return;
        const sharesBought = monthlyAmt / p.close;
        totalShares += sharesBought;
        totalInvested += monthlyAmt;
        rows.push({
          date: d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' }),
          price: p.close,
          sharesBought: sharesBought.toFixed(4),
          totalShares: totalShares.toFixed(4),
          totalInvested,
          portfolioValue: totalShares * p.close,
        });
      });

      if (rows.length === 0) throw new Error('No data after selected start date');

      const latest = rows[rows.length - 1];
      const currentValue = latest.portfolioValue;
      const returnPct = ((currentValue - totalInvested) / totalInvested) * 100;
      const avgCost = totalInvested / totalShares;

      setResult({ rows, totalInvested, currentValue, returnPct, avgCost, totalShares, ticker: ticker.toUpperCase() });
    } catch (e) {
      setError(typeof e.message === 'string' ? e.message : 'Failed to fetch history data. Check the ticker symbol.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="tool-card">
      <h3>💰 DCA Simulator</h3>
      <p className="tool-desc">Backtest a dollar-cost averaging strategy for any stock.</p>

      <div className="tool-form">
        <div className="tool-row">
          <label>Ticker Symbol</label>
          <input
            type="text"
            className="tool-input"
            placeholder="e.g. AAPL"
            value={ticker}
            onChange={e => setTicker(e.target.value.toUpperCase())}
            onKeyDown={e => e.key === 'Enter' && simulate()}
            maxLength={6}
          />
        </div>
        <div className="tool-row">
          <label>Monthly Investment ($)</label>
          <input
            type="number"
            className="tool-input"
            placeholder="e.g. 200"
            value={monthly}
            onChange={e => setMonthly(e.target.value)}
          />
        </div>
        <div className="tool-row">
          <label>Start Date</label>
          <div className="tool-date-row">
            <select className="tool-input" value={startMonth} onChange={e => setStartMonth(e.target.value)}>
              {months.map((m, i) => <option key={m} value={m}>{monthNames[i]}</option>)}
            </select>
            <select className="tool-input" value={startYear} onChange={e => setStartYear(e.target.value)}>
              {years.map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>

        <button className="btn-primary btn-block" onClick={simulate} disabled={loading || !ticker || !monthly}>
          {loading ? 'Simulating…' : '▶ Run Simulation'}
        </button>
      </div>

      {error && <div className="tool-error">{error}</div>}

      {result && (
        <div className="tool-result">
          <div className="result-grid">
            <div className="result-block">
              <div className="result-label">Total Invested</div>
              <div className="result-value">${result.totalInvested.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            </div>
            <div className="result-block">
              <div className="result-label">Current Value</div>
              <div className={`result-value ${result.currentValue >= result.totalInvested ? 'gain' : 'loss'}`}>
                ${result.currentValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </div>
            </div>
            <div className="result-block">
              <div className="result-label">Total Return</div>
              <div className={`result-value ${result.returnPct >= 0 ? 'gain' : 'loss'}`}>
                {result.returnPct >= 0 ? '+' : ''}{result.returnPct.toFixed(1)}%
              </div>
            </div>
            <div className="result-block">
              <div className="result-label">Avg Cost Basis</div>
              <div className="result-value">${result.avgCost.toFixed(2)}</div>
            </div>
            <div className="result-block">
              <div className="result-label">Total Shares</div>
              <div className="result-value">{parseFloat(result.totalShares).toFixed(2)}</div>
            </div>
            <div className="result-block">
              <div className="result-label">Months DCA'd</div>
              <div className="result-value">{result.rows.length}</div>
            </div>
          </div>

          <details className="dca-history-details">
            <summary>View monthly breakdown ({result.rows.length} months)</summary>
            <div className="dca-table-wrap">
              <table className="peer-table dca-table">
                <thead>
                  <tr>
                    <th>Month</th>
                    <th>Price</th>
                    <th>Shares</th>
                    <th>Total Shares</th>
                    <th>Invested</th>
                    <th>Value</th>
                    <th>P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {result.rows.slice(-24).map((r, i) => {
                    const pl = r.portfolioValue - r.totalInvested;
                    return (
                      <tr key={i}>
                        <td>{r.date}</td>
                        <td>${r.price.toFixed(2)}</td>
                        <td>{r.sharesBought}</td>
                        <td>{r.totalShares}</td>
                        <td>${r.totalInvested.toFixed(0)}</td>
                        <td>${r.portfolioValue.toFixed(0)}</td>
                        <td className={pl >= 0 ? 'positive' : 'negative'}>
                          {pl >= 0 ? '+' : ''}{((pl / r.totalInvested) * 100).toFixed(1)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {result.rows.length > 24 && (
                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'center', margin: '8px 0 0' }}>
                  Showing last 24 months. Total: {result.rows.length} months.
                </p>
              )}
            </div>
          </details>
        </div>
      )}
    </div>
  );
}
