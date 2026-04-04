import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';
import { API_BASE } from '../api/config';
import {
  fetchPortfolioSummary, buyStock, sellStock,
  fetchOptionsSummary, buyOption, closeOption,
  editHolding, deleteHolding, editOption, deleteOption,
} from '../api/stockApi';

const GUEST_HOLDINGS_KEY = 'guest_holdings';

function getGuestHoldings() {
  try { return JSON.parse(localStorage.getItem(GUEST_HOLDINGS_KEY) || '[]'); }
  catch { return []; }
}
function saveGuestHoldings(list) {
  localStorage.setItem(GUEST_HOLDINGS_KEY, JSON.stringify(list));
}

export default function Portfolio() {
  const { token, user } = useAuth();
  const isGuest = !user;

  const [tab, setTab] = useState('stocks');
  const [portfolio, setPortfolio] = useState(null);
  const [optionsSummary, setOptionsSummary] = useState(null);
  const [form, setForm] = useState({ ticker: '', shares: 1, price: 100 });
  const [optForm, setOptForm] = useState({
    ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1,
    action: 'bto',
  });
  const [msg, setMsg] = useState(null);
  const [editIdx, setEditIdx] = useState(null);        // DB id / guest id being edited (stocks)
  const [editOptIdx, setEditOptIdx] = useState(null);   // DB id being edited (options)
  const [confirmDelete, setConfirmDelete] = useState(null); // { type: 'stock'|'option', id }

  // ── Guest: build portfolio summary from localStorage + live prices ──

  const loadGuestStocks = useCallback(async () => {
    const raw = getGuestHoldings();
    if (!raw.length) { setPortfolio({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 }); return; }
    try {
      const holdings = await Promise.all(raw.map(async (h) => {
        try {
          const res = await fetch(`${API_BASE}/stock/${h.ticker}/metrics`);
          const m = res.ok ? await res.json() : {};
          const current_price = m.price ?? h.buy_price;
          const pnl = (current_price - h.buy_price) * h.shares;
          const pnl_pct = h.buy_price > 0 ? ((current_price - h.buy_price) / h.buy_price) * 100 : 0;
          return { ...h, current_price, pnl, pnl_pct };
        } catch { return { ...h, current_price: h.buy_price, pnl: 0, pnl_pct: 0 }; }
      }));
      const total_invested = holdings.reduce((s, h) => s + h.buy_price * h.shares, 0);
      const total_current = holdings.reduce((s, h) => s + h.current_price * h.shares, 0);
      const total_pnl = total_current - total_invested;
      const total_pnl_pct = total_invested > 0 ? (total_pnl / total_invested) * 100 : 0;
      setPortfolio({ holdings, total_invested, total_current, total_pnl, total_pnl_pct });
    } catch { /* ignore */ }
  }, []);

  // ── Auth: load from API ──────────────────────────────────────

  const loadStocks = useCallback(async () => {
    if (isGuest) { await loadGuestStocks(); return; }
    try { setPortfolio(await fetchPortfolioSummary()); } catch { /* empty */ }
  }, [isGuest, loadGuestStocks]);

  const loadOptions = useCallback(async () => {
    if (isGuest) return;
    try { setOptionsSummary(await fetchOptionsSummary()); } catch { /* empty */ }
  }, [isGuest]);

  useEffect(() => { loadStocks(); loadOptions(); }, [loadStocks, loadOptions]);

  // Auto-clear messages after 4s
  useEffect(() => {
    if (msg) { const t = setTimeout(() => setMsg(null), 4000); return () => clearTimeout(t); }
  }, [msg]);

  // ── Stock handlers ──────────────────────────────────────────
  const handleBuy = async () => {
    if (!form.ticker) return;
    const ticker = form.ticker.toUpperCase();

    if (isGuest) {
      const raw = getGuestHoldings();
      const existing = raw.find((h) => h.ticker === ticker);
      if (existing) {
        // Average down/up: weighted avg price, combined shares
        const totalShares = existing.shares + form.shares;
        const avgPrice = (existing.buy_price * existing.shares + form.price * form.shares) / totalShares;
        const updated = raw.map((h) => h.ticker === ticker ? { ...h, shares: totalShares, buy_price: parseFloat(avgPrice.toFixed(4)) } : h);
        saveGuestHoldings(updated);
      } else {
        const newHolding = { id: Date.now(), ticker, shares: form.shares, buy_price: form.price, date_added: new Date().toISOString() };
        saveGuestHoldings([...raw, newHolding]);
      }
      setMsg(`Bought ${form.shares} shares of ${ticker}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadGuestStocks();
      return;
    }

    try {
      await buyStock(ticker, form.shares, form.price);
      setMsg(`Bought ${form.shares} shares of ${ticker}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadStocks();
    } catch (e) { setMsg(e.message); }
  };

  const handleSell = async () => {
    if (!form.ticker) return;
    const ticker = form.ticker.toUpperCase();

    if (isGuest) {
      const raw = getGuestHoldings();
      const existing = raw.find((h) => h.ticker === ticker);
      if (!existing) { setMsg(`No position in ${ticker}`); return; }
      const remaining = existing.shares - form.shares;
      const updated = remaining <= 0
        ? raw.filter((h) => h.ticker !== ticker)
        : raw.map((h) => h.ticker === ticker ? { ...h, shares: parseFloat(remaining.toFixed(4)) } : h);
      saveGuestHoldings(updated);
      setMsg(`Sold ${form.shares} shares of ${ticker}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadGuestStocks();
      return;
    }

    try {
      await sellStock(ticker, form.shares, form.price);
      setMsg(`Sold ${form.shares} shares of ${ticker}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadStocks();
    } catch (e) { setMsg(e.message); }
  };

  const startEditStock = (h) => {
    setEditIdx(h.id);
    setForm({ ticker: h.ticker, shares: h.shares, price: h.buy_price });
  };

  const handleSaveEdit = async () => {
    if (editIdx === null) return;

    if (isGuest) {
      const updated = getGuestHoldings().map((h) =>
        h.id === editIdx ? { ...h, ticker: form.ticker.toUpperCase(), shares: form.shares, buy_price: form.price } : h
      );
      saveGuestHoldings(updated);
      setMsg(`Updated ${form.ticker.toUpperCase()}`);
      setEditIdx(null);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadGuestStocks();
      return;
    }

    try {
      await editHolding(editIdx, form.ticker.toUpperCase(), form.shares, form.price);
      setMsg(`Updated ${form.ticker.toUpperCase()}`);
      setEditIdx(null);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadStocks();
    } catch (e) { setMsg(e.message); }
  };

  const handleDeleteStock = async (id) => {
    if (isGuest) {
      saveGuestHoldings(getGuestHoldings().filter((h) => h.id !== id));
      setMsg('Position deleted');
      setConfirmDelete(null);
      loadGuestStocks();
      return;
    }
    try {
      await deleteHolding(id);
      setMsg('Position deleted');
      setConfirmDelete(null);
      loadStocks();
    } catch (e) { setMsg(e.message); }
  };

  // ── Option handlers ─────────────────────────────────────────
  const handleOptionSubmit = async () => {
    if (!optForm.ticker || !optForm.expiry) return;
    const t = optForm.ticker.toUpperCase();
    const { type, strike, expiry, premium, contracts, action } = optForm;
    try {
      if (action === 'bto') {
        await buyOption(t, type, strike, expiry, premium, contracts, 'long');
        setMsg(`BTO ${contracts} ${type.toUpperCase()} on ${t}`);
      } else if (action === 'sto') {
        await buyOption(t, type, strike, expiry, premium, contracts, 'short');
        setMsg(`STO ${contracts} ${type.toUpperCase()} on ${t}`);
      } else if (action === 'stc') {
        await closeOption(t, type, strike, expiry, premium, contracts, 'long');
        setMsg(`STC ${contracts} ${type.toUpperCase()} on ${t}`);
      } else if (action === 'btc') {
        await closeOption(t, type, strike, expiry, premium, contracts, 'short');
        setMsg(`BTC ${contracts} ${type.toUpperCase()} on ${t}`);
      }
      setOptForm({ ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1, action: 'bto' });
      loadOptions();
    } catch (e) { setMsg(e.message); }
  };

  const startEditOption = (o) => {
    setEditOptIdx(o.id);
    setOptForm({
      ticker: o.ticker, type: o.type, strike: o.strike,
      expiry: o.expiry, premium: o.premium, contracts: o.contracts,
      action: o.position === 'short' ? 'sto' : 'bto',
    });
  };

  const handleSaveOptEdit = async () => {
    if (editOptIdx === null) return;
    const position = (optForm.action === 'sto' || optForm.action === 'btc') ? 'short' : 'long';
    try {
      await editOption(
        editOptIdx, optForm.ticker.toUpperCase(), optForm.type,
        optForm.strike, optForm.expiry, optForm.premium, optForm.contracts, position
      );
      setMsg(`Updated option on ${optForm.ticker.toUpperCase()}`);
      setEditOptIdx(null);
      setOptForm({ ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1, action: 'bto' });
      loadOptions();
    } catch (e) { setMsg(e.message); }
  };

  const handleDeleteOption = async (id) => {
    try {
      await deleteOption(id);
      setMsg('Option deleted');
      setConfirmDelete(null);
      loadOptions();
    } catch (e) { setMsg(e.message); }
  };

  const cancelEdit = () => {
    setEditIdx(null);
    setEditOptIdx(null);
    setForm({ ticker: '', shares: 1, price: 100 });
    setOptForm({ ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1, action: 'bto' });
  };

  return (
    <div className="card">
      <div className="portfolio-tabs">
        <h3 style={{ margin: 0 }}>Portfolio {isGuest && <span className="guest-badge">Guest</span>}</h3>
        <div className="chart-toggle">
          <button className={tab === 'stocks' ? 'active' : ''} onClick={() => { setTab('stocks'); cancelEdit(); }}>
            Stocks
          </button>
          <button className={tab === 'options' ? 'active' : ''} onClick={() => { setTab('options'); cancelEdit(); }}>
            Options
          </button>
        </div>
      </div>
      {isGuest && (
        <p className="guest-note">
          Portfolio saved in this browser only. Sign in to sync across devices and unlock options tracking.
        </p>
      )}

      {msg && <p className="portfolio-msg">{msg}</p>}

      {/* ── Stocks Tab ────────────────────────────────────────── */}
      {tab === 'stocks' && (
        <>
          <div className="portfolio-form labeled-form">
            <div className="form-field">
              <label htmlFor="stock-ticker">Ticker</label>
              <input id="stock-ticker" type="text" placeholder="e.g. AAPL" value={form.ticker}
                onChange={(e) => setForm({ ...form, ticker: e.target.value })} maxLength={10} />
            </div>
            <div className="form-field">
              <label htmlFor="stock-shares">Shares</label>
              <input id="stock-shares" type="number" placeholder="Qty" value={form.shares} min={0.01} step={1}
                onChange={(e) => setForm({ ...form, shares: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="form-field">
              <label htmlFor="stock-price">Price ($)</label>
              <input id="stock-price" type="number" placeholder="Per share" value={form.price} min={0.01} step={0.5}
                onChange={(e) => setForm({ ...form, price: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="form-actions">
              {editIdx !== null ? (
                <>
                  <button className="btn-primary" onClick={handleSaveEdit}>Save</button>
                  <button className="btn-secondary" onClick={cancelEdit}>Cancel</button>
                </>
              ) : (
                <>
                  <button className="btn-primary" onClick={handleBuy}>Buy</button>
                  <button className="btn-secondary" onClick={handleSell}>Sell</button>
                </>
              )}
            </div>
          </div>

          {portfolio && portfolio.holdings && portfolio.holdings.length > 0 ? (
            <>
              <div className="metrics-grid" style={{ marginTop: '1rem' }}>
                <div className="metric">
                  <span className="metric-label">Invested</span>
                  <span className="metric-value">${portfolio.total_invested.toLocaleString()}</span>
                </div>
                <div className="metric">
                  <span className="metric-label">Current Value</span>
                  <span className="metric-value">${portfolio.total_current.toLocaleString()}</span>
                </div>
                <div className={`metric ${portfolio.total_pnl >= 0 ? 'metric-positive' : 'metric-negative'}`}>
                  <span className="metric-label">Total P/L</span>
                  <span className={`metric-value ${portfolio.total_pnl >= 0 ? 'positive' : 'negative'}`}>
                    ${portfolio.total_pnl.toLocaleString()} ({portfolio.total_pnl_pct.toFixed(2)}%)
                  </span>
                </div>
              </div>
              <table className="portfolio-table">
                <thead>
                  <tr>
                    <th title="Stock symbol (e.g. AAPL)">Ticker</th>
                    <th title="Number of shares held">Shares</th>
                    <th title="Average price paid per share">Avg Buy</th>
                    <th title="Current market price per share">Current</th>
                    <th title="Profit/Loss: (Current − Buy) × Shares">P/L ($)</th>
                    <th title="Percentage gain or loss">P/L %</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {portfolio.holdings.map((h) => (
                    <tr key={h.id} className={editIdx === h.id ? 'row-editing' : ''}>
                      <td><strong>{h.ticker}</strong></td>
                      <td>{h.shares}</td>
                      <td>${h.buy_price.toFixed(2)}</td>
                      <td>${h.current_price.toFixed(2)}</td>
                      <td className={h.pnl >= 0 ? 'positive' : 'negative'}>${h.pnl.toFixed(2)}</td>
                      <td className={h.pnl_pct >= 0 ? 'positive' : 'negative'}>{h.pnl_pct.toFixed(2)}%</td>
                      <td className="action-cell">
                        <button className="btn-icon" title="Edit position" onClick={() => startEditStock(h)}>✏️</button>
                        {confirmDelete?.type === 'stock' && confirmDelete?.id === h.id ? (
                          <>
                            <button className="btn-icon btn-confirm-del" title="Confirm delete" onClick={() => handleDeleteStock(h.id)}>✔</button>
                            <button className="btn-icon" title="Cancel" onClick={() => setConfirmDelete(null)}>✕</button>
                          </>
                        ) : (
                          <button className="btn-icon" title="Delete position" onClick={() => setConfirmDelete({ type: 'stock', id: h.id })}>🗑️</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="empty-state">No stock holdings yet. Use the form above to add positions.</p>
          )}
        </>
      )}

      {/* ── Options Tab ───────────────────────────────────────── */}
      {tab === 'options' && (
        isGuest ? (
          <div className="empty-state guest-note" style={{ marginTop: '1.5rem' }}>
            Options tracking requires an account. Sign in to add and track calls &amp; puts with live P/L.
          </div>
        ) : (
        <>
          <div className="portfolio-form labeled-form">
            <div className="form-field">
              <label htmlFor="opt-action">Action</label>
              <select id="opt-action" value={optForm.action}
                onChange={(e) => setOptForm({ ...optForm, action: e.target.value })}>
                <option value="bto">Buy to Open (Long)</option>
                <option value="sto">Sell to Open (Short)</option>
                <option value="stc">Sell to Close</option>
                <option value="btc">Buy to Close</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="opt-ticker">Ticker</label>
              <input id="opt-ticker" type="text" placeholder="e.g. AAPL" value={optForm.ticker}
                onChange={(e) => setOptForm({ ...optForm, ticker: e.target.value })} maxLength={10} />
            </div>
            <div className="form-field">
              <label htmlFor="opt-type">Type</label>
              <select id="opt-type" value={optForm.type} onChange={(e) => setOptForm({ ...optForm, type: e.target.value })}>
                <option value="call">Call</option>
                <option value="put">Put</option>
              </select>
            </div>
            <div className="form-field">
              <label htmlFor="opt-strike">Strike ($)</label>
              <input id="opt-strike" type="number" placeholder="Strike price" value={optForm.strike} min={0.01} step={1}
                onChange={(e) => setOptForm({ ...optForm, strike: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="form-field">
              <label htmlFor="opt-expiry">Expiry Date</label>
              <input id="opt-expiry" type="date" value={optForm.expiry}
                onChange={(e) => setOptForm({ ...optForm, expiry: e.target.value })}
                min={new Date().toISOString().split('T')[0]} />
            </div>
            <div className="form-field">
              <label htmlFor="opt-premium">Premium ($)</label>
              <input id="opt-premium" type="number" placeholder="Per share" value={optForm.premium} min={0.01} step={0.05}
                onChange={(e) => setOptForm({ ...optForm, premium: parseFloat(e.target.value) || 0 })} />
            </div>
            <div className="form-field">
              <label htmlFor="opt-contracts">Contracts</label>
              <input id="opt-contracts" type="number" placeholder="Qty" value={optForm.contracts} min={1} step={1}
                onChange={(e) => setOptForm({ ...optForm, contracts: parseInt(e.target.value) || 1 })} />
            </div>
            <div className="form-actions">
              {editOptIdx !== null ? (
                <>
                  <button className="btn-primary" onClick={handleSaveOptEdit}>Save</button>
                  <button className="btn-secondary" onClick={cancelEdit}>Cancel</button>
                </>
              ) : (
                <button className="btn-primary" onClick={handleOptionSubmit}>
                  {optForm.action === 'bto' ? 'Buy to Open' : optForm.action === 'sto' ? 'Sell to Open'
                    : optForm.action === 'stc' ? 'Sell to Close' : 'Buy to Close'}
                </button>
              )}
            </div>
          </div>

          {optionsSummary && optionsSummary.options && optionsSummary.options.length > 0 ? (
            <>
              <div className="metrics-grid" style={{ marginTop: '1rem' }}>
                <div className="metric">
                  <span className="metric-label">Total Cost</span>
                  <span className="metric-value">${optionsSummary.total_cost.toLocaleString()}</span>
                </div>
                <div className="metric">
                  <span className="metric-label">Market Value</span>
                  <span className="metric-value">${optionsSummary.total_value.toLocaleString()}</span>
                </div>
                <div className={`metric ${optionsSummary.total_pnl >= 0 ? 'metric-positive' : 'metric-negative'}`}>
                  <span className="metric-label">Total P/L</span>
                  <span className={`metric-value ${optionsSummary.total_pnl >= 0 ? 'positive' : 'negative'}`}>
                    ${optionsSummary.total_pnl.toLocaleString()} ({optionsSummary.total_pnl_pct.toFixed(2)}%)
                  </span>
                </div>
              </div>
              <table className="portfolio-table">
                <thead>
                  <tr>
                    <th title="Underlying stock symbol">Ticker</th>
                    <th title="Call = right to buy, Put = right to sell">Type</th>
                    <th title="Long = bought, Short = sold/written">Side</th>
                    <th title="Exercise price">Strike</th>
                    <th title="Current stock price">Stock</th>
                    <th title="In/Out/At the money">Status</th>
                    <th title="Contract expiration date (days to expiry)">Expiry</th>
                    <th title="Number of contracts (1 = 100 shares)">Qty</th>
                    <th title="Price you paid/received per share">Paid</th>
                    <th title="Live bid × ask mid-price from Yahoo Finance">Mkt Price</th>
                    <th title="Implied Volatility from Yahoo Finance">IV</th>
                    <th title="Profit/Loss based on live market price">P/L</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {optionsSummary.options.map((o, i) => {
                    const diff = o.type === 'call'
                      ? o.current_price - o.strike
                      : o.strike - o.current_price;
                    const moneyness = Math.abs(diff) < 0.5 ? 'ATM'
                      : diff > 0 ? 'ITM' : 'OTM';
                    const moneyClass = moneyness === 'ITM' ? 'positive'
                      : moneyness === 'OTM' ? 'negative' : '';
                    const side = o.position || 'long';
                    return (
                    <tr key={o.id || i} className={editOptIdx === o.id ? 'row-editing' : ''}>
                      <td><strong>{o.ticker}</strong></td>
                      <td className={o.type === 'call' ? 'positive' : 'negative'}>
                        {o.type.toUpperCase()}
                      </td>
                      <td>
                        <span className={`side-badge side-${side}`}>
                          {side.toUpperCase()}
                        </span>
                      </td>
                      <td>${o.strike.toFixed(2)}</td>
                      <td>${o.current_price.toFixed(2)}</td>
                      <td className={moneyClass}>
                        <span className="moneyness-badge" title={
                          moneyness === 'ITM' ? 'In the Money — has intrinsic value'
                          : moneyness === 'OTM' ? 'Out of the Money — no intrinsic value (only time value)'
                          : 'At the Money — strike ≈ current price'
                        }>{moneyness}</span>
                      </td>
                      <td>
                        {o.expiry}
                        <span className="dte-badge" title="Days to expiry">{o.dte}d</span>
                      </td>
                      <td>{o.contracts}</td>
                      <td>${o.premium.toFixed(2)}</td>
                      <td title={`Bid: $${(o.bid || 0).toFixed(2)} / Ask: $${(o.ask || 0).toFixed(2)}`}>
                        ${o.market_price.toFixed(2)}
                      </td>
                      <td title="Implied Volatility">{o.iv ? `${o.iv}%` : '—'}</td>
                      <td className={o.pnl >= 0 ? 'positive' : 'negative'}>
                        ${o.pnl.toFixed(2)} ({o.pnl_pct.toFixed(1)}%)
                      </td>
                      <td className="action-cell">
                        <button className="btn-icon" title="Edit option" onClick={() => startEditOption(o)}>✏️</button>
                        {confirmDelete?.type === 'option' && confirmDelete?.id === o.id ? (
                          <>
                            <button className="btn-icon btn-confirm-del" title="Confirm delete" onClick={() => handleDeleteOption(o.id)}>✔</button>
                            <button className="btn-icon" title="Cancel" onClick={() => setConfirmDelete(null)}>✕</button>
                          </>
                        ) : (
                          <button className="btn-icon" title="Delete option" onClick={() => setConfirmDelete({ type: 'option', id: o.id })}>🗑️</button>
                        )}
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          ) : (
            <p className="empty-state">No options positions yet. Use the form above to add calls or puts.</p>
          )}
        </>
        )
      )}
    </div>
  );
}
