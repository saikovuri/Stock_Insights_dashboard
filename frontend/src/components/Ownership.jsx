import { useState, useEffect } from 'react';
import { fetchOwnership } from '../api/stockApi';

function formatNum(v) {
  if (v == null) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return v.toLocaleString();
}

export default function Ownership({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState('institutional');

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    setLoading(true);
    fetchOwnership(ticker)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ticker]);

  if (!ticker) return null;
  if (loading) return <div className="glass-card ownership-card"><p className="loading-text">Loading ownership data…</p></div>;
  if (!data) return null;

  const { held_pct_insiders, held_pct_institutions, institutional_holders, insider_transactions } = data;

  return (
    <div className="glass-card ownership-card">
      <h3>🏛️ Institutional & Insider Activity</h3>

      {/* Summary bars */}
      <div className="ownership-summary">
        {held_pct_institutions != null && (
          <div className="ownership-stat">
            <span className="ownership-label">Institutions</span>
            <div className="ownership-bar-track">
              <div className="ownership-bar-fill institutional" style={{ width: `${Math.min(held_pct_institutions, 100)}%` }}></div>
            </div>
            <span className="ownership-pct">{held_pct_institutions.toFixed(1)}%</span>
          </div>
        )}
        {held_pct_insiders != null && (
          <div className="ownership-stat">
            <span className="ownership-label">Insiders</span>
            <div className="ownership-bar-track">
              <div className="ownership-bar-fill insider" style={{ width: `${Math.min(held_pct_insiders, 100)}%` }}></div>
            </div>
            <span className="ownership-pct">{held_pct_insiders.toFixed(1)}%</span>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="ownership-tabs">
        <button className={`fin-tab ${tab === 'institutional' ? 'active' : ''}`} onClick={() => setTab('institutional')}>
          Top Holders ({institutional_holders?.length || 0})
        </button>
        <button className={`fin-tab ${tab === 'insider' ? 'active' : ''}`} onClick={() => setTab('insider')}>
          Insider Trades ({insider_transactions?.length || 0})
        </button>
      </div>

      {tab === 'institutional' && institutional_holders?.length > 0 && (
        <div className="financials-table-wrap">
          <table className="analyst-table">
            <thead>
              <tr><th>Holder</th><th>Shares</th><th>Value</th><th>% Out</th><th>Date Reported</th></tr>
            </thead>
            <tbody>
              {institutional_holders.map((h, i) => (
                <tr key={i}>
                  <td>{h.Holder || h.holder || '—'}</td>
                  <td>{formatNum(h.Shares || h.shares)}</td>
                  <td>{formatNum(h.Value || h.value)}</td>
                  <td>{h['% Out'] != null ? `${(h['% Out'] * 100).toFixed(2)}%` : h.pctHeld != null ? `${(h.pctHeld * 100).toFixed(2)}%` : '—'}</td>
                  <td>{h['Date Reported'] || h.dateReported || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'insider' && insider_transactions?.length > 0 && (
        <div className="financials-table-wrap">
          <table className="analyst-table">
            <thead>
              <tr><th>Insider</th><th>Relation</th><th>Transaction</th><th>Shares</th><th>Value</th><th>Date</th></tr>
            </thead>
            <tbody>
              {insider_transactions.map((t, i) => {
                const txnText = t.Text || t.Transaction || t.transaction || '';
                const isBuy = /purchase|buy|acquisition/i.test(txnText);
                const isSell = /sale|sell|disposition/i.test(txnText);
                return (
                  <tr key={i}>
                    <td>{t.Insider || t['Insider Trading'] || t.insider || '—'}</td>
                    <td>{t.Relationship || t.Position || t.relation || '—'}</td>
                    <td className={isBuy ? 'positive' : isSell ? 'negative' : ''}>{txnText || '—'}</td>
                    <td>{formatNum(t.Shares || t.shares || t['Shares Traded'])}</td>
                    <td>{formatNum(t.Value || t.value || t['Value'])}</td>
                    <td>{t['Start Date'] || t.startDate || t.Date || t.date || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {((tab === 'institutional' && (!institutional_holders || institutional_holders.length === 0)) ||
        (tab === 'insider' && (!insider_transactions || insider_transactions.length === 0))) && (
        <p className="no-data-text">No {tab} data available.</p>
      )}
    </div>
  );
}
