const usd = (value) => `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

function DeleteCell({ type, id, confirmDelete, setConfirmDelete, onDelete }) {
  return (
    <td className="action-cell">
      {confirmDelete?.type === type && confirmDelete?.id === id ? (
        <>
          <button className="btn-icon btn-confirm-del" title="Confirm delete" onClick={() => onDelete(type, id)}>✔</button>
          <button className="btn-icon" title="Cancel" onClick={() => setConfirmDelete(null)}>✕</button>
        </>
      ) : (
        <button className="btn-icon" title="Remove from history" onClick={() => setConfirmDelete({ type, id })}>🗑️</button>
      )}
    </td>
  );
}

function RealizedMetrics({ count, total, label, children }) {
  return (
    <div className="metrics-grid" style={{ marginTop: '0.5rem' }}>
      <div className="metric">
        <span className="metric-label">Closed Trades</span>
        <span className="metric-value">{count}</span>
      </div>
      <div className={`metric ${total >= 0 ? 'metric-positive' : 'metric-negative'}`}>
        <span className="metric-label">{label}</span>
        <span className={`metric-value ${total >= 0 ? 'positive' : 'negative'}`}>{usd(total)}</span>
      </div>
      {children}
    </div>
  );
}

export function ClosedStocks({ data, confirmDelete, setConfirmDelete, onDelete }) {
  if (!data?.trades?.length) return <p className="empty-state">No sold stocks yet. Sell a position to see it here.</p>;
  const remove = { confirmDelete, setConfirmDelete, onDelete };
  return (
    <>
      <RealizedMetrics count={data.trades.length} total={data.total_realized_pnl} label="Realized P/L" />
      <table className="portfolio-table">
        <thead>
          <tr><th>Ticker</th><th>Shares</th><th>Buy Price</th><th>Sell Price</th><th>P/L ($)</th><th>P/L %</th><th>Date</th><th></th></tr>
        </thead>
        <tbody>
          {data.trades.map((t) => (
            <tr key={t.id}>
              <td><strong>{t.ticker}</strong></td>
              <td>{t.shares}</td>
              <td>${t.buy_price.toFixed(2)}</td>
              <td>${t.sell_price.toFixed(2)}</td>
              <td className={t.pnl >= 0 ? 'positive' : 'negative'}>${t.pnl.toFixed(2)}</td>
              <td className={t.pnl_pct >= 0 ? 'positive' : 'negative'}>{t.pnl_pct.toFixed(2)}%</td>
              <td>{new Date(t.closed_at).toLocaleDateString()}</td>
              <DeleteCell type="closed-stock" id={t.id} {...remove} />
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

export function ClosedOptions({ data, confirmDelete, setConfirmDelete, onDelete }) {
  if (!data?.trades?.length) return <p className="empty-state">No closed options yet. Close a position to see it here.</p>;
  const remove = { confirmDelete, setConfirmDelete, onDelete };
  return (
    <>
      <RealizedMetrics count={data.trades.length} total={data.total_realized_pnl} label="Gross Realized P/L">
        <div className="metric"><span className="metric-label">Recorded Fees</span><span className="metric-value">{data.total_fees == null ? 'Unavailable' : `$${data.total_fees.toFixed(2)}`}</span></div>
        <div className="metric"><span className="metric-label">Net Realized P/L</span><span className="metric-value">{data.total_net_pnl == null ? 'Unavailable' : `$${data.total_net_pnl.toFixed(2)}`}</span></div>
      </RealizedMetrics>
      <div className="table-scroll"><table className="portfolio-table">
        <thead>
          <tr>
            <th>Ticker</th><th>Type</th><th>Side</th><th>Strike</th><th>Expiry</th><th>Qty</th><th>Open</th><th>Close</th>
            <th>Gross P/L ($)</th><th>Fees ($)</th><th>Net P/L ($)</th><th>Gross P/L %</th><th>Date</th><th></th>
          </tr>
        </thead>
        <tbody>
          {data.trades.map((t) => (
            <tr key={t.id}>
              <td><strong>{t.ticker}</strong></td>
              <td className={t.option_type === 'call' ? 'positive' : 'negative'}>{t.option_type.toUpperCase()}</td>
              <td><span className={`side-badge side-${t.position}`}>{t.position.toUpperCase()}</span></td>
              <td>${t.strike.toFixed(2)}</td>
              <td>{t.expiry}</td>
              <td>{t.contracts}</td>
              <td>${t.open_premium.toFixed(2)}</td>
              <td>${t.close_premium.toFixed(2)}</td>
              <td className={t.pnl >= 0 ? 'positive' : 'negative'}>${t.pnl.toFixed(2)}</td>
              <td>{t.fees == null ? 'Unavailable' : `$${t.fees.toFixed(2)}`}</td>
              <td>{t.net_pnl == null ? 'Unavailable' : `$${t.net_pnl.toFixed(2)}`}</td>
              <td className={t.pnl_pct >= 0 ? 'positive' : 'negative'}>{t.pnl_pct.toFixed(2)}%</td>
              <td>{String(t.closed_at).slice(0, 10)}</td>
              <DeleteCell type="closed-option" id={t.id} {...remove} />
            </tr>
          ))}
        </tbody>
      </table></div>
    </>
  );
}
