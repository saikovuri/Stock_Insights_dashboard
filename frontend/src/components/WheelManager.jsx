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
  const [shares, setShares] = useState(preset?.shares || 100);
  const [cadence, setCadence] = useState('all');
  const [selectedDate, setSelectedDate] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const run = async (t = ticker, b = basis, s = shares) => {
    setLoading(true); setError(null); setData(null);
    try {
      const result = await fetchAssignedCalls(t.trim().toUpperCase(), Number(b), s, cadence);
      setData(result);
      setSelectedDate(result.expiry || '');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { if (preset?.ticker && preset?.costBasis) run(preset.ticker, preset.costBasis, preset.shares || 100); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selected = data?.expirations?.find(option => option.date === selectedDate) ?? data?.expirations?.[0];
  const ideas = selected?.ideas ?? data?.ideas ?? [];
  const expiry = selected?.date ?? data?.expiry;
  const days = selected?.dte ?? data?.dte;
  const earningsOverlap = selected?.earnings_before_expiry ?? data?.earnings_before_expiry;

  return (
    <>
      <p className="structures-intro">
        Calls at or above your entered cost cap the shares' upside. Premium offsets some downside, but does not
        protect against a large stock loss. Fees and any buy-back cost reduce the outcome.
      </p>
      <div className="income-controls">
        <label>Ticker
          <input className="tool-input" value={ticker} disabled={loading} placeholder="e.g. AAPL" onChange={e => { setTicker(e.target.value); setData(null); }} />
        </label>
        <label>Cost per share ($)
          <input type="number" className="tool-input" min={0} step={0.01} value={basis} disabled={loading}
            placeholder="strike − premium" onChange={e => { setBasis(e.target.value); setData(null); }} />
        </label>
        <label>Shares
          <input type="number" className="tool-input" min={100} step={100} value={shares} disabled={loading}
            onChange={e => { setShares(Math.max(100, Number(e.target.value) || 100)); setData(null); }} />
        </label>
        <label>Expiry horizon
          <select className="tool-input covered-call-horizon" value={cadence} disabled={loading} onChange={e => { setCadence(e.target.value); setData(null); }}>
            <option value="all">All dates (0-120 days)</option>
            <option value="weekly">Weekly (1-7 days)</option>
            <option value="leaps">Long-dated / LEAPS (6-26 months)</option>
          </select>
        </label>
        <button className="btn-primary btn-sm" disabled={!ticker.trim() || !(Number(basis) > 0) || loading} onClick={() => run()}>
          {loading ? 'Loading…' : 'Suggest covered calls'}
        </button>
      </div>
      {cadence === 'weekly' && <p className="ivrank-note">Weekly calls have higher near-expiry gamma risk and less time to adjust.</p>}
      {cadence === 'leaps' && <p className="ivrank-note">A long-dated call pays more up front but gives the stock months or years to rise through the strike. Buying it back after a rally can cost more than the premium received.</p>}
      {error && <p className="empty-state" role="alert">{error}</p>}
      {data && (
        <>
          <div className={`income-warning ${data.unrealized_pct < 0 ? 'income-er' : ''}`}>
            <strong>
              {data.ticker} ${data.spot} vs your cost ${data.cost_basis} ({data.unrealized_pct > 0 ? '+' : ''}{data.unrealized_pct}%)
              · {data.contracts} contract{data.contracts === 1 ? '' : 's'}
              {expiry && <> · expiry {fmtDate(expiry)}{(selected?.monthly ?? data.monthly) ? ' (monthly)' : ''} ({days}d)</>}
            </strong>
            <div>{data.note}</div>
            {earningsOverlap && <div>⚠️ Earnings {fmtDate(data.earnings_date)} before expiry — a gap up can call the shares away.</div>}
            {data.unrealized_pct >= 50 && <div>⚠️ Shares are {data.unrealized_pct}% above your cost. Assignment sells them and realizes that gain (taxable outside retirement accounts). If you want to keep them, favor "Keep the shares" strikes, and buy back or roll up and out before the stock reaches the strike.</div>}
            {days === 0 && <div className="negative">Expires today: elevated gamma risk and limited time to adjust. Annualized returns are not forecasts.</div>}
          </div>
          {!!data.expirations?.length && <div className="income-controls">
            <label>Eligible expiry
              <select className="tool-input covered-call-dates" value={selected?.date || ''} onChange={event => setSelectedDate(event.target.value)}>
                {data.expirations.map(option => <option key={option.date} value={option.date}>
                  {option.date} ({option.dte}d) - {option.ideas.length} strikes
                </option>)}
              </select>
            </label>
          </div>}
          {data.checked_expirations != null && <p className="ivrank-note">
            {data.expirations.length} qualifying dates; {data.skipped_expirations} dates skipped with no qualifying strikes.
          </p>}
          {!!data.unavailable_expirations?.length && <p className="ivrank-note negative" role="status">
            Quotes unavailable for {data.unavailable_expirations.length} dates ({data.unavailable_expirations.join(', ')}). Results are incomplete.
          </p>}
          {ideas.length ? (
            <div className="structures-grid income-grid">
              {ideas.map(i => {
                const [liqText, liqCls] = LIQ[i.liquidity] || LIQ.ok;
                return (
                  <div key={i.strike + i.expiry} className="structure-card covered-call-card">
                    <div className="structure-title">{i.label} <span className="income-delta">Δ {i.delta}</span> <Tip term="delta" /></div>
                    <div className="structure-legs">
                      <div className="structure-leg leg-sell">
                        SELL {data.contracts} × ${i.strike} call · {fmtDate(i.expiry)} ({i.dte}d) @ ${i.mid}
                        <span className="structure-leg-oi"> · OI {i.open_interest.toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="structure-stats">
                      <div><span>Premium</span><strong className="positive">{money(i.total_premium)}</strong></div>
                      <div><span>Bid / ask</span><strong>{i.bid == null || i.ask == null ? 'Unavailable' : `$${i.bid.toFixed(2)} / $${i.ask.toFixed(2)}`}</strong></div>
                      <div className="covered-call-cost"><span>Projected cost/share</span><strong>
                        {i.premium_adjusted_cost == null ? 'Unavailable' : i.premium_adjusted_cost.toLocaleString('en-US', { style: 'currency', currency: 'USD' })}
                      </strong></div>
                      {i.yield_pct != null
                        ? <div><span>Yield on stock value</span><strong>{i.yield_pct}% <small>({i.yield_annualized_pct}%/yr)</small></strong></div>
                        : <div><span>Return on cost</span><strong>{i.return_pct}% <small>({i.annualized_pct}%/yr)</small></strong></div>}
                      <div><span>Strike above price</span><strong>+{i.otm_pct}%</strong></div>
                      {i.if_called_from_today_pct != null
                        ? <div><span>Gain from today if called</span><strong className="positive">{i.if_called_from_today_pct}%</strong></div>
                        : <div><span>Total gain if called</span><strong className="positive">{i.if_called_pct}%</strong></div>}
                      {i.gain_realized_if_called > 0 && <div><span>Gain realized if called</span><strong>{money(i.gain_realized_if_called)}</strong></div>}
                      <div><span>Chance of being called</span><strong>~{i.prob_called_pct}%</strong></div>
                      <div><span>Liquidity</span><strong className={liqCls}>{liqText}</strong></div>
                      {i.spread_pct != null && <div><span>Bid/ask spread</span><strong>{i.spread_pct}%</strong></div>}
                    </div>
                    {i.upside_cap && <p className="ivrank-note covered-call-cap">
                      Upside protection: also buy the ${i.upside_cap.strike} call @ ${i.upside_cap.mid} for a net {money(i.upside_cap.total_net)} credit.
                      Above ${i.upside_cap.strike} the long call gains as fast as the short call loses, so you only give up the move
                      from ${i.strike} to ${i.upside_cap.strike}.
                    </p>}
                  </div>
                );
              })}
            </div>
          ) : (
            <p className="empty-state">{data.cadence === 'weekly'
              ? 'No eligible covered calls at or above your cost in the 1-7 day window. No longer-dated fallback was used.'
              : 'No eligible covered-call suggestions at or above your cost were found.'}</p>
          )}
          {!!ideas.length && <p className="ivrank-note">Projected cost/share = entered cost minus quoted total call premium divided by {data.shares} shares.
            Assumes a fill at the quoted midpoint and excludes fees and buy-back costs. Premium received is not realized option profit while the call is open.
            This scenario does not change recorded holdings or tax basis.</p>}
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
