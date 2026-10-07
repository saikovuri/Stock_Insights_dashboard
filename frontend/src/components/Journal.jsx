import { useState, useEffect, useCallback, useRef } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts';
import { useAuth } from '../AuthContext';
import PreTradeChecklist from './PreTradeChecklist';
import PositionCalculator from './PositionCalculator';
import { Review } from './OptionsDesk';
import WheelCycles from './WheelCycles';
import AccountTransfer from './AccountTransfer';
import Skeleton from './Skeleton';
import TabStrip from './TabStrip';
import PnlCalendar from './PnlCalendar';
import {
  fetchJournal, addJournalEntry, updateJournalEntry, deleteJournalEntry, fetchJournalCoach, fetchClosedTrades, fetchClosedOptions, logClosedOption, updateClosedOption, deleteClosedOption,
  recordAccountingEntry,
} from '../api/stockApi';

const SETUP_TAGS = ['Breakout', 'Pullback', 'Gap and go', 'Opening range', 'Reversal', 'Earnings', 'Trend follow', 'Squeeze', 'Long-term buy'];
const today = () => new Date().toISOString().slice(0, 10);
const EMPTY = { ticker: '', side: 'long', shares: '', entry_date: today(), entry_price: '', stop: '', target: '', setup: '', notes: '', exit_date: '', exit_price: '' };

