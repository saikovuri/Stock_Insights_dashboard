import { useState, useEffect, useMemo } from 'react';
import { fetchFinancials } from '../api/stockApi';

const TABS = [
  { id: 'income', label: 'Income Statement' },
  { id: 'balance', label: 'Balance Sheet' },
  { id: 'cashflow', label: 'Cash Flow' },
];

function formatVal(v) {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

export default function Financials({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('income');
  const [quarterly, setQuarterly] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setData(null);
    fetchFinancials(ticker)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ticker]);

  const tableData = useMemo(() => {
    if (!data) return null;
    const key = activeTab === 'income'
      ? (quarterly ? 'income_statement_quarterly' : 'income_statement')
      : activeTab === 'balance'
      ? (quarterly ? 'balance_sheet_quarterly' : 'balance_sheet')
      : (quarterly ? 'cash_flow_quarterly' : 'cash_flow');
    const sheet = data[key];
    if (!sheet || Object.keys(sheet).length === 0) return null;

    const periods = Object.keys(sheet).sort().reverse();
    // Collect all row labels across all periods
    const rowSet = new Set();
    periods.forEach(p => Object.keys(sheet[p]).forEach(k => rowSet.add(k)));
    const rows = Array.from(rowSet);

    return { periods, rows, sheet };
  }, [data, activeTab, quarterly]);

  if (!ticker) return null;
  if (loading) return <div className="glass-card financials-card"><p className="loading-text">Loading financials…</p></div>;
  if (!data) return null;

  return (
    <div className="glass-card financials-card">
      <h3>📑 Financial Statements</h3>

      <div className="financials-controls">
        <div className="financials-tabs">
          {TABS.map(t => (
            <button
              key={t.id}
              className={`fin-tab ${activeTab === t.id ? 'active' : ''}`}
              onClick={() => setActiveTab(t.id)}
            >{t.label}</button>
          ))}
        </div>
        <button
          className={`btn-toggle-sm ${quarterly ? 'active' : ''}`}
          onClick={() => setQuarterly(!quarterly)}
        >{quarterly ? 'Quarterly' : 'Annual'}</button>
      </div>

      {tableData ? (
        <div className="financials-table-wrap">
          <table className="financials-table">
            <thead>
              <tr>
                <th className="fin-row-label">Item</th>
                {tableData.periods.map(p => (
                  <th key={p}>{p}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tableData.rows.map(row => (
                <tr key={row}>
                  <td className="fin-row-label">{row.replace(/([A-Z])/g, ' $1').trim()}</td>
                  {tableData.periods.map(p => {
                    const v = tableData.sheet[p]?.[row];
                    return (
                      <td key={p} className={v != null && v < 0 ? 'negative' : ''}>
                        {formatVal(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="no-data-text">No financial data available.</p>
      )}
    </div>
  );
}
