import { useState, useEffect } from 'react';
import TabStrip from './TabStrip';
import { ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid } from 'recharts';
import Accounting from './Accounting';
import { Ledger, PremiumIncome } from './OptionsDesk';
import {
  fetchPerformance, fetchDividendIncome, fetchTaxWarnings, importPortfolioCsv, fetchWeeklyReview,
} from '../api/stockApi';

const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', fontSize: '0.8rem' } };
const axis = { tick: { fontSize: 11, fill: 'var(--text-muted)' } };
const usd = v => v == null ? '—' : `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
const pct = v => v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`;
const cls = v => v == null ? '' : v >= 0 ? 'positive' : 'negative';

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

function VsSpy({ version }) {
  const [d, err] = useLoad(fetchPerformance, version);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Comparing your lots with SPY…</p>;
  if (!d.lots) return <p className="empty-state">Add holdings to compare against the S&P 500.</p>;
  return (
    <>
      <div className="doctor-stats">
        <div><span>Your holdings</span><strong className={cls(d.return_pct)}>{pct(d.return_pct)}</strong></div>
        <div><span>Same $ in SPY</span><strong className={cls(d.spy_return_pct)}>{pct(d.spy_return_pct)}</strong></div>
        <div><span>Ahead / behind SPY</span><strong className={cls(d.alpha)}>{usd(d.alpha)}</strong></div>
        <div><span>Realized P/L (closed)</span><strong className={cls(d.realized_pnl)}>{usd(d.realized_pnl)}</strong></div>
      </div>
      {d.series.length > 2 && (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={d.series}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="date" {...axis} minTickGap={40} /><YAxis {...axis} tickFormatter={v => `$${(v / 1000).toFixed(0)}K`} width={55} />
            <Tooltip {...tip} formatter={v => usd(v)} /><Legend />
            <Line dataKey="portfolio" name="Your holdings" stroke="#7c6cf0" dot={false} strokeWidth={2} />
            <Line dataKey="spy" name="Same $ in SPY" stroke="#ffb300" dot={false} strokeWidth={2} />
            <Line dataKey="cost" name="Money invested" stroke="var(--text-muted)" strokeDasharray="4 3" dot={false} />
          </LineChart>
        </ResponsiveContainer>
      )}
      <table className="market-table">
        <thead><tr><th>Stock</th><th>Cost</th><th>Value</th><th>Return</th><th>SPY same dates</th><th>vs SPY</th></tr></thead>
        <tbody>
          {d.by_ticker.map(r => (
            <tr key={r.ticker}>
              <td><strong>{r.ticker}</strong></td><td>{usd(r.cost)}</td><td>{usd(r.value)}</td>
              <td className={cls(r.return_pct)}>{pct(r.return_pct)}</td><td className={cls(r.spy_return_pct)}>{pct(r.spy_return_pct)}</td>
              <td className={cls(r.vs_spy)}><strong>{usd(r.vs_spy)}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="ivrank-note">{d.note}</p>
    </>
  );
}

function DividendIncome({ version }) {
  const [d, err] = useLoad(fetchDividendIncome, version);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Projecting dividend income…</p>;
  if (!d.by_ticker.length) return <p className="empty-state">None of your holdings paid a dividend in the last 12 months.</p>;
  return (
    <>
      <div className="doctor-stats">
        <div><span>Projected annual income</span><strong className="positive">{usd(d.annual_income)}</strong></div>
        <div><span>Monthly average</span><strong>{usd(d.monthly_avg)}</strong></div>
      </div>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={d.calendar}>
          <XAxis dataKey="month" {...axis} /><YAxis {...axis} tickFormatter={v => `$${v}`} width={50} />
          <Tooltip {...tip} formatter={v => [usd(v), 'Est. income']} />
          <Bar dataKey="income" fill="#66bb6a" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <div className="two-column">
        <table className="market-table">
          <thead><tr><th>Stock</th><th>Annual</th><th>Yield</th><th>Yield on cost</th></tr></thead>
          <tbody>
            {d.by_ticker.map(r => (
              <tr key={r.ticker}><td><strong>{r.ticker}</strong></td><td>{usd(r.annual_income)}</td>
                <td>{r.yield_pct != null ? `${r.yield_pct}%` : '—'}</td><td>{r.yield_on_cost_pct != null ? `${r.yield_on_cost_pct}%` : '—'}</td></tr>
            ))}
          </tbody>
        </table>
        <div>
          <h4 className="sub-chart-title">Next expected ex-dates</h4>
          <ul className="smart-list">
            {d.upcoming.map((p, i) => <li key={i}><strong>{p.ticker}</strong> ~{p.est_ex_date} · {usd(p.amount)}</li>)}
          </ul>
        </div>
      </div>
      <p className="ivrank-note">{d.note}</p>
    </>
  );
}

function TaxCheck({ version }) {
  const [d, err] = useLoad(fetchTaxWarnings, version);
  if (err) return <p className="error-text">{err}</p>;
  if (!d) return <p className="loading-text">Checking for wash sales…</p>;
  return (
    <>
      {d.warnings.length === 0 ? <p className="empty-state">✅ No wash-sale issues found in your recorded trades.</p> : (
        <ul className="tax-list">
          {d.warnings.map((w, i) => (
            <li key={i} className={`tax-${w.level}`}>
              <strong>{w.level === 'high' ? '⛔' : w.level === 'medium' ? '⚠️' : 'ℹ️'} {w.ticker}</strong> {w.text}
            </li>
          ))}
        </ul>
      )}
      {d.lots?.length > 0 && (
        <>
          <h4 className="sub-chart-title">Holding period by lot</h4>
          <table className="market-table">
            <thead><tr><th>Stock</th><th>Bought</th><th>Term</th><th>Unrealized</th><th>Note</th></tr></thead>
            <tbody>
              {d.lots.map((l, i) => (
                <tr key={i}>
                  <td><strong>{l.ticker}</strong> <span className="market-sub">{l.shares} sh</span></td>
                  <td>{l.acquired} <span className="market-sub">({l.days_held}d)</span></td>
                  <td>{l.term === 'long' ? 'Long-term' : <>Short-term<div className="market-sub">long-term on {l.long_term_on}</div></>}</td>
                  <td className={cls(l.gain)}>{usd(l.gain)}</td>
                  <td className={l.note ? 'rvol-warm' : ''}>{l.note || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <p className="ivrank-note">{d.note}</p>
    </>
  );
}

function WeeklyReview() {
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState(null);
  const load = (refresh) => {
    setLoading(true); setErr(null);
    fetchWeeklyReview(refresh).then(setD).catch(e => setErr(e.message)).finally(() => setLoading(false));
  };
  useEffect(() => { load(false); }, []);
  return (
    <>
      <div className="ivrank-header">
        <span className="market-sub">Sent to your notifications (and phone, if set up) every weekend.</span>
        <button className="btn-secondary btn-sm" onClick={() => load(true)} disabled={loading}>{loading ? 'Writing…' : '↻ Regenerate'}</button>
      </div>
      {err && <p className="error-text">{err}</p>}
      {d?.empty && <p className="empty-state">Add holdings or watchlist stocks to get a weekly review.</p>}
      {d?.body && <><h4 className="sub-chart-title">{d.title}</h4><p className="briefing-body">{d.body}</p></>}
    </>
  );
}

export function ImportCsv({ onImported, account = '' }) {
  const [text, setText] = useState('');
  const [kind, setKind] = useState('positions');
  const [preview, setPreview] = useState(null);
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);
  const [source, setSource] = useState('');
  const [mode, setMode] = useState('append');
  const syncing = mode === 'sync' && kind !== 'history';

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (f.size > 1_000_000) { setMsg('File is larger than 1 MB.'); return; }
    setText(await f.text());
    setPreview(null); setMsg(null); setSource('');
  };
  const run = async (commit, sourceAccount = source) => {
    setBusy(true); setMsg(null);
    try {
      const r = await importPortfolioCsv(text, commit, kind, account, sourceAccount, syncing ? 'sync' : 'append');
      setPreview(r);
      if (commit) {
        const failed = r.result?.failed || [];
        setMsg(kind === 'history'
          ? `Imported ${r.result.imported} closed trade(s); ${r.result.duplicates} already recorded${failed.length ? `; ${failed.length} rejected: ${failed.map(f => `${f.symbol} (${f.reason})`).join('; ')}` : ''}.`
          : r.sync
            ? `Synced ${account || 'Default'}: ${r.sync.kept} unchanged, ${r.sync.removed_records} record(s) removed, ${r.sync.added_records} added${r.cash ? `; cash set to ${usd(r.cash.cash)}` : ''}.`
            : `Imported ${r.imported} position(s)${r.cash ? `; added ${usd(r.money_market_total)} of money-market funds to ${r.cash.account} cash (now ${usd(r.cash.cash)})` : ''}.`);
        setText(''); onImported?.();
      }
    } catch (e) { setMsg(e.message); }
    setBusy(false);
  };
  const describe = (r) => r.kind === 'option'
    ? `${r.position} ${r.contracts} × $${r.strike} ${r.option_type} ${r.expiry}` : `${r.shares} shares`;
  const pick = (k) => { setKind(k); setPreview(null); setSource(''); };

  return (
    <>
      <div className="chart-toggle import-kind" role="group" aria-label="Import type">
        <button className={kind === 'positions' ? 'active' : ''} onClick={() => pick('positions')}>Open positions</button>
        <button className={kind === 'activity' ? 'active' : ''} onClick={() => pick('activity')}>Transaction history</button>
        <button className={kind === 'history' ? 'active' : ''} onClick={() => pick('history')}>Closed trade history</button>
      </div>
      <p className="structures-intro">
        {kind === 'positions'
          ? <>Export <b>positions</b> as CSV from Fidelity, Schwab, E*TRADE, Vanguard or any broker (Symbol, Quantity and a cost-basis column). Stocks/ETFs become lots; option symbols (OCC, Fidelity, Schwab or E*TRADE style) become option positions, with negative quantities recorded as short. Money-market funds are added to cash; expired options are skipped. Robinhood and Webull don't export positions: use Transaction history.</>
          : kind === 'activity'
            ? <>For <b>Robinhood</b> (Reports → Account activity CSV), <b>Webull</b> (Orders → export filled orders; stock and option files separately) or Fidelity/Schwab transaction history. Buys and sells are replayed oldest first into lots with their real purchase dates; option opens, closes, expirations and assignments net into open contracts. The file must reach back to when each position was opened.</>
            : <>Export <b>realized gain/loss</b> (closed lots) as CSV (Quantity, Date acquired, Date sold, Proceeds, Cost basis). Closed options are recorded through the audited history path and closed stock lots as sold trades. Re-importing the same rows adds nothing.</>}
        {' '}Rows go into <b>{account || 'Default'}</b>. The file is parsed on the server and not stored.
      </p>
      {kind !== 'history' && <div className="chart-toggle import-kind" role="group" aria-label="Import mode">
        <button className={mode === 'append' ? 'active' : ''} aria-pressed={mode === 'append'} onClick={() => { setMode('append'); setPreview(null); }}>Add to recorded positions</button>
        <button className={mode === 'sync' ? 'active' : ''} aria-pressed={mode === 'sync'} onClick={() => { setMode('sync'); setPreview(null); }}>Sync account to this file</button>
      </div>}
      {syncing && <p className="market-sub">Sync makes <b>{account || 'Default'}</b> match the file: matching tickers and contracts are left alone (keeping your lot dates),
        changed ones are replaced with the file&apos;s lots, and positions not in the file are <b>removed without recording a sale</b>. Record real sales first if you want their realized P&amp;L.
        Money-market funds set the cash balance instead of adding to it. Other accounts are not touched.</p>}
      <div className="alert-form">
        <input type="file" accept=".csv,text/csv" aria-label="Broker CSV file" onChange={onFile} />
        <button className="btn-secondary btn-sm" disabled={!text || busy} onClick={() => run(false)}>Preview</button>
        <button className="btn-primary btn-sm" disabled={busy || !(syncing ? (preview?.reconcile?.changes || preview?.money_market?.length) : (preview?.rows?.length || preview?.money_market?.length))} onClick={() => run(true)}>
          {syncing ? `Apply ${preview?.reconcile?.changes ?? ''} change(s)` : `Import ${preview?.rows?.length || ''} rows`}
        </button>
      </div>
      {msg && <p className="notif-msg">{msg}</p>}
      {preview && (
        <>
          {preview.source_accounts?.length > 1 && (
            <label className="market-sub">This file has {preview.source_accounts.length} broker accounts. Import{' '}
              <select className="tool-input" aria-label="Broker account in file" value={source} disabled={busy}
                onChange={e => { setSource(e.target.value); run(false, e.target.value); }}>
                <option value="">all of them</option>
                {preview.source_accounts.map(a => <option key={a} value={a}>{a}</option>)}
              </select>
            </label>
          )}
          {kind === 'activity' && <p className="market-sub">{preview.trades} trade(s){preview.first_date ? ` from ${preview.first_date} to ${preview.last_date}` : ''} rebuild {preview.rows.length} open position(s).
            {Object.keys(preview.ignored || {}).length > 0 && ` Not trades (ignored): ${Object.entries(preview.ignored).map(([k, n]) => `${k} ×${n}`).join(', ')}.`}</p>}
          <p className="market-sub">Detected columns: {Object.entries(preview.columns).map(([k, v]) => `${k} = "${v}"`).join(', ')}</p>
          {syncing && preview.reconcile && <>
            <p className="market-sub">{preview.reconcile.changes ? `${preview.reconcile.changes} difference(s)` : 'Already in sync: nothing to change'}
              {preview.reconcile.counts.match ? ` · ${preview.reconcile.counts.match} matching` : ''}</p>
            <div className="table-scroll"><table className="market-table" aria-label="Differences">
              <thead><tr><th>Position</th><th>Recorded</th><th>In file</th><th>Result</th></tr></thead>
              <tbody>{[...preview.reconcile.stocks.map(s => ({ ...s, label: s.ticker, unit: 'sh' })), ...preview.reconcile.options.map(o => ({ ...o, unit: 'ct' }))]
                .filter(item => item.status !== 'match').map(item => <tr key={item.label} className="no-click">
                  <td>{item.label}</td><td>{item.recorded ? `${item.recorded} ${item.unit}` : '—'}</td><td>{item.file ? `${item.file} ${item.unit}` : '—'}</td>
                  <td className={item.status === 'missing' ? 'negative' : item.status === 'new' ? 'positive' : ''}>
                    {{ new: 'Add', missing: 'Remove', changed: 'Replace lots' }[item.status]}</td></tr>)}</tbody>
            </table></div>
          </>}
          {!syncing && <div className="table-scroll"><table className="market-table">
            {kind !== 'history' ? <>
              <thead><tr><th>Ticker</th><th>Position</th><th>Cost / share</th><th>Acquired</th></tr></thead>
              <tbody>{preview.rows.map((r, i) => <tr key={i}><td>{r.ticker}</td><td>{describe(r)}</td><td>${r.kind === 'option' ? r.premium : r.price}</td><td>{r.kind === 'option' ? '—' : r.acquired || 'today'}</td></tr>)}</tbody>
            </> : <>
              <thead><tr><th>Ticker</th><th>Trade</th><th>Open</th><th>Close</th><th>Opened</th><th>Closed</th></tr></thead>
              <tbody>{preview.rows.map((r, i) => <tr key={i}><td>{r.ticker}</td><td>{describe(r)}</td>
                <td>${r.kind === 'option' ? r.open_premium : r.buy_price}</td><td>${r.kind === 'option' ? r.close_premium : r.sell_price}</td>
                <td>{r.opened_at || r.acquired || '—'}</td><td>{r.closed_at}</td></tr>)}</tbody>
            </>}
          </table></div>}
          {preview.money_market?.length > 0 && (
            <p className="market-sub">Money-market funds are counted as cash, not stock: {preview.money_market.map(m => `${m.ticker} ${usd(m.amount)}`).join(', ')}.
              {' '}{syncing ? 'Syncing sets' : 'Importing adds'} {usd(preview.money_market_total)} {syncing ? 'as' : 'to'} the <b>{account || 'Default'}</b> cash balance.</p>
          )}
          {preview.skipped.length > 0 && (
            <p className="market-sub">Skipped: {preview.skipped.map(s => `${s.symbol} (${s.reason})`).join('; ')}</p>
          )}
        </>
      )}
    </>
  );
}

const TABS = [['combined', 'Combined P&L'], ['accounting', 'Account ledger'], ['income', 'Premium cash flow'], ['spy', 'vs S&P 500'], ['divs', 'Dividends'], ['tax', 'Tax'], ['weekly', 'Weekly review']];

export default function PortfolioInsights({ tickers, version, onImported, initialTab }) {
  const [tab, setTab] = useState(initialTab || 'combined');
  return (
    <div className="card portfolio-insights">
      <TabStrip label="Income and performance views" activeKey={tab}>
        {TABS.map(([id, label]) => (
          <button key={id} className={`sub-tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>{label}</button>
        ))}
      </TabStrip>
      {tab === 'combined' && <Ledger version={version} />}
      {tab === 'accounting' && <Accounting version={version} />}
      {tab === 'income' && <PremiumIncome version={version} />}
      {tab === 'spy' && <VsSpy version={version} />}
      {tab === 'divs' && <DividendIncome version={version} />}
      {tab === 'tax' && <TaxCheck version={version} />}
      {tab === 'weekly' && <WeeklyReview />}
      {tab === 'import' && <ImportCsv onImported={onImported} />}
    </div>
  );
}
