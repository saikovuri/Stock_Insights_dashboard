import { useState, useMemo, useCallback } from 'react';
import { fetchMetrics } from '../api/stockApi';

export default function PositionCalculator() {
  const [portfolio, setPortfolio] = useState('');
  const [cashAvailable, setCashAvailable] = useState('');
  const [ticker, setTicker] = useState('');
  const [stockPrice, setStockPrice] = useState(null);
  const [stockName, setStockName] = useState('');
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState('');
  const [allocPct, setAllocPct] = useState('5');
  const [stopLoss, setStopLoss] = useState('');
  const [targetPrice, setTargetPrice] = useState('');

  const lookupTicker = useCallback(async () => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setLoading(true);
    setFetchError('');
    setStockPrice(null);
    setStockName('');
    try {
      const data = await fetchMetrics(t);
      const price = data.price ?? data.currentPrice ?? data.regularMarketPrice;
      if (!price) throw new Error('Price unavailable');
      setStockPrice(price);
      setStockName(data.name || data.shortName || t);
    } catch (err) {
      setFetchError(err.message || 'Ticker not found');
    } finally {
      setLoading(false);
    }
  }, [ticker]);

  const handleTickerKey = (e) => {
    if (e.key === 'Enter') lookupTicker();
  };

  const calc = useMemo(() => {
    const port = parseFloat(portfolio);
    const cash = parseFloat(cashAvailable);
    const alloc = parseFloat(allocPct) / 100;
    const price = stockPrice;
    const stop = parseFloat(stopLoss);
    const target = parseFloat(targetPrice);

    if (!port || port <= 0 || !price || price <= 0 || !alloc) return null;
    const availCash = cash > 0 ? cash : port;

    // Desired position
    const desiredAmount = port * alloc;
    const idealShares = Math.floor(desiredAmount / price);

    // Cash constraint
    const cashConstrained = desiredAmount > availCash;
    const actualShares = cashConstrained ? Math.floor(availCash / price) : idealShares;
    const capitalDeployed = actualShares * price;
    const actualPct = (capitalDeployed / port) * 100;
    const remainingCash = availCash - capitalDeployed;

    // SL/PT scenarios (optional)
    let slLoss = null, slLossPct = null, riskPerShare = null, stopPct = null;
    if (stop > 0 && stop !== price) {
      riskPerShare = Math.abs(price - stop);
      stopPct = (riskPerShare / price) * 100;
      slLoss = actualShares * riskPerShare;
      slLossPct = (slLoss / port) * 100;
    }

    let ptGain = null, ptGainPct = null, rr = null;
    if (target > 0 && target !== price) {
      const gainPerShare = Math.abs(target - price);
      ptGain = actualShares * gainPerShare;
      ptGainPct = (ptGain / port) * 100;
      if (riskPerShare) rr = gainPerShare / riskPerShare;
    }

    return {
      desiredAmount, idealShares, cashConstrained,
      actualShares, capitalDeployed, actualPct, remainingCash,
      availCash, price,
      slLoss, slLossPct, riskPerShare, stopPct,
      ptGain, ptGainPct, rr,
    };
  }, [portfolio, cashAvailable, allocPct, stockPrice, stopLoss, targetPrice]);

  const fmt = (v, d = 0) => v.toLocaleString(undefined, { maximumFractionDigits: d });

  return (
    <div className="tool-card">
      <h3>🎯 Position Size Calculator</h3>
      <p className="tool-desc">How many shares to buy for your desired portfolio allocation.</p>

      <div className="tool-form">
        {/* Row 1: Portfolio + Cash */}
        <div className="pos-account-row">
          <div className="tool-row">
            <label>Total Portfolio Value ($)</label>
            <input type="number" className="tool-input" placeholder="e.g. 10000"
              value={portfolio} onChange={e => setPortfolio(e.target.value)} />
          </div>
          <div className="tool-row">
            <label>Available Cash ($) <span className="optional">uninvested</span></label>
            <input type="number" className="tool-input" placeholder="e.g. 3000"
              value={cashAvailable} onChange={e => setCashAvailable(e.target.value)} />
          </div>
        </div>

        {/* Row 2: Ticker lookup */}
        <div className="tool-row">
          <label>Ticker</label>
          <div className="pos-ticker-row">
            <input type="text" className="tool-input" placeholder="e.g. AAPL"
              value={ticker} onChange={e => setTicker(e.target.value)} onKeyDown={handleTickerKey} />
            <button className="pos-lookup-btn" onClick={lookupTicker} disabled={loading || !ticker.trim()}>
              {loading ? '...' : 'Lookup'}
            </button>
          </div>
          {fetchError && <span className="pos-fetch-error">{fetchError}</span>}
          {stockPrice && (
            <span className="pos-price-tag">{stockName} — ${stockPrice.toFixed(2)}</span>
          )}
        </div>

        {/* Row 3: Allocation slider */}
        <div className="tool-row">
          <label>Allocate <strong>{allocPct}%</strong> of portfolio to this position</label>
          <div className="tool-risk-row">
            <input type="range" min="1" max="25" step="1" value={allocPct}
              onChange={e => setAllocPct(e.target.value)} />
            <span className="tool-risk-val">{allocPct}%</span>
          </div>
          {portfolio && stockPrice && (
            <span className="pos-alloc-hint">
              {allocPct}% of ${fmt(parseFloat(portfolio))} = ${fmt(parseFloat(portfolio) * parseFloat(allocPct) / 100, 2)}
            </span>
          )}
        </div>

        {/* Row 4: SL & PT */}
        <div className="pos-sltp-row">
          <div className="tool-row">
            <label>Stop Loss ($) <span className="optional">optional</span></label>
            <input type="number" className="tool-input" placeholder="e.g. 140.00"
              value={stopLoss} onChange={e => setStopLoss(e.target.value)} />
          </div>
          <div className="tool-row">
            <label>Price Target ($) <span className="optional">optional</span></label>
            <input type="number" className="tool-input" placeholder="e.g. 180.00"
              value={targetPrice} onChange={e => setTargetPrice(e.target.value)} />
          </div>
        </div>
      </div>

      {/* ── Results ── */}
      {calc && (
        <div className="tool-result">

          {/* Hero answer */}
          <div className="pos-answer">
            <div className="pos-answer-shares">{calc.actualShares}</div>
            <div className="pos-answer-label">shares of {ticker.toUpperCase()}</div>
            <div className="pos-answer-sub">
              {calc.actualShares} × ${calc.price.toFixed(2)} = <strong>${fmt(calc.capitalDeployed, 2)}</strong>
              &nbsp;·&nbsp;{calc.actualPct.toFixed(1)}% of portfolio
              &nbsp;·&nbsp;<strong>${fmt(calc.remainingCash, 2)}</strong> cash left
            </div>
          </div>

          {/* Cash constraint warning */}
          {calc.cashConstrained && (
            <div className="pos-cash-warning">
              ⚠️ For <strong>{allocPct}%</strong> allocation you'd need <strong>${fmt(calc.desiredAmount, 2)}</strong>,
              but you only have <strong>${fmt(calc.availCash, 2)}</strong> in cash.
              You can buy <strong>{calc.actualShares}</strong> shares instead, which is <strong>{calc.actualPct.toFixed(1)}%</strong> of your portfolio.
            </div>
          )}

          {/* SL / PT scenario cards */}
          {(calc.slLoss != null || calc.ptGain != null) && (
            <div className="pos-scenarios">
              {calc.slLoss != null ? (
                <div className="pos-scenario pos-scenario-bad">
                  <div className="pos-scenario-title">📉 If stop hit (${parseFloat(stopLoss).toFixed(2)})</div>
                  <div className="pos-scenario-amount loss">−${fmt(calc.slLoss, 2)}</div>
                  <div className="pos-scenario-pct">{calc.slLossPct.toFixed(2)}% of portfolio</div>
                  <div className="pos-scenario-note">{calc.stopPct.toFixed(1)}% below entry</div>
                </div>
              ) : (
                <div className="pos-scenario pos-scenario-neutral">
                  <div className="pos-scenario-title">📉 No stop loss set</div>
                  <div className="pos-scenario-amount">—</div>
                </div>
              )}

              {calc.ptGain != null ? (
                <div className="pos-scenario pos-scenario-good">
                  <div className="pos-scenario-title">📈 If target hit (${parseFloat(targetPrice).toFixed(2)})</div>
                  <div className="pos-scenario-amount gain">+${fmt(calc.ptGain, 2)}</div>
                  <div className="pos-scenario-pct">{calc.ptGainPct.toFixed(2)}% of portfolio</div>
                  {calc.rr && <div className="pos-scenario-note">Risk : Reward = 1 : {calc.rr.toFixed(2)}</div>}
                </div>
              ) : (
                <div className="pos-scenario pos-scenario-neutral">
                  <div className="pos-scenario-title">📈 No price target set</div>
                  <div className="pos-scenario-amount">—</div>
                </div>
              )}
            </div>
          )}

          {/* Detail breakdown */}
          <div className="pos-details-grid">
            <div className="pos-detail-row">
              <span>Desired allocation</span>
              <span>{allocPct}% → ${fmt(calc.desiredAmount, 2)}</span>
            </div>
            <div className="pos-detail-row">
              <span>Ideal shares</span>
              <span>{calc.idealShares} shares</span>
            </div>
            <div className="pos-detail-row">
              <span>Actual shares (after cash check)</span>
              <span>{calc.actualShares} shares → ${fmt(calc.capitalDeployed, 2)}</span>
            </div>
            <div className="pos-detail-row">
              <span>Actual allocation</span>
              <strong>{calc.actualPct.toFixed(1)}%</strong>
            </div>
          </div>

        </div>
      )}
    </div>
  );
}
