import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';
import { API_BASE } from '../api/config';
import {
  fetchPortfolioSummary, buyStock, sellStock, sellStockLot,
  fetchOptionsSummary, buyOption, closeOption,
  editHolding, deleteHolding, editOption, deleteOption,
  fetchClosedTrades, fetchClosedOptions, assignOption, expireOption, deleteClosedTrade, deleteClosedOption,
} from '../api/stockApi';
import PortfolioChart from './PortfolioChart';
import SectorAllocation from './SectorAllocation';
import PortfolioDoctor from './PortfolioDoctor';
import PortfolioInsights from './PortfolioInsights';
import RollRepair from './RollRepair';
import { Today, Earnings, WhatIf } from './OptionsDesk';
import { ImportCsv } from './PortfolioInsights';
import CorrelationHeatmap from './CorrelationHeatmap';
import AccountTransfer from './AccountTransfer';
import { AccountBar, NavHistory, SplitNotice } from './Accounts';
import Skeleton from './Skeleton';

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
  const [section, setSection] = useState('holdings');
  const [loadError, setLoadError] = useState(null);
  const [transferRevision, setTransferRevision] = useState(0);
  const [account, setAccountState] = useState(() => localStorage.getItem('portfolio_account') || '');
  const setAccount = (name) => { localStorage.setItem('portfolio_account', name); setAccountState(name); };
  const [cycle, setCycle] = useState('');
  const [view, setView] = useState('current');   // 'current' | 'sold'
  const [portfolio, setPortfolio] = useState(null);
  const [optionsSummary, setOptionsSummary] = useState(null);
  const [closedStocks, setClosedStocks] = useState(null);
  const [closedOpts, setClosedOpts] = useState(null);
  const [form, setForm] = useState({ ticker: '', shares: 1, price: 100 });
  const [optForm, setOptForm] = useState({
    ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1,
    action: 'bto',
  });
  const [msg, setMsg] = useState(null);
  const [editIdx, setEditIdx] = useState(null);        // DB id / guest id being edited (stocks)
  const [editOptIdx, setEditOptIdx] = useState(null);   // DB id being edited (options)
  const [confirmDelete, setConfirmDelete] = useState(null); // { type: 'stock'|'option', id }
  const [sellLotId, setSellLotId] = useState(null);    // lot id being sold
  const [expanded, setExpanded] = useState({});         // { ticker: true/false } for collapsibles
  const [repairOpt, setRepairOpt] = useState(null);     // short option position open in Roll / repair
  const validOptionPremium = String(optForm.premium).trim() !== ''
    && Number.isFinite(Number(optForm.premium)) && Number(optForm.premium) >= 0;

  // ── Guest: build portfolio summary from localStorage + live prices ──

  const loadGuestStocks = useCallback(async () => {
    const raw = getGuestHoldings();
    if (!raw.length) { setPortfolio({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 }); return; }
    try {
      const holdings = await Promise.all(raw.map(async (h) => {
        try {
          const res = await fetch(`${API_BASE}/stock/${h.ticker}/metrics`);
          const m = res.ok ? await res.json() : {};
          const current_price = Number.isFinite(m.price) && m.price > 0 ? m.price : null;
          const sector = m.sector || 'Unknown';
          const pnl = current_price == null ? null : (current_price - h.buy_price) * h.shares;
          const pnl_pct = current_price != null && h.buy_price > 0 ? ((current_price - h.buy_price) / h.buy_price) * 100 : null;
          return { ...h, current_price, sector, pnl, pnl_pct };
        } catch { return { ...h, current_price: null, pnl: null, pnl_pct: null }; }
      }));
      const total_invested = holdings.reduce((s, h) => s + h.buy_price * h.shares, 0);
      const total_current = holdings.reduce((s, h) => s + h.current_price * h.shares, 0);
      const total_pnl = total_current - total_invested;
      const total_pnl_pct = total_invested > 0 ? (total_pnl / total_invested) * 100 : 0;
      const incomplete = holdings.some(holding => holding.current_price == null);
      setPortfolio({ holdings, total_invested, incomplete, total_current: incomplete ? null : total_current,
        total_pnl: incomplete ? null : total_pnl, total_pnl_pct: incomplete ? null : total_pnl_pct });
    } catch { /* ignore */ }
  }, []);

  // ── Auth: load from API ──────────────────────────────────────

  const loadStocks = useCallback(async () => {
    if (isGuest) { await loadGuestStocks(); return; }
    try { setPortfolio(await fetchPortfolioSummary(account)); } catch (error) { setLoadError(error.message); }
  }, [isGuest, loadGuestStocks, account]);

  const loadOptions = useCallback(async () => {
    if (isGuest) return;
    try { setOptionsSummary(await fetchOptionsSummary(account)); } catch (error) { setLoadError(error.message); }
  }, [isGuest, account]);

  const loadClosed = useCallback(async () => {
    if (isGuest) {
      try {
        const raw = JSON.parse(localStorage.getItem('guest_sold_stocks') || '[]');
        const total = raw.reduce((s, t) => s + t.pnl, 0);
        setClosedStocks({ total_realized_pnl: Math.round(total * 100) / 100, trades: raw });
      } catch { setClosedStocks({ total_realized_pnl: 0, trades: [] }); }
      return;
    }
    try { setClosedStocks(await fetchClosedTrades(account)); } catch (error) { setLoadError(error.message); }
    try { setClosedOpts(await fetchClosedOptions(account)); } catch (error) { setLoadError(error.message); }
  }, [isGuest, account]);

  useEffect(() => { loadStocks(); loadOptions(); loadClosed(); }, [loadStocks, loadOptions, loadClosed]);

  // Auto-clear messages after 4s
  useEffect(() => {
    if (msg) { const t = setTimeout(() => setMsg(null), 4000); return () => clearTimeout(t); }
  }, [msg]);

  // ── Stock handlers ──────────────────────────────────────────
  const handleBuy = async () => {
    if (!form.ticker || !Number.isFinite(form.shares) || form.shares <= 0 || !Number.isFinite(form.price) || form.price < 0) { setMsg('Enter valid shares and price.'); return; }
    const ticker = form.ticker.toUpperCase();

    if (isGuest) {
      // Always create a new lot (separate tax lot tracking)
      const raw = getGuestHoldings();
      const newHolding = { id: Date.now(), ticker, shares: form.shares, buy_price: form.price, date_added: new Date().toISOString() };
      saveGuestHoldings([...raw, newHolding]);
      setMsg(`Bought ${form.shares} shares of ${ticker}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadGuestStocks();
      return;
    }

    try {
      await buyStock(ticker, form.shares, form.price, account);
      setMsg(`Bought ${form.shares} shares of ${ticker}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      loadStocks();
    } catch (e) { setMsg(e.message); }
  };

  const handleSell = async () => {
    if (!form.ticker || !Number.isFinite(form.shares) || form.shares <= 0 || !Number.isFinite(form.price) || form.price < 0) { setMsg('Enter valid shares and price.'); return; }
    const ticker = form.ticker.toUpperCase();

    if (isGuest) {
      const raw = getGuestHoldings();
      // If selling a specific lot, find by id; otherwise find by ticker
      const lotId = sellLotId;
      const existing = lotId ? raw.find((h) => h.id === lotId) : raw.find((h) => h.ticker === ticker);
      if (!existing) { setMsg(`No position in ${ticker}`); return; }
      if (form.shares > existing.shares) { setMsg('Sale exceeds this lot. Select and sell each guest lot separately.'); return; }
      const soldShares = Math.min(form.shares, existing.shares);
      const remaining = existing.shares - soldShares;
      const updated = remaining <= 0
        ? raw.filter((h) => h.id !== existing.id)
        : raw.map((h) => h.id === existing.id ? { ...h, shares: parseFloat(remaining.toFixed(4)) } : h);
      saveGuestHoldings(updated);
      // Record closed trade in guest localStorage
      const pnl = (form.price - existing.buy_price) * soldShares;
      const pnl_pct = existing.buy_price > 0 ? ((form.price - existing.buy_price) / existing.buy_price) * 100 : 0;
      const sold = JSON.parse(localStorage.getItem('guest_sold_stocks') || '[]');
      sold.unshift({ id: Date.now(), ticker, shares: soldShares, buy_price: existing.buy_price, sell_price: form.price, pnl: Math.round(pnl * 100) / 100, pnl_pct: Math.round(pnl_pct * 100) / 100, closed_at: new Date().toISOString() });
      localStorage.setItem('guest_sold_stocks', JSON.stringify(sold));
      setMsg(`Sold ${soldShares} shares of ${ticker} @ $${form.price}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      setSellLotId(null);
      loadGuestStocks();
      loadClosed();
      return;
    }

    try {
      if (sellLotId) {
        await sellStockLot(sellLotId, ticker, form.shares, form.price);
      } else {
        await sellStock(ticker, form.shares, form.price, account);
      }
      setMsg(`Sold ${form.shares} shares of ${ticker} @ $${form.price}`);
      setForm({ ticker: '', shares: 1, price: 100 });
      setSellLotId(null);
      loadStocks();
      loadClosed();
    } catch (e) { setMsg(e.message); }
  };

  const startSellLot = (lot) => {
    setSellLotId(lot.id);
    setEditIdx(null);
    setForm({ ticker: lot.ticker, shares: lot.shares, price: lot.current_price ?? lot.buy_price });
  };

  const startEditStock = (h) => {
    setEditIdx(h.id);
    setForm({ ticker: h.ticker, shares: h.shares, price: h.buy_price });
  };

  const handleSaveEdit = async () => {
    if (editIdx === null) return;
    if (!form.ticker || !Number.isFinite(form.shares) || form.shares <= 0 || !Number.isFinite(form.price) || form.price < 0) { setMsg('Enter valid shares and price.'); return; }

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
    if (!optForm.ticker || !optForm.expiry || !validOptionPremium) return;
    const t = optForm.ticker.toUpperCase();
    const { type, strike, expiry, contracts, action } = optForm;
    const premium = Number(optForm.premium);
    try {
      let closed = null;
      if (action === 'bto') {
        await buyOption(t, type, strike, expiry, premium, contracts, 'long', account);
        setMsg(`BTO ${contracts} ${type.toUpperCase()} on ${t}`);
      } else if (action === 'sto') {
        await buyOption(t, type, strike, expiry, premium, contracts, 'short', account);
        setMsg(`STO ${contracts} ${type.toUpperCase()} on ${t}`);
      } else if (action === 'stc') {
        closed = await closeOption(t, type, strike, expiry, premium, contracts, 'long', optForm.option_id, cycle.trim());
        setMsg(`STC ${contracts} ${type.toUpperCase()} on ${t}`);
      } else if (action === 'btc') {
        closed = await closeOption(t, type, strike, expiry, premium, contracts, 'short', optForm.option_id, cycle.trim());
        setMsg(`BTC ${contracts} ${type.toUpperCase()} on ${t}`);
      }
      if (closed?.cycle_error) setMsg(closed.cycle_error);
      else if (closed?.cycle) setMsg(`${action.toUpperCase()} ${contracts} ${type.toUpperCase()} on ${t} · linked to ${closed.cycle}`);
      setCycle('');
      setOptForm({ ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1, action: 'bto' });
      loadOptions();
      if (action === 'stc' || action === 'btc') loadClosed();
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
    if (editOptIdx === null || !validOptionPremium) return;
    const position = (optForm.action === 'sto' || optForm.action === 'btc') ? 'short' : 'long';
    try {
      await editOption(
        editOptIdx, optForm.ticker.toUpperCase(), optForm.type,
        optForm.strike, optForm.expiry, Number(optForm.premium), optForm.contracts, position
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

  const handleDeleteClosed = async (type, id) => {
    try {
      if (type === 'closed-stock' && isGuest) {
        const sold = JSON.parse(localStorage.getItem('guest_sold_stocks') || '[]').filter(t => t.id !== id);
        localStorage.setItem('guest_sold_stocks', JSON.stringify(sold));
      } else if (type === 'closed-stock') {
        await deleteClosedTrade(id);
      } else {
        await deleteClosedOption(id);
      }
      setMsg('Trade removed from history');
      setConfirmDelete(null);
      loadClosed();
    } catch (e) { setMsg(e.message); }
  };

  const handleAssign = async (o) => {
    const n = 100 * o.contracts;
    const what = o.type === 'put'
      ? `buy ${n} ${o.ticker} shares at $${o.strike}`
      : `sell ${n} ${o.ticker} shares at $${o.strike} (called away)`;
    if (!window.confirm(`Mark the short $${o.strike} ${o.type} as assigned? This closes it at $0 (premium kept) and will ${what}.`)) return;
    try {
      const r = await assignOption(o.id);
      setMsg(r.action === 'ASSIGNED_PUT' ? `Assigned: added ${r.shares} ${r.ticker} shares at $${r.price}`
        : `Called away: sold ${r.shares} ${r.ticker} shares at $${r.price}`);
      setRepairOpt(null);
      loadStocks(); loadOptions(); loadClosed();
    } catch (e) { setMsg(e.message); }
  };

  const handleExpire = async (o) => {
    const linked = window.prompt(`Record the ${o.ticker} $${o.strike} ${o.type} (${o.expiry}) as expired worthless at $0? `
      + 'Optionally enter a wheel cycle name to link it; leave blank to skip.', '');
    if (linked === null) return;
    try {
      const r = await expireOption(o.id, linked.trim());
      setMsg(r.cycle_error || `Expired worthless: ${o.ticker} $${o.strike} ${o.type}${r.cycle ? ` · linked to ${r.cycle}` : ''}`);
      loadOptions(); loadClosed();
    } catch (e) { setMsg(e.message); }
  };

  const cancelEdit = () => {
    setEditIdx(null);
    setEditOptIdx(null);
    setSellLotId(null);
    setForm({ ticker: '', shares: 1, price: 100 });
    setOptForm({ ticker: '', type: 'call', strike: 100, expiry: '', premium: 2.5, contracts: 1, action: 'bto' });
  };

  // Compute combined realized P/L for the banner
  const realizedStockPnl = closedStocks?.total_realized_pnl || 0;
  const realizedOptPnl = closedOpts?.total_realized_pnl || 0;
  const totalRealizedPnl = realizedStockPnl + realizedOptPnl;
  const holdings = portfolio?.holdings || [];
  const options = optionsSummary?.options || [];
  const version = JSON.stringify([holdings, options, closedStocks, closedOpts, transferRevision, account]);
  const repair = id => {
    const option = options.find(item => item.id === id);
    if (option) { setSection('holdings'); setTab('options'); setView('current'); setRepairOpt(option); }
  };

  return (
    <div className="portfolio-workspace">
      <nav className="sub-tabs" aria-label="Portfolio views">
        {[['holdings', 'Holdings'], ['risk', 'Portfolio Risk'], ['performance', 'Income & Performance']].map(([id, label]) =>
          <button key={id} className={`sub-tab ${section === id ? 'active' : ''}`} onClick={() => setSection(id)}>{label}</button>)}
      </nav>
      <AccountTransfer onImported={() => { loadStocks(); loadOptions(); loadClosed(); setTransferRevision(value => value + 1); }} />
      {!isGuest && <AccountBar account={account} onChange={setAccount} version={version} />}
      {loadError && <p className="error-text" role="alert">{loadError} <button className="link-btn" onClick={() => { setLoadError(null); loadStocks(); loadOptions(); loadClosed(); }}>Retry</button></p>}
      {portfolio?.incomplete && <p className="error-text">Some stock quotes are unavailable. Current value and P&L totals are incomplete.</p>}
      {!portfolio && !loadError && <Skeleton label="Loading holdings" />}
      {portfolio?.as_of && <p className="as-of">Quotes as of {new Date(portfolio.as_of).toLocaleTimeString()}{optionsSummary?.as_of ? ` · option marks ${new Date(optionsSummary.as_of).toLocaleTimeString()}` : ''}</p>}
      {section === 'risk' && <section className="portfolio-section">
        {isGuest ? <p>Sign in to review portfolio risk.</p> : <>
          <h3>Position alerts</h3><Today version={version} onRepair={repair} onAssign={id => { const option = options.find(item => item.id === id); if (option) handleAssign(option); }} />
          <h3>Earnings exposure</h3><Earnings version={version} />
          <PortfolioDoctor key={version} />
          <h3>Stress scenarios</h3><WhatIf options={options} holdings={holdings} />
          {holdings.length >= 2 && <CorrelationHeatmap tickers={[...new Set(holdings.map(item => item.ticker))]} />}
          {holdings.length > 0 && !portfolio?.incomplete && <SectorAllocation holdings={holdings} />}
        </>}
      </section>}
      {section === 'performance' && <section className="portfolio-section">
        {!isGuest && <NavHistory account={account} />}
        {holdings.length > 0 && !portfolio?.incomplete && <PortfolioChart holdings={holdings} closedTrades={closedStocks} />}
        {!isGuest && <PortfolioInsights tickers={[...new Set(holdings.map(item => item.ticker))]} version={version} onImported={loadStocks} />}
      </section>}
      {section === 'holdings' && <>
      {!isGuest && <SplitNotice version={transferRevision} onApplied={() => { loadStocks(); loadOptions(); }} />}
      {/* ── Realized P/L Banner ─────────────────────────── */}
      {(closedStocks?.trades?.length > 0 || closedOpts?.trades?.length > 0) && (
        <div className={`realized-pnl-banner ${totalRealizedPnl >= 0 ? 'banner-positive' : 'banner-negative'}`}>
          <span>Realized P/L</span>
          <strong className={totalRealizedPnl >= 0 ? 'positive' : 'negative'}>
            ${totalRealizedPnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </strong>
          {!isGuest && realizedStockPnl !== 0 && realizedOptPnl !== 0 && (
            <span className="realized-breakdown">
              Stocks: <span className={realizedStockPnl >= 0 ? 'positive' : 'negative'}>${realizedStockPnl.toLocaleString()}</span>
              {' · '}
              Options: <span className={realizedOptPnl >= 0 ? 'positive' : 'negative'}>${realizedOptPnl.toLocaleString()}</span>
            </span>
          )}
        </div>
      )}

      <div className="portfolio-tabs">
        <h3 style={{ margin: 0 }}>Portfolio {isGuest && <span className="guest-badge">Guest</span>}</h3>
        <div className="chart-toggle">
          <button className={tab === 'stocks' ? 'active' : ''} onClick={() => { setTab('stocks'); setView('current'); cancelEdit(); }}>
            Stocks
          </button>
          <button className={tab === 'options' ? 'active' : ''} onClick={() => { setTab('options'); setView('current'); cancelEdit(); }}>
            Options
          </button>
        </div>
      </div>

      {/* ── Current / Sold Sub-Toggle ────────────────────── */}
      <div className="chart-toggle" style={{ marginBottom: '0.75rem' }}>
        <button className={view === 'current' ? 'active' : ''} onClick={() => setView('current')}>
          Current Holdings
        </button>
        <button className={view === 'sold' ? 'active' : ''} onClick={() => setView('sold')}>
          Sold / Closed
        </button>
      </div>

      {isGuest && (
        <p className="guest-note">
          Portfolio saved in this browser only. Sign in to sync across devices and unlock options tracking.
        </p>
      )}

      {msg && <p className="portfolio-msg">{msg}</p>}

      {/* ── Stocks Tab ────────────────────────────────────────── */}
      {tab === 'stocks' && view === 'current' && (
        <>
          <div className="portfolio-form labeled-form">
            {sellLotId !== null && (
              <div className="sell-lot-banner">Selling from lot: <strong>{form.ticker}</strong> — {form.shares} shares @ ${form.price}</div>
            )}
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
              ) : sellLotId !== null ? (
                <>
                  <button className="btn-secondary" onClick={handleSell}>Sell Lot</button>
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

          {portfolio && portfolio.holdings && portfolio.holdings.length > 0 ? (() => {
            // Group holdings by ticker
            const groups = {};
            portfolio.holdings.forEach((h) => {
              if (!groups[h.ticker]) groups[h.ticker] = [];
              groups[h.ticker].push(h);
            });

            return (
              <>
                <div className="metrics-grid" style={{ marginTop: '1rem' }}>
                  <div className="metric">
                    <span className="metric-label">Invested</span>
                    <span className="metric-value">${portfolio.total_invested.toLocaleString()}</span>
                  </div>
                  <div className="metric">
                    <span className="metric-label">Current Value</span>
                    <span className="metric-value">{portfolio.total_current == null ? 'Unavailable' : `$${portfolio.total_current.toLocaleString()}`}</span>
                  </div>
                  <div className={`metric ${portfolio.total_pnl == null ? '' : portfolio.total_pnl >= 0 ? 'metric-positive' : 'metric-negative'}`}>
                    <span className="metric-label">Total P/L</span>
                    <span className={`metric-value ${portfolio.total_pnl == null ? '' : portfolio.total_pnl >= 0 ? 'positive' : 'negative'}`}>
                      {portfolio.total_pnl == null ? 'Unavailable' : `$${portfolio.total_pnl.toLocaleString()} (${portfolio.total_pnl_pct.toFixed(2)}%)`}
                    </span>
                  </div>
                </div>

                <div className="lot-groups">
                  {Object.entries(groups).map(([ticker, lots]) => {
                    const isOpen = !!expanded[ticker];
                    const totalShares = lots.reduce((s, l) => s + l.shares, 0);
                    const totalInvested = lots.reduce((s, l) => s + l.buy_price * l.shares, 0);
                    const avgBuy = totalInvested / totalShares;
                    const currentPrice = lots[0].current_price;
                    const totalCurrent = totalShares * currentPrice;
                    const totalPnl = totalCurrent - totalInvested;
                    const totalPnlPct = totalInvested > 0 ? (totalPnl / totalInvested * 100) : 0;
                    const hasMultipleLots = lots.length > 1;

                    return (
                      <div key={ticker} className="lot-group">
                        <div
                          className={`lot-group-header ${hasMultipleLots ? 'clickable' : ''}`}
                          onClick={() => hasMultipleLots && setExpanded((p) => ({ ...p, [ticker]: !p[ticker] }))}
                        >
                          <span className="lot-toggle">{hasMultipleLots ? (isOpen ? '▼' : '▶') : '•'}</span>
                          <strong className="lot-ticker">{ticker}</strong>
                          {!account && [...new Set(lots.map(l => l.account).filter(a => a && a !== 'Default'))].map(a => <span key={a} className="account-badge">{a}</span>)}
                          <span className="lot-shares">{totalShares} shares</span>
                          {hasMultipleLots && <span className="lot-count">{lots.length} lots</span>}
                          <span className="lot-avg">Avg ${avgBuy.toFixed(2)}</span>
                          <span className="lot-current">{currentPrice == null ? 'Unavailable' : `$${currentPrice.toFixed(2)}`}</span>
                          <span className={`lot-pnl ${currentPrice == null ? '' : totalPnl >= 0 ? 'positive' : 'negative'}`}>
                            {currentPrice == null ? 'Unavailable' : `$${totalPnl.toFixed(2)} (${totalPnlPct.toFixed(2)}%)`}
                          </span>
                          {!hasMultipleLots && (
                            <span className="lot-actions">
                              <button className="btn-icon" title="Sell lot" onClick={(e) => { e.stopPropagation(); startSellLot(lots[0]); }}>💲</button>
                              <button className="btn-icon" title="Edit" onClick={(e) => { e.stopPropagation(); startEditStock(lots[0]); }}>✏️</button>
                              {confirmDelete?.type === 'stock' && confirmDelete?.id === lots[0].id ? (
                                <>
                                  <button className="btn-icon btn-confirm-del" title="Confirm" onClick={(e) => { e.stopPropagation(); handleDeleteStock(lots[0].id); }}>✔</button>
                                  <button className="btn-icon" title="Cancel" onClick={(e) => { e.stopPropagation(); setConfirmDelete(null); }}>✕</button>
                                </>
                              ) : (
                                <button className="btn-icon" title="Delete" onClick={(e) => { e.stopPropagation(); setConfirmDelete({ type: 'stock', id: lots[0].id }); }}>🗑️</button>
                              )}
                            </span>
                          )}
                        </div>
                        {isOpen && (
                          <table className="portfolio-table lot-table">
                            <thead>
                              <tr>
                                <th>Lot #</th>
                                <th>Shares</th>
                                <th>Buy Price</th>
                                <th>Current</th>
                                <th>P/L ($)</th>
                                <th>P/L %</th>
                                <th>Date</th>
                                <th>Actions</th>
                              </tr>
                            </thead>
                            <tbody>
                              {lots.map((h, i) => (
                                <tr key={h.id} className={`lot-row ${editIdx === h.id ? 'row-editing' : ''} ${sellLotId === h.id ? 'row-selling' : ''}`}>
                                  <td>{i + 1}</td>
                                  <td>{h.shares}</td>
                                  <td>${h.buy_price.toFixed(2)}</td>
                                  <td>{h.current_price == null ? 'Unavailable' : `$${h.current_price.toFixed(2)}`}</td>
                                  <td className={h.pnl == null ? '' : h.pnl >= 0 ? 'positive' : 'negative'}>{h.pnl == null ? 'Unavailable' : `$${h.pnl.toFixed(2)}`}</td>
                                  <td className={h.pnl_pct == null ? '' : h.pnl_pct >= 0 ? 'positive' : 'negative'}>{h.pnl_pct == null ? 'Unavailable' : `${h.pnl_pct.toFixed(2)}%`}</td>
                                  <td>{new Date(h.date_added || h.date).toLocaleDateString()}</td>
                                  <td className="action-cell">
                                    <button className="btn-icon" title="Sell this lot" onClick={() => startSellLot(h)}>💲</button>
                                    <button className="btn-icon" title="Edit" onClick={() => startEditStock(h)}>✏️</button>
                                    {confirmDelete?.type === 'stock' && confirmDelete?.id === h.id ? (
                                      <>
                                        <button className="btn-icon btn-confirm-del" title="Confirm" onClick={() => handleDeleteStock(h.id)}>✔</button>
                                        <button className="btn-icon" title="Cancel" onClick={() => setConfirmDelete(null)}>✕</button>
                                      </>
                                    ) : (
                                      <button className="btn-icon" title="Delete" onClick={() => setConfirmDelete({ type: 'stock', id: h.id })}>🗑️</button>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            );
          })() : (
            portfolio && <p className="empty-state">No stock holdings yet.</p>
          )}
        </>
      )}

      {/* ── Sold Stocks ───────────────────────────────────────── */}
      {tab === 'stocks' && view === 'sold' && (
        <>
          {closedStocks?.trades?.length > 0 ? (
            <>
              <div className="metrics-grid" style={{ marginTop: '0.5rem' }}>
                <div className="metric">
                  <span className="metric-label">Closed Trades</span>
                  <span className="metric-value">{closedStocks.trades.length}</span>
                </div>
                <div className={`metric ${closedStocks.total_realized_pnl >= 0 ? 'metric-positive' : 'metric-negative'}`}>
                  <span className="metric-label">Realized P/L</span>
                  <span className={`metric-value ${closedStocks.total_realized_pnl >= 0 ? 'positive' : 'negative'}`}>
                    ${closedStocks.total_realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
              </div>
              <table className="portfolio-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Shares</th>
                    <th>Buy Price</th>
                    <th>Sell Price</th>
                    <th>P/L ($)</th>
                    <th>P/L %</th>
                    <th>Date</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {closedStocks.trades.map((t) => (
                    <tr key={t.id}>
                      <td><strong>{t.ticker}</strong></td>
                      <td>{t.shares}</td>
                      <td>${t.buy_price.toFixed(2)}</td>
                      <td>${t.sell_price.toFixed(2)}</td>
                      <td className={t.pnl >= 0 ? 'positive' : 'negative'}>${t.pnl.toFixed(2)}</td>
                      <td className={t.pnl_pct >= 0 ? 'positive' : 'negative'}>{t.pnl_pct.toFixed(2)}%</td>
                      <td>{new Date(t.closed_at).toLocaleDateString()}</td>
                      <td className="action-cell">
                        {confirmDelete?.type === 'closed-stock' && confirmDelete?.id === t.id ? (
                          <>
                            <button className="btn-icon btn-confirm-del" title="Confirm delete" onClick={() => handleDeleteClosed('closed-stock', t.id)}>✔</button>
                            <button className="btn-icon" title="Cancel" onClick={() => setConfirmDelete(null)}>✕</button>
                          </>
                        ) : (
                          <button className="btn-icon" title="Remove from history" onClick={() => setConfirmDelete({ type: 'closed-stock', id: t.id })}>🗑️</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <p className="empty-state">No sold stocks yet. Sell a position to see it here.</p>
          )}
        </>
      )}

      {/* ── Options Tab ───────────────────────────────────────── */}
      {tab === 'options' && view === 'current' && (
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
                onChange={(e) => setOptForm({ ...optForm, action: e.target.value,
                  premium: ['btc', 'stc'].includes(e.target.value) ? '' : optForm.premium })}>
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
              <label htmlFor="opt-premium">{optForm.action === 'btc' ? 'Buy-back price ($/share)' : optForm.action === 'stc' ? 'Closing sale price ($/share)' : 'Premium ($)'}</label>
              <input id="opt-premium" type="number" placeholder="Actual fill per share" value={optForm.premium} min={0} step="any" required
                onChange={(e) => setOptForm({ ...optForm, premium: e.target.value })} />
            </div>
            <div className="form-field">
              <label htmlFor="opt-contracts">Contracts</label>
              <input id="opt-contracts" type="number" placeholder="Qty" value={optForm.contracts} min={1} step={1}
                onChange={(e) => setOptForm({ ...optForm, contracts: parseInt(e.target.value) || 1 })} />
            </div>
            {['btc', 'stc'].includes(optForm.action) && editOptIdx === null && (
              <div className="form-field">
                <label htmlFor="opt-cycle">Wheel cycle (optional)</label>
                <input id="opt-cycle" type="text" placeholder="e.g. AAPL wheel" value={cycle} maxLength={80}
                  onChange={(e) => setCycle(e.target.value)} />
              </div>
            )}
            <div className="form-actions">
              {editOptIdx !== null ? (
                <>
                  <button className="btn-primary" onClick={handleSaveOptEdit} disabled={!validOptionPremium}>Save</button>
                  <button className="btn-secondary" onClick={cancelEdit}>Cancel</button>
                </>
              ) : (
                <button className="btn-primary" onClick={handleOptionSubmit} disabled={!validOptionPremium}>
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
                  <span className="metric-value">{optionsSummary.total_value == null ? 'Unavailable' : `$${optionsSummary.total_value.toLocaleString()}`}</span>
                </div>
                <div className={`metric ${optionsSummary.total_pnl == null ? '' : optionsSummary.total_pnl >= 0 ? 'metric-positive' : 'metric-negative'}`}>
                  <span className="metric-label">Total P/L</span>
                  <span className={`metric-value ${optionsSummary.total_pnl == null ? '' : optionsSummary.total_pnl >= 0 ? 'positive' : 'negative'}`}>
                    {optionsSummary.total_pnl == null ? 'Incomplete quotes' : `$${optionsSummary.total_pnl.toLocaleString()} (${optionsSummary.total_pnl_pct.toFixed(2)}%)`}
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
                    const moneyness = o.current_price == null ? 'Unknown' : Math.abs(diff) < 0.5 ? 'ATM'
                      : diff > 0 ? 'ITM' : 'OTM';
                    const moneyClass = moneyness === 'ITM' ? 'positive'
                      : moneyness === 'OTM' ? 'negative' : '';
                    const side = o.position || 'long';
                    return (
                    <tr key={o.id || i} className={editOptIdx === o.id ? 'row-editing' : ''}>
                      <td><strong>{o.ticker}</strong>{!account && o.account && o.account !== 'Default' && <span className="account-badge">{o.account}</span>}</td>
                      <td className={o.type === 'call' ? 'positive' : 'negative'}>
                        {o.type.toUpperCase()}
                      </td>
                      <td>
                        <span className={`side-badge side-${side}`}>
                          {side.toUpperCase()}
                        </span>
                      </td>
                      <td>${o.strike.toFixed(2)}</td>
                      <td>{o.current_price == null ? 'Unavailable' : `$${o.current_price.toFixed(2)}`}</td>
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
                      <td title={o.quoted === false
                        ? 'No usable two-sided quote for this exact contract; excluded from valuation'
                        : `Bid: $${(o.bid || 0).toFixed(2)} / Ask: $${(o.ask || 0).toFixed(2)}`}>
                        {o.market_price == null ? 'Unavailable' : `$${o.market_price.toFixed(2)}`}
                      </td>
                      <td title="Implied Volatility">{o.iv ? `${o.iv}%` : '—'}</td>
                      <td className={o.pnl == null ? '' : o.pnl >= 0 ? 'positive' : 'negative'}>
                        {o.pnl == null ? 'Unavailable' : `$${o.pnl.toFixed(2)} (${o.pnl_pct?.toFixed(1) ?? '0'}%)`}
                      </td>
                      <td className="action-cell">
                        <button className="btn-icon" title="Close this option lot" onClick={() => {
                          setEditOptIdx(null); setOptForm({ ticker: o.ticker, type: o.type, strike: o.strike, expiry: o.expiry,
                            premium: '', contracts: o.contracts, action: side === 'short' ? 'btc' : 'stc', option_id: o.id });
                          const priceInput = document.getElementById('opt-premium');
                          priceInput?.scrollIntoView({ block: 'center' });
                          priceInput?.focus();
                        }}>×</button>
                        {side === 'short' && o.dte >= 0 && (
                          <button className="btn-icon" title="Roll / repair this short option"
                            onClick={() => setRepairOpt(repairOpt?.id === o.id ? null : o)}>🔧</button>
                        )}
                        {side === 'short' && (
                          <button className="btn-icon" title={o.type === 'put' ? 'Assigned: add the shares at the strike' : 'Called away: sell the shares at the strike'}
                            onClick={() => handleAssign(o)}>📥</button>
                        )}
                        {o.expired && (
                          <button className="btn-icon" title="Expired worthless: close at $0 on the expiry date" aria-label={`Expired worthless ${o.ticker} ${o.strike} ${o.type}`}
                            onClick={() => handleExpire(o)}>⌛</button>
                        )}
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
              {repairOpt && (
                <div className="card roll-panel" id="roll-panel">
                  <div className="ivrank-header">
                    <h3 style={{ margin: 0 }}>
                      🔧 Roll / repair: {repairOpt.ticker} short ${repairOpt.strike} {repairOpt.type} · {repairOpt.expiry}
                    </h3>
                    <button className="btn-icon" title="Close" onClick={() => setRepairOpt(null)}>✕</button>
                  </div>
                  <RollRepair key={repairOpt.id} ticker={repairOpt.ticker} standalone initial={{
                    strategy: repairOpt.type === 'call' ? 'cc' : 'csp',
                    expiry: repairOpt.expiry, shortStrike: repairOpt.strike, credit: repairOpt.premium,
                  }} />
                </div>
              )}
            </>
          ) : (
            optionsSummary && <p className="empty-state">No options positions yet.</p>
          )}
        </>
        )
      )}

      {/* ── Closed Options ────────────────────────────────────── */}
      {tab === 'options' && view === 'sold' && (
        isGuest ? (
          <div className="empty-state guest-note" style={{ marginTop: '1.5rem' }}>
            Options tracking requires an account. Sign in to view closed options.
          </div>
        ) : (
        <>
          {closedOpts?.trades?.length > 0 ? (
            <>
              <div className="metrics-grid" style={{ marginTop: '0.5rem' }}>
                <div className="metric">
                  <span className="metric-label">Closed Trades</span>
                  <span className="metric-value">{closedOpts.trades.length}</span>
                </div>
                <div className={`metric ${closedOpts.total_realized_pnl >= 0 ? 'metric-positive' : 'metric-negative'}`}>
                  <span className="metric-label">Gross Realized P/L</span>
                  <span className={`metric-value ${closedOpts.total_realized_pnl >= 0 ? 'positive' : 'negative'}`}>
                    ${closedOpts.total_realized_pnl.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                </div>
                <div className="metric"><span className="metric-label">Recorded Fees</span><span className="metric-value">{closedOpts.total_fees == null ? 'Unavailable' : `$${closedOpts.total_fees.toFixed(2)}`}</span></div>
                <div className="metric"><span className="metric-label">Net Realized P/L</span><span className="metric-value">{closedOpts.total_net_pnl == null ? 'Unavailable' : `$${closedOpts.total_net_pnl.toFixed(2)}`}</span></div>
              </div>
              <div className="table-scroll"><table className="portfolio-table">
                <thead>
                  <tr>
                    <th>Ticker</th>
                    <th>Type</th>
                    <th>Side</th>
                    <th>Strike</th>
                    <th>Expiry</th>
                    <th>Qty</th>
                    <th>Open</th>
                    <th>Close</th>
                    <th>Gross P/L ($)</th>
                    <th>Fees ($)</th>
                    <th>Net P/L ($)</th>
                    <th>Gross P/L %</th>
                    <th>Date</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {closedOpts.trades.map((t) => (
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
                      <td className="action-cell">
                        {confirmDelete?.type === 'closed-option' && confirmDelete?.id === t.id ? (
                          <>
                            <button className="btn-icon btn-confirm-del" title="Confirm delete" onClick={() => handleDeleteClosed('closed-option', t.id)}>✔</button>
                            <button className="btn-icon" title="Cancel" onClick={() => setConfirmDelete(null)}>✕</button>
                          </>
                        ) : (
                          <button className="btn-icon" title="Remove from history" onClick={() => setConfirmDelete({ type: 'closed-option', id: t.id })}>🗑️</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
            </>
          ) : (
            <p className="empty-state">No closed options yet. Close a position to see it here.</p>
          )}
        </>
        )
      )}
      {!isGuest && <details className="portfolio-section"><summary>Import from broker CSV</summary><ImportCsv account={account} onImported={() => { loadStocks(); loadOptions(); loadClosed(); }} /></details>}
      </>}
    </div>
  );
}
