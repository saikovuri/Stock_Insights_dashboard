import { useState, useEffect, useMemo } from 'react';
import { fetchFinancials } from '../api/stockApi';

const TABS = [
  { id: 'income', label: 'Income' },
  { id: 'balance', label: 'Balance Sheet' },
  { id: 'cashflow', label: 'Cash Flow' },
];

// Only the metrics people actually care about per statement
const KEY_METRICS = {
  income: [
    'Total Revenue',
    'Cost Of Revenue',
    'Gross Profit',
    'Operating Income',
    'Net Income',
    'EBITDA',
    'Basic EPS',
    'Diluted EPS',
    'Total Expenses',
    'Operating Expense',
    'Research And Development',
  ],
  balance: [
    'Total Assets',
    'Total Liabilities Net Minority Interest',
    'Total Equity Gross Minority Interest',
    'Stockholders Equity',
    'Cash And Cash Equivalents',
    'Total Debt',
    'Net Debt',
    'Current Assets',
    'Current Liabilities',
    'Long Term Debt',
    'Retained Earnings',
  ],
  cashflow: [
    'Operating Cash Flow',
    'Capital Expenditure',
    'Free Cash Flow',
    'Investing Cash Flow',
    'Financing Cash Flow',
    'Repurchase Of Capital Stock',
    'Cash Dividends Paid',
    'Issuance Of Debt',
    'Repayment Of Debt',
    'Changes In Cash',
  ],
};

function formatVal(v) {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

// Convert camelCase/PascalCase keys from API to readable labels
function labelFromKey(key) {
  return key
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .trim();
}

export default function Financials({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('income');
  const [quarterly, setQuarterly] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    setShowAll(false);
    setLoading(true);
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
    const allRowSet = new Set();
    periods.forEach(p => Object.keys(sheet[p]).forEach(k => allRowSet.add(k)));
    const allRows = Array.from(allRowSet);

    // Filter to key metrics (match by label since API keys are PascalCase)
    const keyList = KEY_METRICS[activeTab] || [];
    const keyRows = [];
    const extraRows = [];

    for (const row of allRows) {
      const label = labelFromKey(row);
      if (keyList.some(km => label.toLowerCase().includes(km.toLowerCase()) || km.toLowerCase().includes(label.toLowerCase()))) {
        keyRows.push(row);
      } else {
        extraRows.push(row);
      }
    }

    // Sort key rows by the order defined in KEY_METRICS
    keyRows.sort((a, b) => {
      const la = labelFromKey(a).toLowerCase();
      const lb = labelFromKey(b).toLowerCase();
      const ia = keyList.findIndex(km => la.includes(km.toLowerCase()) || km.toLowerCase().includes(la));
      const ib = keyList.findIndex(km => lb.includes(km.toLowerCase()) || km.toLowerCase().includes(lb));
      return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    });

    return { periods, keyRows, extraRows, sheet };
  }, [data, activeTab, quarterly]);

  if (!ticker) return null;

  if (loading) return <div className="glass-card financials-card"><p className="loading-text">Loading financials…</p></div>;
  if (!data) return null;

  const rows = tableData ? (showAll ? [...tableData.keyRows, ...tableData.extraRows] : tableData.keyRows) : [];

  return (
    <div className="glass-card financials-card">
      <h3>📑 Financial Statements</h3>

      <div className="financials-controls">
        <div className="financials-tabs">
          {TABS.map(t => (
            <button
              key={t.id}
              className={`fin-tab ${activeTab === t.id ? 'active' : ''}`}
              onClick={() => { setActiveTab(t.id); setShowAll(false); }}
            >{t.label}</button>
          ))}
        </div>
        <button
          className={`btn-toggle-sm ${quarterly ? 'active' : ''}`}
          onClick={() => setQuarterly(!quarterly)}
        >{quarterly ? 'Quarterly' : 'Annual'}</button>
      </div>

      {tableData ? (
        <>
          <div className="financials-table-wrap">
            <table className="financials-table">
              <thead>
                <tr>
                  <th className="fin-row-label">Metric</th>
                  {tableData.periods.map(p => (
                    <th key={p}>{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map(row => (
                  <tr key={row}>
                    <td className="fin-row-label">{labelFromKey(row)}</td>
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
          {tableData.extraRows.length > 0 && (
            <button
              className="btn-toggle-sm"
              style={{ marginTop: '0.75rem' }}
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? 'Show Key Metrics Only' : `Show All (${tableData.keyRows.length + tableData.extraRows.length} items)`}
            </button>
          )}
        </>
      ) : (
        <p className="no-data-text">No financial data available.</p>
      )}
    </div>
  );
}
