import { useState, useEffect, useMemo } from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ReferenceLine, ComposedChart, Bar } from 'recharts';
import {
  fetchOptionActions, fetchPortfolioEarnings, fetchWheelLedger, fetchOptionsReview, fetchOptionsCoach,
  fetchPremiumIncome, saveIncomeGoal,
} from '../api/stockApi';

const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const cls = v => v == null ? '' : v >= 0 ? 'positive' : 'negative';
const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
const ICON = { act: '✅', warn: '⚠️', info: 'ℹ️' };
const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', fontSize: '0.8rem' } };
const axis = { tick: { fontSize: 11, fill: 'var(--text-muted)' } };

function useLoad(fn, dep) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setData(null); setError(null);
    fn().then(setData).catch(e => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dep]);
  return [data, error];
}

function Today({ version, onRepair, onAssign }) {
  const [d, err] = useLoad(fetchOptionActions, version);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Checking your option positions…</p>;
  if (!d.positions.length) return <p className="empty-state">No open option positions.</p>;
  const busy = d.positions.filter(p => p.actions.length);
  return (
    <>
      <p className="structures-intro">
        Daily rules: take profit at {d.rules.take_profit_pct}% of max, act when a short strike's delta passes {d.rules.tested_delta},
        avoid the last {d.rules.gamma_days} days, and watch earnings and ex-dividend dates. Must-act items are also pushed to
        your notifications each morning.
      </p>
      {busy.length === 0 && <p className="empty-state">✅ Nothing needs attention today.</p>}
      {busy.map(p => (
        <div key={p.id} className="desk-item">
          <div className="desk-head">
            <strong>{p.ticker}</strong> {p.position} ${p.strike} {p.type} · {fmtDate(p.expiry)} ({p.dte}d)
            <span className="market-sub">
              {' '}· stock ${p.spot}{p.mid != null && ` · mark $${p.mid}`}{p.delta != null && ` · Δ ${p.delta}`}
              {p.profit_captured_pct > 0 && ` · ${p.profit_captured_pct}% of max profit`}
            </span>
            {p.pnl != null && <strong className={`desk-pnl ${cls(p.pnl)}`}>{usd(p.pnl)}</strong>}
          </div>
          <ul className="idea-checks">
            {p.actions.map((a, i) => (
              <li key={i} className={`desk-${a.level}`}>
                {ICON[a.level]} {a.text}
                {a.repair && <> <button className="link-btn" onClick={() => onRepair(p.id)}>🔧 Repair</button></>}
                {a.assign && <> <button className="link-btn" onClick={() => onAssign(p.id)}>📥 Mark assigned</button></>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {d.positions.length > busy.length && (
        <p className="market-sub">{d.positions.length - busy.length} other position{d.positions.length - busy.length > 1 ? 's' : ''} on track.</p>
      )}
    </>
  );
}

function Earnings({ version }) {
  const [d, err] = useLoad(fetchPortfolioEarnings, version);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Checking earnings dates…</p>;
  return (
    <>
      {d.upcoming.length === 0 ? <p className="empty-state">No holdings or options report in the next 30 days.</p> : (
        <table className="market-table">
          <thead><tr><th>Stock</th><th>Reports</th><th>Typical move</th><th>Your exposure</th></tr></thead>
          <tbody>
            {d.upcoming.map(r => (
              <tr key={r.ticker}>
                <td><strong>{r.ticker}</strong></td>
                <td>
                  {fmtDate(r.date)}{!r.confirmed && ' (est.)'} <span className="market-sub">in {r.days}d{r.timing ? `, ${r.timing}` : ''}</span>
                  {r.alt && <div className="market-sub">other source: {fmtDate(r.alt)}</div>}
                </td>
                <td>{r.avg_move_pct != null ? `±${r.avg_move_pct}%` : '—'}</td>
                <td>
                  {r.shares > 0 && <div>{r.shares} shares{r.dollar_move ? ` ≈ ±${usd(r.dollar_move)}` : ''}</div>}
                  {r.options.map(o => (
                    <div key={o.id} className={o.position === 'short' ? 'rvol-warm' : ''}>
                      {o.position} ${o.strike} {o.type} {fmtDate(o.expiry)} ×{o.contracts}{o.position === 'short' ? ' — spans the report' : ''}
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {d.recent.length > 0 && (
        <>
          <h4 className="sub-chart-title">Just reported</h4>
          <ul className="idea-checks">
            {d.recent.map(r => (
              <li key={r.ticker} className="positive">
                ✓ <strong>{r.ticker}</strong> reported {fmtDate(r.date)}{r.timing ? ` ${r.timing}` : ''} ({r.days_ago === 0 ? 'today' : `${r.days_ago}d ago`})
                — the earnings volatility drop is behind it, often a calmer window to sell premium.
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="ivrank-note">Typical move = average close-to-close reaction over the last ~12 reports.</p>
    </>
  );
}

// ── What-if: Black-Scholes repricing of every position ──
function ncdf(x) {
  const t = 1 / (1 + 0.2316419 * Math.abs(x));
  const d = 0.3989423 * Math.exp(-x * x / 2);
  const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
  return x > 0 ? 1 - p : p;
}
function bs(S, K, T, sigma, kind) {
  if (T <= 0 || sigma <= 0) return Math.max(kind === 'call' ? S - K : K - S, 0);
  const d1 = (Math.log(S / K) + (0.04 + sigma * sigma / 2) * T) / (sigma * Math.sqrt(T));
  const d2 = d1 - sigma * Math.sqrt(T);
  return kind === 'call' ? S * ncdf(d1) - K * Math.exp(-0.04 * T) * ncdf(d2)
    : K * Math.exp(-0.04 * T) * ncdf(-d2) - S * ncdf(-d1);
}
function pnlAt(options, holdings, move, ivChg, days, withStocks) {
  let total = 0;
  const rows = options.map(o => {
    const S = o.current_price * (1 + move / 100);
    const sigma = (o.iv || 30) / 100;
    const iv = Math.max(sigma * (1 + ivChg / 100), 0.01);
    const T0 = Math.max(o.dte, 0) / 365;
    const T = Math.max(o.dte - days, 0) / 365;
    // Anchor the model to today's market mark; the gap fades out by expiry
    const gap = o.quoted !== false && T0 > 0 ? o.market_price - bs(o.current_price, o.strike, T0, sigma, o.type) : 0;
    const v = Math.max(bs(S, o.strike, T, iv, o.type) + gap * (T0 > 0 ? T / T0 : 0), 0);
    const pnl = ((o.position === 'short' ? o.premium - v : v - o.premium) * 100 * o.contracts);
    total += pnl;
    return { key: `o${o.id}`, label: `${o.ticker} ${o.position} $${o.strike} ${o.type}`, pnl };
  });
  if (withStocks) {
    for (const h of holdings) {
      const pnl = h.shares * (h.current_price * (1 + move / 100) - h.buy_price);
      total += pnl;
      rows.push({ key: `h${h.id}`, label: `${h.ticker} ${h.shares} shares`, pnl });
    }
  }
  return { total, rows };
}

function WhatIf({ options, holdings }) {
  const maxDte = Math.max(0, ...options.map(o => o.dte));
  const [move, setMove] = useState(0);
  const [ivChg, setIvChg] = useState(0);
  const [days, setDays] = useState(0);
  const [withStocks, setWithStocks] = useState(true);
  const now = useMemo(() => pnlAt(options, holdings, 0, 0, 0, withStocks).total, [options, holdings, withStocks]);
  const res = useMemo(() => pnlAt(options, holdings, move, ivChg, days, withStocks), [options, holdings, move, ivChg, days, withStocks]);
  const curve = useMemo(() => Array.from({ length: 41 }, (_, i) => {
    const m = -20 + i;
    return { move: m, scenario: Math.round(pnlAt(options, holdings, m, ivChg, days, withStocks).total),
      expiry: Math.round(pnlAt(options, holdings, m, 0, maxDte, withStocks).total) };
  }), [options, holdings, ivChg, days, withStocks, maxDte]);
  if (!options.length && !holdings.length) return <p className="empty-state">Add positions to run scenarios.</p>;
  return (
    <>
      <div className="whatif-controls">
        <label>Stocks move <strong>{move > 0 ? '+' : ''}{move}%</strong>
          <input type="range" min={-30} max={30} value={move} onChange={e => setMove(+e.target.value)} /></label>
        <label>Implied volatility <strong>{ivChg > 0 ? '+' : ''}{ivChg}%</strong>
          <input type="range" min={-60} max={100} step={5} value={ivChg} onChange={e => setIvChg(+e.target.value)} /></label>
        <label>Days pass <strong>{days}</strong>
          <input type="range" min={0} max={Math.max(maxDte, 1)} value={days} onChange={e => setDays(+e.target.value)} /></label>
        <label className="whatif-check"><input type="checkbox" checked={withStocks} onChange={e => setWithStocks(e.target.checked)} /> Include shares</label>
      </div>
      <div className="doctor-stats">
        <div><span>P&L now</span><strong className={cls(now)}>{usd(now)}</strong></div>
        <div><span>P&L in this scenario</span><strong className={cls(res.total)}>{usd(res.total)}</strong></div>
        <div><span>Change</span><strong className={cls(res.total - now)}>{usd(res.total - now)}</strong></div>
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={curve}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="move" {...axis} tickFormatter={v => `${v}%`} />
          <YAxis {...axis} width={60} tickFormatter={v => usd(v)} />
          <Tooltip {...tip} formatter={v => usd(v)} labelFormatter={v => `Stocks ${v > 0 ? '+' : ''}${v}%`} />
          <Legend />
          <ReferenceLine y={0} stroke="var(--text-muted)" />
          <ReferenceLine x={move} stroke="#7c6cf0" strokeDasharray="4 3" />
          <Line dataKey="scenario" name={`After ${days}d${ivChg ? `, IV ${ivChg > 0 ? '+' : ''}${ivChg}%` : ''}`} stroke="#7c6cf0" dot={false} strokeWidth={2} />
          <Line dataKey="expiry" name="At last expiry" stroke="#ffb300" dot={false} strokeDasharray="5 3" />
        </LineChart>
      </ResponsiveContainer>
      <table className="market-table">
        <thead><tr><th>Position</th><th>Scenario P&L</th></tr></thead>
        <tbody>{res.rows.map(r => <tr key={r.key}><td>{r.label}</td><td className={cls(r.pnl)}>{usd(r.pnl)}</td></tr>)}</tbody>
      </table>
      <p className="ivrank-note">
        Every stock gets the same % move. Options are repriced with Black-Scholes from their current implied volatility
        (30% if unquoted); options already past their expiry in the scenario are worth intrinsic value.
      </p>
    </>
  );
}

function Ledger({ version }) {
  const [d, err] = useLoad(fetchWheelLedger, version);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Adding up your wheel…</p>;
  if (!d.rows.length) return <p className="empty-state">No short options recorded yet — sell a put or covered call to start a wheel.</p>;
  return (
    <>
      <div className="doctor-stats"><div><span>Total wheel P&L</span><strong className={cls(d.total_pnl)}>{usd(d.total_pnl)}</strong></div></div>
      <table className="market-table">
        <thead><tr><th>Stock</th><th>Since</th><th>Premium</th><th>Shares · cost</th><th>Total P&L</th><th>Return</th><th>Buy &amp; hold</th></tr></thead>
        <tbody>
          {d.rows.map(r => (
            <tr key={r.ticker}>
              <td><strong>{r.ticker}</strong><div className="market-sub">{r.cycles} trade{r.cycles !== 1 ? 's' : ''}{r.open_shorts ? `, ${r.open_shorts} open` : ''}</div></td>
              <td>{fmtDate(r.since)}</td>
              <td className="positive">{usd(r.premium_kept + r.open_premium)}{r.open_premium > 0 && <div className="market-sub">{usd(r.open_premium)} open</div>}</td>
              <td>{r.shares ? <>{r.shares} @ ${r.avg_cost}<div className="market-sub">adjusted ${r.adjusted_cost}</div></> : '—'}</td>
              <td className={cls(r.total_pnl)}><strong>{usd(r.total_pnl)}</strong></td>
              <td className={cls(r.return_pct)}>{r.return_pct != null ? `${r.return_pct}%` : '—'}{r.annualized_pct != null && <div className="market-sub">{r.annualized_pct}%/yr</div>}</td>
              <td className={cls(r.buy_hold_pct)}>{r.buy_hold_pct != null ? `${r.buy_hold_pct}%` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="ivrank-note">{d.note} Adjusted cost = share cost minus all premium collected on the stock.</p>
    </>
  );
}

function Breakdown({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div>
      <h4 className="sub-chart-title">{title}</h4>
      <table className="market-table">
        <thead><tr><th></th><th>Trades</th><th>Win rate</th><th>P&L</th></tr></thead>
        <tbody>{rows.map(r => <tr key={r.key}><td>{r.key}</td><td>{r.trades}</td><td>{r.win_rate}%</td><td className={cls(r.pnl)}>{usd(r.pnl)}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function Review({ version }) {
  const [d, err] = useLoad(fetchOptionsReview, version);
  const [ai, setAi] = useState(null);
  const [busy, setBusy] = useState(false);
  const [aiErr, setAiErr] = useState(null);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Reviewing closed options…</p>;
  if (!d.stats) return <p className="empty-state">Close some option trades to see what's working.</p>;
  const s = d.stats;
  const coach = () => { setBusy(true); setAiErr(null); fetchOptionsCoach().then(setAi).catch(e => setAiErr(e.message)).finally(() => setBusy(false)); };
  return (
    <>
      <div className="doctor-stats">
        <div><span>Closed trades</span><strong>{s.trades}</strong></div>
        <div><span>Win rate</span><strong>{s.win_rate}%</strong></div>
        <div><span>Total P&L</span><strong className={cls(s.total_pnl)}>{usd(s.total_pnl)}</strong></div>
        <div><span>Avg win / loss</span><strong>{usd(s.avg_win)} / {usd(s.avg_loss)}</strong></div>
        <div><span>Profit factor</span><strong>{s.profit_factor ?? '—'}</strong></div>
      </div>
      <div className="two-column">
        <Breakdown title="By strategy" rows={d.breakdowns.strategy} />
        <Breakdown title="By days to expiry when opened" rows={d.breakdowns.dte_at_open} />
        <Breakdown title="Held to expiry vs closed early" rows={d.breakdowns.exit} />
        <Breakdown title="By stock" rows={d.breakdowns.ticker} />
      </div>
      <button className="btn-secondary btn-sm" onClick={coach} disabled={busy}>{busy ? 'Reviewing…' : '🧠 AI review of my option trades'}</button>
      {aiErr && <p className="error-text">{aiErr}</p>}
      {ai && (
        <div className="coach-box">
          <p>{ai.summary}</p>
          {ai.strengths.length > 0 && <><h4 className="sub-chart-title">Working</h4><ul className="idea-checks">{ai.strengths.map((x, i) => <li key={i} className="positive">✓ {x}</li>)}</ul></>}
          {ai.leaks.length > 0 && <><h4 className="sub-chart-title">Costing you</h4><ul className="idea-checks">{ai.leaks.map((x, i) => <li key={i} className="rvol-warm">⚠ {x}</li>)}</ul></>}
          {ai.rules.length > 0 && <><h4 className="sub-chart-title">Rules to adopt</h4><ul className="idea-checks">{ai.rules.map((x, i) => <li key={i}>→ {x}</li>)}</ul></>}
        </div>
      )}
    </>
  );
}

function PremiumIncome({ version }) {
  const [d, err] = useLoad(fetchPremiumIncome, version);
  const [goal, setGoal] = useState('');
  const [saved, setSaved] = useState(null);
  useEffect(() => { if (d) { setGoal(d.goal ?? ''); setSaved(d.goal); } }, [d]);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Adding up premium…</p>;
  const save = () => saveIncomeGoal(goal === '' ? null : Number(goal)).then(r => setSaved(r.goal)).catch(() => {});
  const t = d.this_month;
  const pct = saved ? Math.round(t.net / saved * 100) : null;
  const label = m => new Date(m + '-15').toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
  return (
    <>
      <div className="doctor-stats">
        <div><span>This month (net)</span><strong className={cls(t.net)}>{usd(t.net)}</strong></div>
        <div><span>Realized this month</span><strong className={cls(t.realized)}>{usd(t.realized)}</strong></div>
        <div><span>Year to date (net)</span><strong className={cls(d.ytd_net)}>{usd(d.ytd_net)}</strong></div>
        <div><span>Avg last 3 months</span><strong className={cls(d.avg_net_3m)}>{usd(d.avg_net_3m)}</strong></div>
      </div>
      <div className="income-goal">
        <label>Monthly goal ($)
          <input type="number" className="tool-input" min={0} step={100} value={goal} placeholder="e.g. 1000"
            onChange={e => setGoal(e.target.value)} />
        </label>
        <button className="btn-secondary btn-sm" onClick={save} disabled={String(goal) === String(saved ?? '')}>Save</button>
        {saved > 0 && (
          <div className="goal-progress">
            <div className="goal-track"><div className={`goal-fill ${pct >= 100 ? 'goal-done' : ''}`} style={{ width: `${Math.min(Math.max(pct, 0), 100)}%` }} /></div>
            <span>{usd(t.net)} of {usd(saved)} this month ({pct}%){pct >= 100 ? ' 🎉' : ''}</span>
          </div>
        )}
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={d.months.map(r => ({ ...r, label: label(r.month), paid: -r.paid }))}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="label" {...axis} />
          <YAxis {...axis} width={60} tickFormatter={v => usd(v)} />
          <Tooltip {...tip} formatter={(v, n) => [usd(n === 'Paid back' ? -v : v), n]} />
          <Legend />
          <ReferenceLine y={0} stroke="var(--text-muted)" />
          {saved > 0 && <ReferenceLine y={saved} stroke="#ffb300" strokeDasharray="5 3" label={{ value: 'Goal', fill: '#ffb300', fontSize: 11 }} />}
          <Bar dataKey="collected" name="Collected" fill="#66bb6a" radius={[3, 3, 0, 0]} />
          <Bar dataKey="paid" name="Paid back" fill="#ef5350" radius={[0, 0, 3, 3]} />
          <Line dataKey="net" name="Net" stroke="#7c6cf0" strokeWidth={2} dot />
          <Line dataKey="realized" name="Realized P&L" stroke="var(--text-muted)" strokeDasharray="4 3" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <p className="ivrank-note">{d.note}</p>
    </>
  );
}

const TABS = [['today', '🛠 Today'], ['income', '💵 Premium income'], ['earnings', '📅 Earnings ahead'], ['whatif', '🎚 What-if'],
  ['ledger', '🎡 Wheel ledger'], ['review', '🧠 Options review']];

export default function OptionsDesk({ options, holdings, closedCount, onRepair, onAssign }) {
  const [tab, setTab] = useState(options.length ? 'today' : 'earnings');
  const version = options.map(o => `${o.id}:${o.contracts}`).join(',') + `|${holdings.length}|${closedCount}`;
  return (
    <div className="card portfolio-insights">
      <nav className="sub-tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={`sub-tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>
      {tab === 'today' && <Today version={version} onRepair={onRepair} onAssign={onAssign} />}
      {tab === 'income' && <PremiumIncome version={version} />}
      {tab === 'earnings' && <Earnings version={version} />}
      {tab === 'whatif' && <WhatIf options={options} holdings={holdings} />}
      {tab === 'ledger' && <Ledger version={version} />}
      {tab === 'review' && <Review version={version} />}
    </div>
  );
}
