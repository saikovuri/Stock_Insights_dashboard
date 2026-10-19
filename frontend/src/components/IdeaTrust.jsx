import { useEffect, useState } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid } from 'recharts';
import { fetchTrackRecord, openPaperTrade } from '../api/stockApi';
import { useOptionalAuth } from '../AuthContext';

const usd = value => `${value < 0 ? '-' : ''}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
export const MIN_SETTLED = 10;

// One shared request per page load (refreshed after 10 minutes): every card reads the same summary
let trackCache = null;
function loadTrackRecord() {
  if (!trackCache || Date.now() - trackCache.at > 600000) {
    const promise = fetchTrackRecord().catch(error => { trackCache = null; throw error; });
    trackCache = { at: Date.now(), promise };
  }
  return trackCache.promise;
}
export function resetTrackRecordCache() { trackCache = null; }

/** Settled history of ideas like this one (same idea type and label), across every ticker the app has suggested. */
export function PastResults({ kind, label = null }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    let active = true;
    loadTrackRecord().then(data => { if (active) setState({ data }); }).catch(() => { if (active) setState({ error: true }); });
    return () => { active = false; };
  }, []);
  if (state.loading || state.error) return null;
  const group = state.data.groups?.find(g => g.kind === kind && (g.label ?? null) === (label ?? null));
  const title = 'Hypothetical ideas this app showed before, entered at the midpoint less a small cost model and scored at expiry. '
    + 'Not executed trades; ideas on the same days are related, so this is a sanity check, not proof of an edge.';
  if (!group) return <p className="past-results market-sub" title={title}>📊 No settled ideas like this yet, so there is no track record to judge it by.</p>;
  if (group.ideas < MIN_SETTLED) {
    return <p className="past-results market-sub" title={title}>📊 Only {group.ideas} idea{group.ideas === 1 ? '' : 's'} like this {group.ideas === 1 ? 'has' : 'have'} settled so far: too few to judge.</p>;
  }
  const avg = group.avg_return_on_risk_pct;
  return <p className="past-results" title={title}>
    📊 <strong>Past ideas like this</strong> (all tickers, at expiry): {group.ideas} settled · <strong>{group.win_rate}% won</strong>
    {avg != null && <> · average <span className={avg >= 0 ? 'positive' : 'negative'}>{avg > 0 ? '+' : ''}{avg}%</span> of the amount at risk</>}
    {group.worst_pct != null && <> · worst {group.worst_pct}%</>}
  </p>;
}

const sign = leg => (leg.position === 'long' ? 1 : -1);
const legValue = (leg, price) => (leg.option_type === 'stock' ? price
  : leg.option_type === 'call' ? Math.max(price - leg.strike, 0) : Math.max(leg.strike - price, 0));

/** P/L curve at expiry. legs: {position, option_type ('call'|'put'|'stock'), strike, ratio}; net: per-share amount paid
 * (a credit is negative); units: number of structures (shares count as one option per 100 shares). */
export function payoffPoints(legs, net, units, spot) {
  const strikes = legs.filter(l => l.option_type !== 'stock').map(l => Number(l.strike));
  const anchors = [...strikes, spot].filter(v => Number.isFinite(v) && v > 0);
  const lo = Math.max(0, Math.min(...anchors) * 0.8), hi = Math.max(...anchors) * 1.2;
  const prices = new Set([...Array.from({ length: 61 }, (_, i) => lo + (hi - lo) * i / 60), ...anchors]);
  return [...prices].sort((a, b) => a - b).map(price => {
    const pnl = (legs.reduce((sum, l) => sum + sign(l) * (l.ratio || 1) * legValue(l, price), 0) - net) * 100 * units;
    return { price: Math.round(price * 100) / 100, pnl: Math.round(pnl * 100) / 100, profit: Math.max(pnl, 0), loss: Math.min(pnl, 0) };
  });
}

export function PayoffChart({ legs, net, units = 1, spot, height = 180 }) {
  const points = payoffPoints(legs, net, units, spot);
  return <div className="payoff-chart" aria-label="Profit or loss at expiry by stock price">
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
        <XAxis dataKey="price" type="number" domain={['dataMin', 'dataMax']} tickFormatter={v => `$${Math.round(v)}`} fontSize={11} />
        <YAxis tickFormatter={usd} fontSize={11} width={56} />
        <Tooltip formatter={(value, name, item) => [usd(item.payload.pnl), 'P/L at expiry']} labelFormatter={v => `Stock at $${v}`} />
        <ReferenceLine y={0} stroke="var(--text-muted)" />
        {Number.isFinite(spot) && <ReferenceLine x={spot} stroke="#7c6cf0" strokeDasharray="4 3" label={{ value: 'Now', fill: '#7c6cf0', fontSize: 11, position: 'top' }} />}
        <Area dataKey="profit" type="linear" stroke="#34d399" fill="rgba(52,211,153,0.25)" isAnimationActive={false} />
        <Area dataKey="loss" type="linear" stroke="#f87171" fill="rgba(248,113,113,0.25)" isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  </div>;
}

/** Collapsed by default; the chart only renders once opened. */
export function PayoffToggle({ multiExpiry = false, ...props }) {
  const [open, setOpen] = useState(false);
  return <details className="payoff-toggle" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>📈 Profit/loss at expiry</summary>
    {multiExpiry ? <p className="market-sub">Calendars and diagonals have no single expiry curve: the later leg&apos;s value depends on volatility.</p>
      : open && <PayoffChart {...props} />}
  </details>;
}

/** Records an idea as a paper (practice) trade at a realistic fill quoted now. */
export function PaperTradeButton({ ticker, legs, contracts = 1, source, label }) {
  const { user } = useOptionalAuth() || {};
  const [state, setState] = useState(null);
  if (!user) return null;
  const record = async () => {
    setState({ busy: true });
    try {
      const trade = await openPaperTrade({ ticker, contracts, source, label,
        legs: legs.map(l => ({ position: l.position, option_type: l.option_type, strike: Number(l.strike), expiry: l.expiry, ratio: l.ratio || 1 })) });
      setState({ done: `Paper trade recorded: ${trade.style} of $${Math.abs(trade.entry).toFixed(2)}/share at a realistic fill. Track it in Journal → Paper trades.` });
    } catch (error) { setState({ error: error.message }); }
  };
  return <div className="paper-trade">
    <button type="button" className="btn-secondary btn-sm" disabled={state?.busy || Boolean(state?.done)} onClick={record}
      title="Practice this idea without real money: it is tracked to expiry in Journal → Paper trades, apart from your portfolio">
      {state?.busy ? 'Recording…' : state?.done ? '✓ Paper trade recorded' : '📝 Paper trade'}</button>
    {state?.done && <span className="market-sub" role="status"> {state.done}</span>}
    {state?.error && <span className="error-text" role="alert"> {state.error}</span>}
  </div>;
}
