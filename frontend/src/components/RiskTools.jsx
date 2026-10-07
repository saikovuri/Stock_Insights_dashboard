import { useEffect, useState } from 'react';
import { fetchTradingRules, saveTradingRules, fetchTrimPlan } from '../api/stockApi';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const NUMBER_RULES = [
  ['max_position_pct', 'Max % of stock value in one stock', 1, 100],
  ['min_free_cash_pct', 'Keep at least this % of each account as free cash', 0, 100],
  ['take_profit_pct', 'Take profit on short options at % of premium captured', 1, 100],
];

export function TradingRules({ onSaved }) {
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetchTradingRules().then(rules => setForm(Object.fromEntries(Object.entries(rules).map(([k, v]) => [k, v ?? '']))))
      .catch(e => setMsg(e.message));
  }, []);
  if (!form) return msg ? <p className="error-text">{msg}</p> : <p className="loading-text">Loading your rules…</p>;
  const save = async event => {
    event.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const body = { ...form };
      NUMBER_RULES.forEach(([key]) => { body[key] = form[key] === '' ? null : Number(form[key]); });
      await saveTradingRules(body);
      setMsg('Rules saved. Broken rules show in Suggested next steps and in a daily notification.');
      onSaved?.();
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  return <form className="trading-rules" onSubmit={save} aria-label="My trading rules">
    <p className="structures-intro">Rules you set for yourself. Leave a number blank to turn that rule off.</p>
    {NUMBER_RULES.map(([key, label, min, max]) => <label key={key}>{label}
      <input className="tool-input" type="number" min={min} max={max} step="any" value={form[key]}
        onChange={e => setForm({ ...form, [key]: e.target.value })} placeholder="off" /></label>)}
    <label className="checkbox-row"><input type="checkbox" checked={!!form.no_calls_below_cost}
      onChange={e => setForm({ ...form, no_calls_below_cost: e.target.checked })} /> Never sell a call below my average cost</label>
    <label className="checkbox-row"><input type="checkbox" checked={!!form.no_short_through_earnings}
      onChange={e => setForm({ ...form, no_short_through_earnings: e.target.checked })} /> No short options open through earnings</label>
    <button className="btn-primary btn-sm" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save rules'}</button>
    {msg && <p className="notif-msg" role="status">{msg}</p>}
  </form>;
}

export function TrimPlanner({ tickers, initialTicker }) {
  const [ticker, setTicker] = useState(initialTicker || tickers[0] || '');
  const [target, setTarget] = useState(30);
  const [steps, setSteps] = useState(4);
  const [spacing, setSpacing] = useState(5);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (initialTicker) { setTicker(initialTicker); setData(null); } }, [initialTicker]);
  if (!tickers.length) return <p className="empty-state">Record stock holdings to plan a trim.</p>;
  const run = async () => {
    setBusy(true); setError(null); setData(null);
    try { setData(await fetchTrimPlan(ticker, target, steps, spacing)); } catch (e) { setError(e.message); }
    setBusy(false);
  };
  return <div className="trim-planner">
    <p className="structures-intro">Sizes the sales needed to bring one stock down to a target share of your stock value, split into steps
      at rising prices, with the gain each step would realize. Selling covered calls at each step&apos;s price is a way to get paid while waiting.</p>
    <div className="income-controls">
      <label>Stock<select className="tool-input" value={ticker} onChange={e => { setTicker(e.target.value); setData(null); }}>
        {tickers.map(t => <option key={t} value={t}>{t}</option>)}</select></label>
      <label>Target weight (%)<input className="tool-input" type="number" min={1} max={95} value={target} onChange={e => { setTarget(Number(e.target.value)); setData(null); }} /></label>
      <label>Steps<input className="tool-input" type="number" min={1} max={12} value={steps} onChange={e => { setSteps(Number(e.target.value)); setData(null); }} /></label>
      <label>Price step (%)<input className="tool-input" type="number" min={0} max={50} step="any" value={spacing} onChange={e => { setSpacing(Number(e.target.value)); setData(null); }} /></label>
      <button className="btn-primary btn-sm" disabled={busy || !ticker} onClick={run}>{busy ? 'Planning…' : 'Plan trim'}</button>
    </div>
    {error && <p className="error-text" role="alert">{error}</p>}
    {data && (data.shares_to_sell === 0
      ? <p className="empty-state">{data.ticker} is {data.current_pct}% of your stock value, already at or below {data.target_pct}%.</p>
      : <>
        <p className="market-sub">{data.ticker} is <strong>{data.current_pct}%</strong> of stock value at ${data.price}. Selling about <strong>{data.shares_to_sell}</strong> of {data.shares_held} shares
          reaches {data.target_pct}% · proceeds {usd(data.total_proceeds)} · realized gain {usd(data.total_short_term_gain)} short-term, {usd(data.total_long_term_gain)} long-term.</p>
        <div className="table-scroll"><table className="market-table" aria-label="Trim steps">
          <thead><tr><th>Step</th><th>Sell at</th><th>Shares</th><th>Proceeds</th><th>Gain (short / long)</th><th>Weight after</th><th>Or sell calls</th></tr></thead>
          <tbody>{data.tranches.map(step => <tr key={step.step} className="no-click"><td>{step.step}</td><td>${step.price}</td><td>{step.shares}</td>
            <td>{usd(step.proceeds)}</td><td>{usd(step.short_term_gain)} / {usd(step.long_term_gain)}</td><td>{step.weight_after_pct}%</td>
            <td>{step.covered_call_contracts ? `${step.covered_call_contracts} × $${Math.round(step.price)} call` : '—'}</td></tr>)}</tbody>
        </table></div>
        <p className="market-sub">{data.note} Spreading steps across two calendar years spreads the realized gain across two tax years.</p>
      </>)}
  </div>;
}
