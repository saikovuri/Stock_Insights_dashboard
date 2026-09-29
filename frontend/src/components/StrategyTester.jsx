import { useState, useEffect } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts';
import { fetchBacktestStrategies, runBacktest, compareBacktests } from '../api/stockApi';

const TF_LABELS = { '1m': '1 min (7 days)', '3m': '3 min (7 days)', '5m': '5 min (60 days)', '15m': '15 min (60 days)', '1h': '1 hour (1 year)', '1d': 'Daily (5 years)' };
const PARAM_LABELS = {
  fast: 'Fast', slow: 'Slow', vwap_filter: 'VWAP filter (0/1)', bb_len: 'BB length', ao_fast: 'AO fast', ao_slow: 'AO slow',
  signal: 'Signal', atr_len: 'ATR length', mult: 'Multiplier', length: 'Length', lower: 'Lower', upper: 'Upper', minutes: 'Range (min)',
};
const pct = (v, d = 2) => v == null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`;
const cls = v => v == null ? '' : v >= 0 ? 'positive' : 'negative';

function Verdict({ s }) {
  if (!s?.trades) return <p className="empty-state">No trades — the signal never fired in this window.</p>;
  const pf = s.profit_factor ?? 0;
  const [icon, text, c] = s.trades < 30
    ? ['⚠️', `Only ${s.trades} trades — too few to trust either way.`, '']
    : pf >= 1.3 && s.avg_net_pct > 0
      ? ['✅', 'Profitable after costs in this window. Check it holds on other tickers and timeframes before relying on it.', 'positive']
      : pf >= 1.0 && s.avg_net_pct > 0
        ? ['🟡', 'Roughly break-even after costs — no reliable edge on its own. Use it as a filter, not a trigger.', '']
        : ['❌', 'Loses money after costs here. Signals alone are not an edge on this ticker/timeframe.', 'negative'];
  return <p className={`bt-verdict ${c}`}>{icon} {text}</p>;
}

export default function StrategyTester({ initialTicker }) {
  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState({
    ticker: initialTicker || 'SPY', timeframe: '5m', strategy: 'ema_cross', side: 'both',
    cost_bps: 3, stop_pct: '', target_pct: '',
  });
  const [params, setParams] = useState({});
  const [result, setResult] = useState(null);
  const [compare, setCompare] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => { fetchBacktestStrategies().then(setMeta).catch(e => setError(e.message)); }, []);
  useEffect(() => { if (meta) setParams({ ...meta.strategies[form.strategy].params }); }, [meta, form.strategy]);

  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));
  const ticker = form.ticker.trim().toUpperCase();

  const run = async (override) => {
    setBusy(true); setError(null); setCompare(null);
    const f = override?.form || form;
    const p = override?.params || params;
    try {
      const opts = { ...f, ticker: f.ticker.trim().toUpperCase() };
      Object.entries(p).forEach(([k, v]) => { opts[`p_${k}`] = v; });
      setResult(await runBacktest(opts));
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const runCompare = async () => {
    setBusy(true); setError(null); setResult(null);
    try { setCompare(await compareBacktests(ticker, form.timeframe, form.cost_bps || 0)); } catch (e) { setError(e.message); }
    setBusy(false);
  };

  const openRow = (row) => {
    const f = { ...form, strategy: row.strategy, side: 'both', stop_pct: '', target_pct: '' };
    const p = { ...row.params };
    setForm(f); setParams(p);
    run({ form: f, params: p });
  };

  if (!meta) return <div className="card">{error ? <p className="error-text">{error}</p> : <p className="loading-text">Loading…</p>}</div>;
  const strat = meta.strategies[form.strategy];
  const s = result?.stats;

  return (
    <>
      <div className="card">
        <h3>🧪 Strategy tester</h3>
        <p className="structures-intro">
          Test a TradingView-style indicator on real bars before risking money. Signals use each bar's close and fill at the
          next bar's open; intraday trades are closed by 4 PM. Costs cover spread and slippage — keep 2–5 bps for liquid
          stocks, 10+ for small caps.
        </p>
        <div className="bt-form">
          <label>Ticker<input className="tool-input" value={form.ticker} maxLength={10} onChange={set('ticker')} /></label>
          <label>Timeframe
            <select className="candle-select" value={form.timeframe} onChange={set('timeframe')}>
              {meta.timeframes.map(t => <option key={t} value={t}>{TF_LABELS[t] || t}</option>)}
            </select>
          </label>
          <label>Strategy
            <select className="candle-select" value={form.strategy} onChange={set('strategy')}>
              {Object.entries(meta.strategies).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
          {Object.keys(params).map(k => (
            <label key={k}>{PARAM_LABELS[k] || k}
              <input className="tool-input bt-num" type="number" step="any" value={params[k]}
                onChange={e => setParams(p => ({ ...p, [k]: e.target.value }))} />
            </label>
          ))}
          <label>Direction
            <select className="candle-select" value={form.side} onChange={set('side')}>
              <option value="both">Long & short</option><option value="long">Long only</option><option value="short">Short only</option>
            </select>
          </label>
          <label>Stop %<input className="tool-input bt-num" type="number" step="0.1" min="0" placeholder="none" value={form.stop_pct} onChange={set('stop_pct')} /></label>
          <label>Target %<input className="tool-input bt-num" type="number" step="0.1" min="0" placeholder="none" value={form.target_pct} onChange={set('target_pct')} /></label>
          <label>Cost (bps)<input className="tool-input bt-num" type="number" step="0.5" min="0" value={form.cost_bps} onChange={set('cost_bps')} /></label>
        </div>
        <p className="market-sub">{strat.help}</p>
        <div className="thesis-actions">
          <button className="btn-primary btn-sm" onClick={() => run()} disabled={busy || !ticker}>{busy ? 'Running…' : '▶ Run backtest'}</button>
          <button className="btn-secondary btn-sm" onClick={runCompare} disabled={busy || !ticker}>Compare all strategies</button>
        </div>
        {error && <p className="error-text">{error}</p>}
      </div>

      {compare && (
        <div className="card">
          <h3>All strategies · {compare.ticker} · {TF_LABELS[compare.timeframe]}</h3>
          <p className="market-sub">{compare.from} → {compare.to} · {compare.sessions} sessions · {compare.cost_bps} bps cost · click a row for details</p>
          <div className="table-scroll">
            <table className="market-table">
              <thead><tr><th>Strategy</th><th>Trades</th><th>Per session</th><th>Win %</th><th>Avg / trade</th><th>Total</th><th>Profit factor</th><th>Max DD</th></tr></thead>
              <tbody>
                {compare.rows.map(r => (
                  <tr key={r.label} onClick={() => openRow(r)}>
                    <td><strong>{r.label}</strong></td>
                    <td>{r.trades}</td><td>{r.per_session ?? '—'}</td><td>{r.win_rate ?? '—'}%</td>
                    <td className={cls(r.avg_net_pct)}>{pct(r.avg_net_pct, 3)}</td>
                    <td className={cls(r.total_net_pct)}>{pct(r.total_net_pct)}</td>
                    <td className={r.profit_factor >= 1 ? 'positive' : 'negative'}>{r.profit_factor ?? '—'}</td>
                    <td className="negative">{pct(r.max_drawdown_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="market-sub">Baseline — {compare.baseline.label}: {pct(compare.baseline.total_pct)} total{compare.baseline.avg_pct != null ? ` (${pct(compare.baseline.avg_pct, 3)} per day)` : ''}</p>
        </div>
      )}

      {result && (
        <div className="card">
          <div className="ivrank-header">
            <h3 style={{ margin: 0 }}>{result.label} · {result.ticker} · {result.timeframe}</h3>
            <span className="market-sub">{result.from} → {result.to} · {result.sessions} sessions</span>
          </div>
          <Verdict s={s} />
          {s?.trades > 0 && (
            <>
              <div className="doctor-stats">
                <div><span>Trades</span><strong>{s.trades} <span className="market-sub">({s.per_session}/session)</span></strong></div>
                <div><span>Win rate</span><strong>{s.win_rate}%</strong></div>
                <div><span>Avg per trade (net)</span><strong className={cls(s.avg_net_pct)}>{pct(s.avg_net_pct, 3)}</strong></div>
                <div><span>Total (sum of trades)</span><strong className={cls(s.total_net_pct)}>{pct(s.total_net_pct)}</strong></div>
                <div><span>Profit factor</span><strong className={s.profit_factor >= 1 ? 'positive' : 'negative'}>{s.profit_factor ?? '—'}</strong></div>
                <div><span>Avg win / loss</span><strong>{pct(s.avg_win_pct, 2)} / {pct(s.avg_loss_pct, 2)}</strong></div>
                <div><span>Max drawdown</span><strong className="negative">{pct(s.max_drawdown_pct)}</strong></div>
                <div><span>Longs / shorts avg</span><strong>{pct(s.long_avg_net_pct, 3)} / {pct(s.short_avg_net_pct, 3)}</strong></div>
              </div>
              <ResponsiveContainer width="100%" height={220}>
                <AreaChart data={result.equity}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="t" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} minTickGap={50} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickFormatter={v => `${v}%`} width={45} />
                  <Tooltip formatter={v => [`${v}%`, 'Cumulative']} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)' }} />
                  <ReferenceLine y={0} stroke="var(--text-muted)" />
                  <Area dataKey="equity" stroke="#7c6cf0" fill="rgba(124,108,240,0.2)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
              <p className="market-sub">Baseline — {result.baseline.label}: {pct(result.baseline.total_pct)} total</p>
              <h4 className="sub-chart-title">Latest trades</h4>
              <div className="table-scroll">
                <table className="market-table">
                  <thead><tr><th>Side</th><th>Entry</th><th>Exit</th><th>Price</th><th>Net</th><th>Exit reason</th></tr></thead>
                  <tbody>
                    {result.recent_trades.map((t, i) => (
                      <tr key={i} className="no-click">
                        <td className={t.side === 'long' ? 'positive' : 'negative'}>{t.side}</td>
                        <td>{t.entry_time}</td><td>{t.exit_time}</td>
                        <td>${t.entry} → ${t.exit}</td>
                        <td className={cls(t.ret_pct)}>{pct(t.ret_pct)}</td>
                        <td className="market-sub">{t.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="ivrank-note">Past results on one ticker and window don't guarantee future performance. Not financial advice.</p>
        </div>
      )}
    </>
  );
}
