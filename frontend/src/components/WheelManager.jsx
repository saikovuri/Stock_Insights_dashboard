import { useState, useEffect } from 'react';
import { fetchAssignedCalls } from '../api/stockApi';
import RollRepair from './RollRepair';
import Tip from './Tip';

const LIQ = { good: ['Liquid', 'positive'], ok: ['OK liquidity', ''], thin: ['Thin', 'negative'] };
const money = v => `$${Math.round(v).toLocaleString()}`;
const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

function CoveredCalls({ preset }) {
  const [ticker, setTicker] = useState(preset?.ticker || '');
  const [basis, setBasis] = useState(preset?.costBasis ?? '');
  const [shares, setShares] = useState(100);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async (t = ticker, b = basis, s = shares) => {
    setLoading(true); setError(null); setData(null);
    try {
      setData(await fetchAssignedCalls(t.trim().toUpperCase(), Number(b), s));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { if (preset?.ticker && preset?.costBasis) run(preset.ticker, preset.costBasis, 100); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <p className="structures-intro">
        Assigned on a put? Now you own the shares. Sell a call <b>at or above your cost</b> each month: you keep the
        premium, and if the shares get called away you still exit at a profit. Repeat until called, then go back to
        selling puts.
      </p>
      <div className="income-controls">
        <label>Ticker
          <input className="tool-input" value={ticker} placeholder="e.g. AAPL" onChange={e => setTicker(e.target.value)} />
        </label>
        <label>Cost per share ($)
          <input type="number" className="tool-input" min={0} step={0.01} value={basis}
            placeholder="strike − premium" onChange={e => setBasis(e.target.value)} />
        </label>
        <label>Shares
          <input type="number" className="tool-input" min={100} step={100} value={shares}
            onChange={e => setShares(Math.max(100, Number(e.target.value) || 100))} />
        </label>
        <button className="btn-primary btn-sm" disabled={!ticker.trim() || !(Number(basis) > 0) || loading} onClick={() => run()}>
          {loading ? 'Loading…' : 'Suggest covered calls'}
        </button>
      </div>
      {error && <p className="empty-state">{error}</p>}
      {data && (
        <>
          <div className={`income-warning ${data.unrealized_pct < 0 ? 'income-er' : ''}`}>
            <strong>
              {data.ticker} ${data.spot} vs your cost ${data.cost_basis} ({data.unrealized_pct > 0 ? '+' : ''}{data.unrealized_pct}%)
              · {data.contracts} contract{data.contracts === 1 ? '' : 's'} · expiry {fmtDate(data.expiry)}{data.monthly ? ' (monthly)' : ''} ({data.dte}d)
            </strong>
            <div>{data.note}</div>
            {data.earnings_before_expiry && <div>⚠️ Earnings {fmtDate(data.earnings_date)} before expiry — a gap up can call the shares away.</div>}
          </div>
          {data.ideas.length ? (
            <div className="structures-grid income-grid">
              {data.ideas.map(i => {
                const [liqText, liqCls] = LIQ[i.liquidity] || LIQ.ok;
                return (
                  <div key={i.strike + i.expiry} className="structure-card">
                    <div className="structure-title">{i.label} <span className="income-delta">Δ {i.delta}</span> <Tip term="delta" /></div>
                    <div className="structure-legs">
                      <div className="structure-leg leg-sell">
                        SELL {data.contracts} × ${i.strike} call · {fmtDate(i.expiry)} ({i.dte}d) @ ${i.mid}
                        <span className="structure-leg-oi"> · OI {i.open_interest.toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="structure-stats">
                      <div><span>Premium</span><strong className="positive">{money(i.total_premium)}</strong></div>
                      <div><span>Return on cost</span><strong>{i.return_pct}% <small>({i.annualized_pct}%/yr)</small></strong></div>
                      <div><span>Strike above price</span><strong>+{i.otm_pct}%</strong></div>
                      <div><span>Total gain if called</span><strong className="positive">{i.if_called_pct}%</strong></div>
                      <div><span>Chance of being called</span><strong>~{i.prob_called_pct}%</strong></div>
                      <div><span>Liquidity</span><strong className={liqCls}>{liqText}</strong></div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="empty-state">No call at or above your cost pays anything within 4 months — hold the shares and check again after a bounce.</p>
          )}
        </>
      )}
    </>
  );
}

export default function WheelManager({ preset }) {
  const [mode, setMode] = useState(preset?.mode || 'repair');
  const [ticker, setTicker] = useState(preset?.ticker || '');
  useEffect(() => { if (preset) { setMode(preset.mode); setTicker(preset.ticker); } }, [preset]);

  return (
    <div className="card wheel-manager" id="wheel-manager">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🛠 Manage a wheel position</h3>
        <div className="chart-toggle">
          <button className={mode === 'repair' ? 'active' : ''} onClick={() => setMode('repair')}>🔧 Put tested</button>
          <button className={mode === 'assigned' ? 'active' : ''} onClick={() => setMode('assigned')}>📞 Assigned</button>
        </div>
      </div>
      {mode === 'repair' ? (
        <>
          {!preset?.strike && (
            <div className="income-controls">
              <label>Ticker
                <input className="tool-input" value={ticker} placeholder="e.g. AAPL" onChange={e => setTicker(e.target.value.toUpperCase())} />
              </label>
            </div>
          )}
          {ticker.trim() && (
            <RollRepair key={JSON.stringify(preset) + (preset?.strike ? '' : ticker)} ticker={ticker.trim()} standalone mode="csp"
              initial={preset?.mode === 'repair' && preset.strike ? {
                strategy: 'csp', expiry: preset.expiry, shortStrike: preset.strike, credit: preset.credit,
              } : undefined} />
          )}
        </>
      ) : (
        <CoveredCalls key={JSON.stringify(preset)} preset={preset?.mode === 'assigned' ? preset : null} />
      )}
    </div>
  );
}