function money(v) {
  if (v == null) return '—';
  return `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

const finiteNumber = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));
const percent = value => value == null ? 'Unavailable' : `${value.toFixed(1)}%`;
const pnlClass = value => value > 0 ? 'positive' : value < 0 ? 'negative' : '';
const EXIT_REASONS = { profit_target: 'Profit target', stop: 'Stop / risk limit', expiry: 'Expiry', assignment: 'Assignment',
  roll: 'Roll', discretionary: 'Discretionary exit', other: 'Other' };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const PAGE = 25;

function shortDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value ?? '').slice(0, 10));
  if (!match) return null;
  const label = `${MONTHS[Number(match[2]) - 1]} ${Number(match[3])}`;
  return match[1] === String(new Date().getFullYear()) ? label : `${label}, ${match[1]}`;
}

const Missing = ({ reason }) => <span className="muted-dash" title={reason}>—<span className="sr-only">{reason}</span></span>;
const barWidth = value => `${Math.max(0, Math.min(100, value))}%`;
const price = value => `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;

function calendarDays(start, end) {
  const parse = value => {
    const text = String(value ?? '').slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
    const timestamp = Date.parse(`${text}T00:00:00Z`);
    return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === text ? timestamp : null;
  };
  const first = parse(start), last = parse(end);
  return first == null || last == null || last < first ? null : (last - first) / 86400000;
}

export function recordedTradeMetrics(trade) {
  const option = ['short', 'long'].includes(trade.position) && ['put', 'call'].includes(trade.option_type);
  const validPremiums = option && finiteNumber(trade.open_premium) && Number(trade.open_premium) > 0
    && finiteNumber(trade.close_premium) && Number(trade.close_premium) >= 0;
  const capture = validPremiums ? (Number(trade.close_premium) - Number(trade.open_premium))
    / Number(trade.open_premium) * 100 * (trade.position === 'short' ? -1 : 1) : null;
  const target = option && trade.position === 'short' && finiteNumber(trade.review?.target_capture_pct)
    ? Number(trade.review.target_capture_pct) : null;
  return { option, capture, label: trade.position === 'short' ? 'Captured' : 'Return',
    target, targetGap: target == null || capture == null ? null : capture - target,
    daysHeld: calendarDays(trade.opened_at || trade.acquired_at, trade.closed_at),
    dteAtClose: option ? calendarDays(trade.closed_at, trade.expiry) : null };
}

export function recordedOptionStats(rows) {
  const values = rows.filter(row => recordedTradeMetrics(row).option && finiteNumber(row.net_pnl)).map(row => Number(row.net_pnl));
  const wins = values.filter(value => value > 0);
  const losses = values.filter(value => value < 0);
  const gain = wins.reduce((sum, value) => sum + value, 0);
  const loss = -losses.reduce((sum, value) => sum + value, 0);
  return { count: values.length, net: values.reduce((sum, value) => sum + value, 0),
    expectancy: values.length ? (gain - loss) / values.length : null,
    winRate: values.length ? wins.length / values.length * 100 : null,
    profitFactor: loss ? (gain / loss).toFixed(2) : values.length ? 'No losses' : 'Unavailable' };
}

const bucket = (value, edges) => value == null ? 'Unknown' : edges.find(([limit]) => value <= limit)?.[1] ?? edges.at(-1)[1];
const DTE_BUCKETS = [[7, '0-7 days'], [21, '8-21 days'], [45, '22-45 days'], [90, '46-90 days'], [Infinity, '91+ days']];
const HELD_BUCKETS = [[3, '0-3 days'], [14, '4-14 days'], [30, '15-30 days'], [Infinity, '31+ days']];
const CLOSE_ORDER = ['Held to expiry', 'Closed early, 50%+ captured', 'Closed early, under 50% captured', 'Closed early at a loss', 'Closed before expiry', 'Unknown'];

export function howClosed(row) {
  const metrics = recordedTradeMetrics(row);
  if (metrics.dteAtClose == null) return 'Unknown';
  if (metrics.dteAtClose <= 0) return 'Held to expiry';
  if (row.position !== 'short') return 'Closed before expiry';
  if (metrics.capture == null) return 'Unknown';
  return metrics.capture >= 50 ? 'Closed early, 50%+ captured' : metrics.capture >= 0 ? 'Closed early, under 50% captured' : 'Closed early at a loss';
}

export const GROUPINGS = {
  strategy: ['Strategy', row => `${row.position === 'short' ? 'Short' : 'Long'} ${row.option_type}`],
  dte: ['Days to expiry at entry', row => bucket(calendarDays(row.opened_at, row.expiry), DTE_BUCKETS), [...DTE_BUCKETS.map(([, label]) => label), 'Unknown']],
  held: ['Days held', row => bucket(recordedTradeMetrics(row).daysHeld, HELD_BUCKETS), [...HELD_BUCKETS.map(([, label]) => label), 'Unknown']],
  closed: ['How it was closed', howClosed, CLOSE_ORDER],
  ticker: ['Ticker', row => row.ticker],
  month: ['Closing month', row => String(row.closed_at).slice(0, 7)],
  exit: ['Exit reason', row => EXIT_REASONS[row.review?.exit_reason] || 'Not recorded'],
  account: ['Account', row => row.account || 'Default'],
};

export function groupedOptionStats(rows, grouping) {
  const [, keyOf, order] = GROUPINGS[grouping];
  const groups = new Map();
  rows.filter(row => recordedTradeMetrics(row).option && finiteNumber(row.net_pnl)).forEach(row => {
    const key = keyOf(row);
    groups.set(key, [...(groups.get(key) || []), row]);
  });
  return [...groups.entries()].map(([key, members]) => ({ key, ...recordedOptionStats(members) }))
    .sort((first, second) => order ? order.indexOf(first.key) - order.indexOf(second.key)
      : grouping === 'month' ? second.key.localeCompare(first.key) : second.net - first.net);
}

const EDGE_MIN_CLOSES = 5;
const EDGE_DIMENSIONS = ['strategy', 'dte', 'held', 'closed', 'ticker'];

/** Strongest and weakest patterns by net expectancy per close, ignoring groups under EDGE_MIN_CLOSES. */
export function edgeHighlights(rows) {
  const groups = EDGE_DIMENSIONS.flatMap(dimension => groupedOptionStats(rows, dimension)
    .filter(group => group.count >= EDGE_MIN_CLOSES && group.key !== 'Unknown')
    .map(group => ({ ...group, dimension: GROUPINGS[dimension][0] })));
  const ranked = [...groups].sort((first, second) => second.expectancy - first.expectancy);
  return { best: ranked.filter(group => group.expectancy > 0).slice(0, 3),
    worst: ranked.filter(group => group.expectancy < 0).reverse().slice(0, 3) };
}

function GroupedOptionStats({ rows }) {
  const [grouping, setGrouping] = useState('strategy');
  const groups = groupedOptionStats(rows, grouping);
  if (!groups.length) return null;
  const edge = edgeHighlights(rows);
  const line = group => <li key={`${group.dimension}:${group.key}`}><strong>{group.dimension}: {group.key}</strong>{' '}
    <span className={pnlClass(group.expectancy)}>{money(group.expectancy)}</span> per close over {group.count} closes
    {' '}({percent(group.winRate)} wins, {money(group.net)} net)</li>;
  return <div className="journal-breakdown">
    <div className="edge-report" aria-label="Your edge">
      <h4>Your edge</h4>
      {edge.best.length || edge.worst.length ? <div className="edge-columns">
        {edge.best.length > 0 && <div><span className="positive">Working best</span><ul>{edge.best.map(line)}</ul></div>}
        {edge.worst.length > 0 && <div><span className="negative">Costing you</span><ul>{edge.worst.map(line)}</ul></div>}
      </div> : <p className="market-sub">Needs at least {EDGE_MIN_CLOSES} closed options in the same group (strategy, days to expiry, days held, how closed or ticker) before a pattern is shown.</p>}
      <p className="market-sub">Ranked by net dollars per close using recorded fees. Groups overlap (one close counts in each dimension) and small samples mislead: treat these as questions to look into, not rules.</p>
    </div>
    <div className="ivrank-header"><h4 style={{ margin: 0 }}>Option results by {GROUPINGS[grouping][0].toLowerCase()}</h4>
      <label className="market-sub">Group by{' '}<select value={grouping} onChange={event => setGrouping(event.target.value)}>
        {Object.entries(GROUPINGS).map(([key, [label]]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
    <div className="table-scroll"><table className="market-table" aria-label="Grouped option results">
      <thead><tr><th>{GROUPINGS[grouping][0]}</th><th>Closes</th><th>Net win rate</th><th>Net P&L</th><th>Expectancy / close</th><th>Profit factor</th></tr></thead>
      <tbody>{groups.map(group => <tr key={group.key} className="no-click"><td>{group.key}</td><td>{group.count}</td>
        <td>{percent(group.winRate)}</td><td className={pnlClass(group.net)}>{money(group.net)}</td>
        <td className={pnlClass(group.expectancy)}>{money(group.expectancy)}</td><td>{group.profitFactor}</td></tr>)}</tbody>
    </table></div>
    {groups.some(group => group.count < 10) && <p className="market-sub">Groups with fewer than 10 closes are too small to show a reliable edge.</p>}
  </div>;
}

function Breakdown({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div className="journal-breakdown">
      <h4>{title}</h4>
      <table className="market-table">
        <thead><tr><th></th><th>Trades</th><th>Win %</th><th>P&L</th><th>Avg R</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.key} className="no-click">
              <td>{r.key}</td><td>{r.trades}</td><td>{r.win_rate}%</td>
              <td className={r.pnl >= 0 ? 'positive' : 'negative'}>{money(r.pnl)}</td>
              <td>{r.avg_r ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PlanTrade() {
  const dialog = useRef(null);
  return (
    <>
      <button className="btn-secondary btn-sm" aria-haspopup="dialog" onClick={() => dialog.current.showModal()}>Plan a trade</button>
      <dialog ref={dialog} className="journal-plan-dialog" aria-labelledby="journal-plan-title">
        <div className="journal-plan-header">
          <h2 id="journal-plan-title">Plan a trade</h2>
          <button className="btn-secondary btn-sm" onClick={() => dialog.current.close()}>Close</button>
        </div>
        <div className="tools-grid">
          <PreTradeChecklist />
          <PositionCalculator />
        </div>
      </dialog>
    </>
  );
}

function TradeReview({ trade, onClose, onSaved }) {
  const dialog = useRef(null);
  const pending = useRef(false);
  const attempt = useRef(null);
  const [reason, setReason] = useState(trade.review?.exit_reason || '');
  const [target, setTarget] = useState(trade.review?.target_capture_pct ?? '');
  const [note, setNote] = useState(trade.review?.review_note || '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const metrics = recordedTradeMetrics(trade);
  useEffect(() => { dialog.current.showModal(); }, []);
  const valid = target === '' || (Number.isFinite(Number(target)) && Number(target) >= 0 && Number(target) <= 100);
  const submit = async event => {
    event.preventDefault();
    if (pending.current || !valid) return;
    const body = { kind: 'review', event_id: trade.ledger_event_id, exit_reason: reason || null,
      target_capture_pct: metrics.option && trade.position === 'short' && target !== '' ? Number(target) : null, note };
    const signature = JSON.stringify(body);
    if (attempt.current?.signature !== signature) attempt.current = { signature,
      payload: { ...body, occurred_at: new Date().toISOString(), idempotency_key: crypto.randomUUID() } };
    pending.current = true; setBusy(true); setError(null);
    try { await recordAccountingEntry(attempt.current.payload); onSaved(); }
    catch (failure) { setError(failure.message); }
    finally { pending.current = false; setBusy(false); }
  };
  return <dialog ref={dialog} className="journal-plan-dialog" aria-labelledby="trade-review-title"
    onCancel={event => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="journal-plan-header"><h3 id="trade-review-title">Review {trade.ticker} closed trade</h3>
      <button className="btn-secondary btn-sm" disabled={busy} onClick={onClose}>Close</button></div>
    <form onSubmit={submit} className="closed-option-form" aria-label="Trade review">
      <fieldset disabled={busy}>
        <label>Exit reason<select className="tool-input" value={reason} onChange={event => setReason(event.target.value)}>
          <option value="">Not recorded</option>{Object.entries(EXIT_REASONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        {metrics.option && trade.position === 'short' && <label>Target capture (%)<input className="tool-input" type="number"
          min="0" max="100" step="0.01" value={target} onChange={event => setTarget(event.target.value)} /></label>}
        <div className="closed-option-wide closed-option-notes-field"><label htmlFor="trade-review-note">Review notes</label>
          <textarea id="trade-review-note" className="tool-input" maxLength={500} rows={3} value={note} onChange={event => setNote(event.target.value)} /></div>
        {metrics.option && <p className="closed-option-wide">Actual {metrics.label.toLowerCase()}: {percent(metrics.capture)} before fees.</p>}
        <p className="closed-option-wide market-sub">Retrospective review. Targets entered here are not verified pre-trade plans.
          Exit reasons are user-reported; they do not execute assignment, expiry or a roll. Saving preserves prior reviews and does not change fills or P&L.</p>
        {error && <p className="closed-option-wide error-text" role="alert">{error}</p>}
        <button type="submit" className="btn-primary btn-sm" disabled={busy || !valid}>{busy ? 'Saving...' : 'Save review'}</button>
      </fieldset>
    </form>
  </dialog>;
}

function RecordedHistory({ optionsOnly = false, version = 0, onEdit, onDelete, busy = false }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [reviewTrade, setReviewTrade] = useState(null);
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState('all');
  const [limit, setLimit] = useState(PAGE);
  const [revision, setRevision] = useState(0);
  const [saved, setSaved] = useState(null);
  useEffect(() => {
    let active = true;
    setError(null);
    setRows(null);
    Promise.all([optionsOnly ? Promise.resolve({ trades: [] }) : fetchClosedTrades(), fetchClosedOptions()]).then(([stocks, options]) => {
      if (active) setRows([...stocks.trades.map(trade => ({ ...trade, key: `stock:${trade.id}`, kind: 'Stock', quantity: trade.shares })),
        ...options.trades.map(trade => ({ ...trade, key: `option:${trade.id}`, kind: `${trade.position} ${trade.option_type} $${trade.strike} ${trade.expiry}`, quantity: trade.contracts }))]
        .sort((first, second) => String(second.closed_at).localeCompare(String(first.closed_at))));
    }).catch(reason => { if (active) setError(reason.message); });
    return () => { active = false; };
  }, [optionsOnly, version, revision]);
  if (error) return <p className="error-text">{error}</p>;
  if (!rows) return <Skeleton label="Loading recorded trades" lines={2} />;
  if (!rows.length) return <p className="empty-state">{optionsOnly ? 'No closed options recorded.' : 'No closed stock or option trades recorded.'}</p>;
  const grossTotal = rows.reduce((total, row) => total + row.pnl, 0);
  const stats = recordedOptionStats(rows);
  const search = query.trim().toUpperCase();
  const filtered = rows.filter(row => (kind === 'all' || (kind === 'options') === row.key.startsWith('option:'))
    && (!search || row.ticker.toUpperCase().includes(search)));
  const visible = filtered.slice(0, limit);
  return <section className="portfolio-section">
    <h3>{optionsOnly ? 'Recorded closed options' : 'Recorded stock and option trades'}</h3>
    {saved && <p className="positive" role="status">{saved}</p>}
    {reviewTrade && <TradeReview key={reviewTrade.key} trade={reviewTrade} onClose={() => setReviewTrade(null)}
      onSaved={() => { setSaved(`${reviewTrade.ticker} review saved.`); setReviewTrade(null); setRevision(value => value + 1); }} />}
    <p>Gross realized P&L: <span className={grossTotal > 0 ? 'positive' : grossTotal < 0 ? 'negative' : ''}>{money(grossTotal)}</span></p>
    <div className="doctor-stats" aria-label="Recorded option performance">
      <div><span>Options with net results</span><strong>{stats.count}</strong></div>
      <div><span>Recorded net option P&L</span><strong className={pnlClass(stats.net)}>{stats.count ? money(stats.net) : 'Unavailable'}</strong></div>
      <div><span>Net expectancy / close</span><strong className={pnlClass(stats.expectancy)}>{stats.expectancy == null ? 'Unavailable' : money(stats.expectancy)}</strong></div>
      <div><span>Net win rate</span><strong>{percent(stats.winRate)}</strong></div>
      <div><span>Net profit factor</span><strong>{stats.profitFactor}</strong></div>
    </div>
    <p className="market-sub">Capture and return percentages are before fees and measure the option only, not return on collateral or a full wheel cycle.
      Net statistics include recorded fees only; each closing record counts once, including partial closes. Past averages are not forecasts.</p>
    <GroupedOptionStats rows={rows} />
    <div className="trade-history-toolbar">
      <input className="tool-input" type="search" aria-label="Filter by ticker" placeholder="Filter by ticker" maxLength={12}
        value={query} onChange={event => { setQuery(event.target.value); setLimit(PAGE); }} />
      {!optionsOnly && <div className="trade-history-kinds" role="group" aria-label="Trade type">
        {[['all', 'All'], ['options', 'Options'], ['stocks', 'Stocks']].map(([value, label]) =>
          <button key={value} type="button" className={`watchlist-tab${kind === value ? ' active' : ''}`} aria-pressed={kind === value}
            onClick={() => { setKind(value); setLimit(PAGE); }}>{label}</button>)}
      </div>}
      <span className="market-sub">{filtered.length === rows.length ? `${rows.length} trades` : `${filtered.length} of ${rows.length} trades`}</span>
    </div>
    {!filtered.length ? <p className="empty-state">No recorded trades match this filter.</p> : <>
    <div className="table-scroll"><table className="market-table trade-history-table" aria-label="Recorded trades">
      <thead><tr><th>Trade</th><th>Dates</th><th>Premium / price</th><th>Captured / return</th><th>Exit reason</th><th>Net P&L</th><th><span className="sr-only">Actions</span></th></tr></thead>
      <tbody>{visible.map(row => {
        const metrics = recordedTradeMetrics(row);
        const opened = shortDate(row.opened_at || row.acquired_at);
        const closed = shortDate(row.closed_at);
        const timing = [metrics.daysHeld != null && `${metrics.daysHeld}d held`,
          metrics.option && metrics.dteAtClose != null && `${metrics.dteAtClose} DTE left`].filter(Boolean).join(' · ');
        const size = metrics.option ? `${row.quantity} contract${row.quantity === 1 ? '' : 's'}` : `${row.quantity} shares`;
        const stockReturn = !metrics.option && finiteNumber(row.pnl_pct) ? Number(row.pnl_pct) : null;
        return <tr key={row.key}>
          <td className="trade-cell"><strong>{row.ticker}</strong>
            <span className={`trade-badge trade-${metrics.option ? row.position : 'stock'}`}>{metrics.option ? `${row.position} ${row.option_type}` : 'stock'}</span>
            {row.account && row.account !== 'Default' && <span className="account-badge">{row.account}</span>}
            <span className="trade-sub">{metrics.option ? `$${row.strike} · exp ${shortDate(row.expiry) || row.expiry} · ` : ''}{size}</span></td>
          <td className="nowrap" data-label="Dates">{opened ? <>{opened} → {closed}</> : closed || <Missing reason="Close date unavailable" />}
            {timing && <span className="trade-sub">{timing}</span>}</td>
          <td className="nowrap" data-label="Premium / price">{metrics.option && row.open_premium != null ? `${price(row.open_premium)} → ${price(row.close_premium)}`
            : !metrics.option && row.buy_price != null ? `${price(row.buy_price)} → ${price(row.sell_price)}` : <Missing reason="Prices unavailable" />}</td>
          <td data-label="Captured / return">{metrics.option && metrics.capture != null ? <div className="capture-cell">
              <span className={pnlClass(metrics.capture)}>{metrics.capture.toFixed(1)}%</span> <small>{metrics.label.toLowerCase()}</small>
              <span className="capture-bar" aria-hidden="true"><span className={metrics.capture < 0 ? 'negative-fill' : ''} style={{ width: barWidth(Math.abs(metrics.capture)) }} />
                {metrics.target != null && <i style={{ left: barWidth(metrics.target) }} />}</span>
              {metrics.target != null && <span className="trade-sub">Target {percent(metrics.target)} · <span className={pnlClass(metrics.targetGap)}>
                {metrics.targetGap > 0 ? '+' : ''}{metrics.targetGap.toFixed(1)} pp</span></span>}
            </div>
            : stockReturn != null ? <><span className={pnlClass(stockReturn)}>{stockReturn.toFixed(1)}%</span> <small>return</small></>
              : <Missing reason={metrics.option ? 'Premiums unavailable' : 'Return unavailable'} />}</td>
          <td data-label="Exit reason">{EXIT_REASONS[row.review?.exit_reason] || <Missing reason="Exit reason not recorded" />}</td>
          <td className="trade-pnl">{row.net_pnl != null
            ? <><strong className={pnlClass(row.net_pnl)}>{money(row.net_pnl)}</strong><span className="trade-sub">Gross {money(row.pnl)} · fees {money(row.fees)}</span></>
            : <><strong className={pnlClass(row.pnl)}>{money(row.pnl)}</strong><span className="trade-sub">Gross · no fees recorded</span></>}</td>
          <td className="closed-option-actions">
            <button className="btn-secondary btn-sm" type="button" title="Exit reason, target and review notes" aria-label={`Review ${row.ticker} trade ${row.id}`}
              disabled={busy || !row.ledger_event_id} onClick={() => { setSaved(null); setReviewTrade(row); }}>Review</button>
            {onEdit && row.is_manual && <>
              <button className="btn-icon" type="button" title="Edit manual option" aria-label={`Edit ${row.ticker} option`} disabled={busy} onClick={() => onEdit(row)}>✏️</button>
              <button className="btn-icon" type="button" title="Delete manual option" aria-label={`Delete ${row.ticker} option`} disabled={busy} onClick={() => onDelete(row)}>🗑</button>
            </>}
            {(row.notes || row.review) && <details className="closed-option-notes"><summary>Notes</summary>{row.notes && <p>{row.notes}</p>}
              {row.review && <><p>{row.review.review_note || 'No review notes.'}</p><small>Review recorded {row.review.review_recorded_at}</small></>}</details>}
          </td></tr>; })}</tbody>
    </table></div>
    {filtered.length > visible.length && <button type="button" className="btn-secondary btn-sm trade-history-more" onClick={() => setLimit(value => value + PAGE)}>
      Show {Math.min(PAGE, filtered.length - visible.length)} more ({visible.length} of {filtered.length} shown)</button>}
    </>}
    {filtered.length > 0 && <PnlCalendar rows={filtered} />}
  </section>;
}

const EMPTY_OPTION = { ticker: '', option_type: 'put', position: 'short', strike: '', expiry: '', contracts: '1',
  open_premium: '', close_premium: '', opened_at: '', closed_at: '', fees: '0', notes: '' };

function OptionDateField({ name, label, value, onChange, max }) {
  const input = useRef(null);
  const openCalendar = () => {
    input.current?.focus();
    try { input.current?.showPicker?.(); } catch { input.current?.focus(); }
  };
  return <div className="closed-option-date-field">
    <label htmlFor={`closed-option-${name}`}>{label}</label>
    <div className="closed-option-date-control">
      <input ref={input} id={`closed-option-${name}`} className="tool-input" type="date" required max={max} value={value} onChange={onChange} />
      <button className="btn-icon" type="button" title={`Open ${label.toLowerCase()} calendar`} aria-label={`Open ${label.toLowerCase()} calendar`} onClick={openCalendar}>📅</button>
    </div>
  </div>;
}

function ClosedOptionJournal() {
  const [form, setForm] = useState(EMPTY_OPTION);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);
  const [version, setVersion] = useState(0);
  const [editId, setEditId] = useState(null);
  const tickerInput = useRef(null);
  const attempt = useRef(null);
  const pending = useRef(false);
  useEffect(() => { if (show) tickerInput.current?.focus(); }, [show, editId]);
  const set = key => event => setForm(value => ({ ...value, [key]: event.target.value }));
  const numeric = ['strike', 'contracts', 'open_premium', 'close_premium', 'fees'];
  const validNumbers = numeric.every(key => form[key] !== '' && Number.isFinite(Number(form[key])))
    && Number(form.strike) > 0 && Number(form.open_premium) > 0 && Number(form.close_premium) >= 0
    && Number(form.fees) >= 0 && Number.isInteger(Number(form.contracts)) && Number(form.contracts) > 0;
  const dateError = form.opened_at && form.closed_at && form.opened_at > form.closed_at ? 'Closing date cannot precede opening date.'
    : form.closed_at && form.closed_at > today() ? 'Completed trades cannot have future dates.'
      : form.expiry && form.closed_at && form.closed_at > form.expiry ? 'Closing date cannot be after expiry.' : null;
  const valid = validNumbers && /^[A-Z^][A-Z0-9.^=-]{0,19}$/.test(form.ticker.trim().toUpperCase())
    && form.opened_at && form.closed_at && form.expiry && !dateError;
  const gross = validNumbers ? Math.round((Number(form.close_premium) - Number(form.open_premium))
    * Number(form.contracts) * 100 * (form.position === 'short' ? -1 : 1) * 100) / 100 : null;
  const save = async event => {
    event.preventDefault();
    if (!valid || pending.current) return;
    const payload = { ...form, ticker: form.ticker.trim().toUpperCase(), contracts: Number(form.contracts) };
    const signature = JSON.stringify({ editId, payload });
    if (attempt.current?.signature !== signature) attempt.current = { signature, key: crypto.randomUUID() };
    pending.current = true;
    setBusy(true); setError(null); setSaved(null);
    try {
      const request = { ...payload, idempotency_key: attempt.current.key };
      if (editId !== null) await updateClosedOption(editId, request);
      else await logClosedOption(request);
      setSaved(`${payload.ticker} closed option ${editId !== null ? 'updated' : 'recorded'}.`);
      setForm(EMPTY_OPTION); setEditId(null); setShow(false); setVersion(value => value + 1); attempt.current = null;
    } catch (reason) { setError(reason.message); }
    finally { pending.current = false; setBusy(false); }
  };
  const edit = row => {
    setForm(Object.fromEntries(Object.keys(EMPTY_OPTION).map(key => [key, String(row[key] ?? EMPTY_OPTION[key])])));
    setEditId(row.id); setShow(true); setError(null); setSaved(null); attempt.current = null;
  };
  const remove = async row => {
    if (pending.current || !window.confirm(`Delete this ${row.ticker} manual option entry and its recorded fees? The audit history will be retained.`)) return;
    pending.current = true; setBusy(true); setError(null); setSaved(null);
    try {
      await deleteClosedOption(row.id);
      if (editId === row.id) { setEditId(null); setForm(EMPTY_OPTION); setShow(false); attempt.current = null; }
      setSaved(`${row.ticker} closed option deleted.`); setVersion(value => value + 1);
    } catch (reason) { setError(reason.message); }
    finally { pending.current = false; setBusy(false); }
  };
  return <section className="portfolio-section closed-option-journal">
    <div className="journal-plan-header"><h3>Options journal</h3>
      <button className="btn-primary btn-sm" disabled={busy} aria-expanded={show} onClick={() => { setShow(!show); setEditId(null); setForm(EMPTY_OPTION); attempt.current = null; setError(null); setSaved(null); }}>
        {show ? 'Cancel option entry' : 'Log closed option'}
      </button>
    </div>
    {saved && <p role="status" className="positive">{saved}</p>}
    {error && <p className="error-text" role="alert">{error}</p>}
    {show && <form className="closed-option-form" aria-label="Closed option entry" onSubmit={save}>
      <fieldset disabled={busy}>
        <legend>{editId !== null ? 'Edit closed option' : 'Completed single-leg option'} · Standard 100-share contracts</legend>
        <label>Option ticker<input ref={tickerInput} className="tool-input" required maxLength={20} value={form.ticker} onChange={set('ticker')} /></label>
        <label>Option type<select className="tool-input" value={form.option_type} onChange={set('option_type')}><option value="put">Put</option><option value="call">Call</option></select></label>
        <label>Position<select className="tool-input" value={form.position} onChange={set('position')}><option value="short">Short (sold to open)</option><option value="long">Long (bought to open)</option></select></label>
        <label>Strike ($)<input className="tool-input" type="number" required min="0.000001" step="0.000001" value={form.strike} onChange={set('strike')} /></label>
        <OptionDateField name="expiry" label="Expiry" value={form.expiry} onChange={set('expiry')} />
        <label>Contracts<input className="tool-input" type="number" required min="1" step="1" value={form.contracts} onChange={set('contracts')} /></label>
        <OptionDateField name="opened" label="Opened on" max={today()} value={form.opened_at} onChange={set('opened_at')} />
        <OptionDateField name="closed" label="Closed on" max={today()} value={form.closed_at} onChange={set('closed_at')} />
        <label>Opening premium ($/share)<input className="tool-input" type="number" required min="0.000001" step="0.000001" value={form.open_premium} onChange={set('open_premium')} /></label>
        <label>Closing premium ($/share)<input className="tool-input" type="number" required min="0" step="0.000001" value={form.close_premium} onChange={set('close_premium')} /></label>
        <label>Total fees ($, both sides)<input className="tool-input" type="number" required min="0" step="0.01" value={form.fees} onChange={set('fees')} /></label>
        <div className="closed-option-wide closed-option-notes-field">
          <label htmlFor="closed-option-notes">Option notes</label>
          <textarea id="closed-option-notes" className="tool-input" rows={3} maxLength={1000} value={form.notes} onChange={set('notes')} />
        </div>
        <div className="closed-option-wide doctor-stats" aria-label="Option P&L preview">
          <div><span>Gross P&L</span><strong>{money(gross)}</strong></div>
          <div><span>Recorded fees</span><strong>{validNumbers ? money(Number(form.fees)) : '—'}</strong></div>
          <div><span>Net P&L</span><strong>{gross == null ? '—' : money(gross - Number(form.fees))}</strong></div>
        </div>
        <p className="closed-option-wide market-sub">{editId !== null ? 'Corrections retain the audit history and replace recorded fees.' : 'For previously unrecorded trades only. No automatic matching to existing records or assignment, exercise or adjusted-contract accounting.'}</p>
        {dateError && <p className="closed-option-wide error-text" role="alert">{dateError}</p>}
        <button className="btn-primary btn-sm" disabled={!valid || busy} type="submit">{busy ? 'Saving...' : editId !== null ? 'Save option changes' : 'Record closed option'}</button>
      </fieldset>
    </form>}
    <RecordedHistory optionsOnly version={version} onEdit={edit} onDelete={remove} busy={busy} />
  </section>;
}

export default function Journal(props) {
  const { user } = useAuth();
  const [revision, setRevision] = useState(0);
  return <div className="journal-workspace" key={user?.id ?? user?.username ?? 'guest'}>
    <header className="journal-plan-header"><h2>Journal</h2><PlanTrade /></header>
    <AccountTransfer onImported={() => setRevision(value => value + 1)} />
    <JournalViews key={revision} {...props} />
  </div>;
}

function JournalViews({ onSignIn, onSelect }) {
  const { user } = useAuth();
  const [report, setReport] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [editId, setEditId] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [msg, setMsg] = useState(null);
  const [coach, setCoach] = useState(null);
  const [coachLoading, setCoachLoading] = useState(false);
  const [view, setView] = useState('history');

  const load = useCallback(() => {
    fetchJournal().then(setReport).catch(e => setMsg(e.message));
  }, []);

  useEffect(() => { if (user) load(); }, [user, load]);

  if (!user) {
    return (
      <div className="journal">
        <div className="card">
          <h3>📓 Trade Journal</h3>
          <p className="empty-state" style={{ padding: 0 }}>Sign in to log trades and get AI coaching on your win rate, R-multiples and habits.</p>
          {onSignIn && <button className="btn-primary btn-sm" onClick={onSignIn}>Sign in</button>}
        </div>
      </div>
    );
  }

  const set = (k) => (e) => setForm(f => ({ ...f, [k]: e.target.value }));
  const navigation = <TabStrip label="Journal views" activeKey={view}>
    {[['history', 'Trade history'], ['journal', 'Manual journal'], ['options', 'Options review'], ['cycles', 'Wheel cycles']].map(([id, label]) =>
      <button key={id} className={`sub-tab ${view === id ? 'active' : ''}`} onClick={() => setView(id)}>{label}</button>)}
  </TabStrip>;
  if (view !== 'journal') return <div className="journal portfolio-workspace">{navigation}
    {view === 'history' ? <RecordedHistory /> : view === 'cycles' ? <WheelCycles /> : <Review version={user.id} />}
  </div>;

  const save = async () => {
    setMsg(null);
    const num = v => (v === '' || v == null ? null : Number(v));
    const payload = {
      ...form, ticker: form.ticker.trim().toUpperCase(), shares: num(form.shares), entry_price: num(form.entry_price),
      stop: num(form.stop), target: num(form.target), exit_price: num(form.exit_price),
      exit_date: form.exit_price ? (form.exit_date || today()) : null, setup: form.setup || null, notes: form.notes || null,
    };
    try {
      if (editId) await updateJournalEntry(editId, payload); else await addJournalEntry(payload);
      setForm(EMPTY); setEditId(null); setShowForm(false); load();
    } catch (e) { setMsg(e.message); }
  };

  const edit = (t) => {
    setForm(Object.fromEntries(Object.keys(EMPTY).map(k => [k, t[k] ?? ''])));
    setEditId(t.id); setShowForm(true);
  };

  const remove = async (id) => {
    if (!window.confirm('Delete this trade?')) return;
    try { await deleteJournalEntry(id); load(); } catch (e) { setMsg(e.message); }
  };

  const runCoach = async () => {
    setCoachLoading(true);
    try { setCoach(await fetchJournalCoach()); } catch (e) { setCoach({ summary: e.message, strengths: [], leaks: [], rules: [] }); }
    finally { setCoachLoading(false); }
  };

  const s = report?.stats;
  const risk = form.stop && form.entry_price && form.shares
    ? Math.abs(Number(form.entry_price) - Number(form.stop)) * Number(form.shares) : null;
  const rr = form.stop && form.target && form.entry_price
    ? Math.abs(Number(form.target) - Number(form.entry_price)) / Math.abs(Number(form.entry_price) - Number(form.stop)) : null;

  return (
    <div className="journal">
      {navigation}
      <ClosedOptionJournal />
      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>Manual stock journal</h3>
          <button className="btn-primary btn-sm" onClick={() => { setShowForm(!showForm); setEditId(null); setForm(EMPTY); }}>
            {showForm ? 'Cancel' : '+ Log stock trade'}
          </button>
        </div>
        {msg && <p className="error-text">{msg}</p>}

        {showForm && (
          <div className="journal-form">
            <input className="tool-input" placeholder="Ticker" value={form.ticker} onChange={set('ticker')} />
            <select className="candle-select" value={form.side} onChange={set('side')}>
              <option value="long">Long</option><option value="short">Short</option>
            </select>
            <input className="tool-input" type="number" placeholder="Shares" value={form.shares} onChange={set('shares')} />
            <label>Entry<input className="tool-input" type="date" value={form.entry_date} onChange={set('entry_date')} /></label>
            <input className="tool-input" type="number" step="any" placeholder="Entry price" value={form.entry_price} onChange={set('entry_price')} />
            <input className="tool-input" type="number" step="any" placeholder="Stop" value={form.stop} onChange={set('stop')} />
            <input className="tool-input" type="number" step="any" placeholder="Target" value={form.target} onChange={set('target')} />
            <input className="tool-input" list="setup-tags" placeholder="Setup tag" value={form.setup} onChange={set('setup')} maxLength={40} />
            <datalist id="setup-tags">{SETUP_TAGS.map(t => <option key={t} value={t} />)}</datalist>
            <label>Exit<input className="tool-input" type="date" value={form.exit_date} onChange={set('exit_date')} /></label>
            <input className="tool-input" type="number" step="any" placeholder="Exit price (blank if open)" value={form.exit_price} onChange={set('exit_price')} />
            <textarea className="tool-input journal-notes" placeholder="Notes: why you took it, emotions, mistakes…" value={form.notes} onChange={set('notes')} maxLength={1000} />
            <div className="journal-form-footer">
              {risk != null && <span className="market-sub">Risk ${risk.toFixed(2)}{rr != null && ` · reward/risk ${rr.toFixed(1)}:1`}</span>}
              <button className="btn-primary btn-sm" onClick={save}
                disabled={!form.ticker || !form.shares || !form.entry_price || !form.entry_date}>
                {editId ? 'Update trade' : 'Save trade'}
              </button>
            </div>
          </div>
        )}

        {s && (
          <div className="doctor-stats">
            <div><span>Total P&L</span><strong className={s.total_pnl >= 0 ? 'positive' : 'negative'}>{money(s.total_pnl)}</strong></div>
            <div><span>Win rate</span><strong>{s.win_rate != null ? `${s.win_rate}%` : '—'}</strong></div>
            <div><span>Profit factor</span><strong>{s.profit_factor ?? '—'}</strong></div>
            <div><span>Expectancy / trade</span><strong>{money(s.expectancy)}</strong></div>
            <div><span>Avg R</span><strong>{s.avg_r ?? '—'}</strong></div>
            <div><span>Avg win / loss</span><strong>{money(s.avg_win)} / {money(s.avg_loss)}</strong></div>
            <div><span>Max drawdown</span><strong className="negative">{money(s.max_drawdown)}</strong></div>
            <div><span>Closed / open</span><strong>{s.closed} / {s.open}</strong></div>
          </div>
        )}
        {s && s.pct_with_stop != null && s.pct_with_stop < 80 && (
          <p className="income-warning">Only {s.pct_with_stop}% of trades have a stop logged — add stops to measure risk (R-multiples).</p>
        )}
      </div>

      {report?.equity?.length > 1 && (
        <div className="card">
          <h3>Equity curve</h3>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={report.equity}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
              <YAxis tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickFormatter={v => `$${v}`} />
              <Tooltip formatter={v => money(v)} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)' }} />
              <ReferenceLine y={0} stroke="var(--text-muted)" />
              <Area type="monotone" dataKey="equity" stroke="#7c6cf0" fill="rgba(124,108,240,0.2)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>🧠 AI Coach</h3>
          <button className="btn-secondary btn-sm" onClick={runCoach} disabled={coachLoading}>
            {coachLoading ? 'Reviewing trades…' : coach ? '↻ Re-run' : 'Review my trading'}
          </button>
        </div>
        {!coach && <p className="market-sub">Finds your edge and your leaks from your logged trades (needs 5+ closed trades).</p>}
        {coach && (
          <>
            <p className="ai-brief-summary">{coach.summary}</p>
            <div className="bull-bear-grid">
              {coach.strengths?.length > 0 && <div className="bull-col bull-bear-col"><div className="bull-bear-col-header">What's working</div><ul>{coach.strengths.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
              {coach.leaks?.length > 0 && <div className="bear-col bull-bear-col"><div className="bull-bear-col-header">Leaks</div><ul>{coach.leaks.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
            </div>
            {coach.rules?.length > 0 && <div className="bull-bear-col ai-brief-neutral"><div className="bull-bear-col-header">Rules for next week</div><ul>{coach.rules.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
          </>
        )}
      </div>

      {report?.entries?.length > 0 && (
        <div className="card">
          <h3>Trades</h3>
          <div className="table-scroll">
            <table className="market-table">
              <thead><tr><th>Entry</th><th>Ticker</th><th>Side</th><th>Shares</th><th>Entry → Exit</th><th>P&L</th><th>R</th><th>Days</th><th>Setup</th><th></th></tr></thead>
              <tbody>
                {report.entries.map(t => (
                  <tr key={t.id} className="no-click" title={t.notes || ''}>
                    <td>{t.entry_date}</td>
                    <td><a onClick={() => onSelect?.(t.ticker)} className="link">{t.ticker}</a></td>
                    <td>{t.side}</td>
                    <td>{t.shares}</td>
                    <td>${t.entry_price} → {t.exit_price != null ? `$${t.exit_price}` : <span className="market-sub">open</span>}</td>
                    <td className={t.pnl >= 0 ? 'positive' : 'negative'}>{t.pnl != null ? `${money(t.pnl)} (${t.pnl_pct}%)` : '—'}</td>
                    <td>{t.r_multiple ?? '—'}</td>
                    <td>{t.hold_days ?? '—'}</td>
                    <td>{t.setup || '—'}</td>
                    <td className="journal-actions">
                      <button className="btn-icon" onClick={() => edit(t)} title="Edit / close">✎</button>
                      <button className="btn-icon" onClick={() => remove(t.id)} title="Delete">✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {report?.stats?.closed > 0 && (
        <div className="card">
          <h3>Where your edge is</h3>
          <div className="journal-breakdowns">
            <Breakdown title="By setup" rows={report.breakdowns.setup} />
            <Breakdown title="By holding period" rows={report.breakdowns.holding} />
            <Breakdown title="By weekday" rows={report.breakdowns.weekday} />
            <Breakdown title="By side" rows={report.breakdowns.side} />
          </div>
        </div>
      )}
    </div>
  );
}
