import { useState, useEffect, useCallback, useRef } from 'react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid, ReferenceLine } from 'recharts';
import { useAuth } from '../AuthContext';
import PreTradeChecklist from './PreTradeChecklist';
import PositionCalculator from './PositionCalculator';
import { Review } from './OptionsDesk';
import WheelCycles from './WheelCycles';
import Skeleton from './Skeleton';
import TabStrip from './TabStrip';
import PnlCalendar from './PnlCalendar';
import {
  fetchJournal, addJournalEntry, updateJournalEntry, deleteJournalEntry, fetchJournalCoach, fetchClosedTrades, fetchClosedOptions, logClosedOption, updateClosedOption, deleteClosedOption,
  recordAccountingEntry, fetchTradePlans, logClosedSpread, deleteClosedSpread,
} from '../api/stockApi';
import { SPREAD_KINDS, spreadLegs, spreadPreview } from '../spreads';

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
// Keys must match ReviewTag in backend/portfolio_models.py; `good` marks habits to repeat
export const REVIEW_TAGS = {
  fomo: ['FOMO entry'], chased: ['Chased the price'], oversized: ['Position too big'], moved_stop: ['Moved my stop'],
  early_exit: ['Exited too early'], late_exit: ['Held too long'], ignored_earnings: ['Ignored earnings'], revenge: ['Revenge trade'],
  patient_entry: ['Patient entry', true], sized_right: ['Sized right', true], cut_loss_fast: ['Cut loss quickly', true],
  let_winner_run: ['Let the winner run', true],
};
const tradeNet = row => (finiteNumber(row.net_pnl) ? Number(row.net_pnl) : Number(row.pnl) || 0);

/** P&L by review tag and by whether the plan was followed (reviewed trades only). */
export function reviewLessons(rows) {
  const groups = new Map();
  const add = (key, row) => groups.set(key, [...(groups.get(key) || []), tradeNet(row)]);
  rows.filter(row => row.review).forEach(row => {
    (row.review.tags || []).forEach(tag => add(`tag:${tag}`, row));
    if (row.review.followed_plan != null) add(`plan:${row.review.followed_plan ? 'yes' : 'no'}`, row);
  });
  const summary = (key, values) => ({ key, count: values.length, net: values.reduce((sum, value) => sum + value, 0),
    winRate: values.filter(value => value > 0).length / values.length * 100 });
  const all = [...groups.entries()].map(([key, values]) => summary(key, values));
  return { plan: ['yes', 'no'].map(answer => all.find(group => group.key === `plan:${answer}`)).filter(Boolean),
    tags: all.filter(group => group.key.startsWith('tag:')).map(group => ({ ...group, tag: group.key.slice(4) }))
      .sort((first, second) => first.net - second.net) };
}

function ReviewLessons({ rows }) {
  const { plan, tags } = reviewLessons(rows);
  if (!plan.length && !tags.length) return null;
  const line = (label, group, good) => <li key={group.key}><strong className={good === true ? 'positive' : good === false ? 'negative' : ''}>{label}</strong>{' '}
    {group.count} trade{group.count === 1 ? '' : 's'} · <span className={pnlClass(group.net)}>{money(group.net)}</span> net · {percent(group.winRate)} winners</li>;
  return <div className="edge-report" aria-label="Lessons from your reviews">
    <h4>Lessons from your reviews</h4>
    {plan.length > 0 && <ul>{plan.map(group => line(group.key === 'plan:yes' ? 'Followed my plan' : 'Broke my plan', group, group.key === 'plan:yes'))}</ul>}
    {tags.length > 0 && <ul>{tags.map(group => line(REVIEW_TAGS[group.tag]?.[0] || group.tag, group, REVIEW_TAGS[group.tag]?.[1] === true ? true : false))}</ul>}
    <p className="market-sub">From the plan answer and tags in your trade reviews (net of recorded fees). A trade counts once per tag. Small samples mislead.</p>
  </div>;
}
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

export const PLAN_WINDOW_DAYS = 30;
const HORIZON_DAYS = { 'Same day (0DTE)': 0, '1–7 days': 7, '1–4 weeks': 28, '1–3 months': 92 };
const localDay = value => {
  const day = new Date(value);
  return Number.isNaN(day.getTime()) ? '' : `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
};

/** Newest saved plan for the ticker made on, or up to PLAN_WINDOW_DAYS before, the day the trade opened (closed if unknown). */
export function matchPlan(plans, trade) {
  const anchor = String(trade.opened_at || trade.acquired_at || trade.closed_at || '').slice(0, 10);
  return plans.filter(plan => plan.ticker === trade.ticker)
    .sort((first, second) => String(second.created_at).localeCompare(String(first.created_at)))
    .find(plan => { const gap = calendarDays(localDay(plan.created_at), anchor); return gap != null && gap <= PLAN_WINDOW_DAYS; }) || null;
}

/** What the closed trade actually was, in the pre-trade checklist's structure terms where possible. */
export const tradeStructure = trade => trade.spread ? `${trade.spread.style} spread`
  : recordedTradeMetrics(trade).option ? `${trade.position} ${trade.option_type}` : null;
const tradeLabel = trade => trade.spread ? `${trade.spread.label} spread` : `${trade.position} ${trade.option_type}`;
const tradeStrikes = trade => trade.spread ? `$${trade.spread.long_strike}/$${trade.spread.short_strike}` : `$${trade.strike}`;

/** Plain comparisons of a closed trade against its saved plan: loss limit, holding period and structure. */
export function planChecks(plan, trade) {
  const checks = [];
  const net = finiteNumber(trade.net_pnl) ? Number(trade.net_pnl) : Number(trade.pnl);
  const maxLoss = Number(plan.max_loss);
  if (Number.isFinite(net) && net < 0) checks.push(-net > maxLoss
    ? { ok: false, text: `Lost ${money(-net)}, more than your planned max loss of ${money(maxLoss)}` }
    : { ok: true, text: `Loss of ${money(-net)} stayed within your planned max of ${money(maxLoss)}` });
  else if (Number.isFinite(net)) checks.push({ ok: true, text: `Closed at ${money(net)}; your planned max loss was ${money(maxLoss)}` });
  const { daysHeld } = recordedTradeMetrics(trade);
  const limit = HORIZON_DAYS[plan.horizon];
  if (daysHeld != null && limit != null) checks.push(daysHeld > limit
    ? { ok: false, text: `Held ${daysHeld} days; you planned ${plan.horizon}` }
    : { ok: true, text: `Held ${daysHeld} days, within your planned ${plan.horizon}` });
  const actual = tradeStructure(trade);
  if (actual && ['Long call', 'Long put', 'Debit spread', 'Credit spread'].includes(plan.structure) && plan.structure.toLowerCase() !== actual)
    checks.push({ ok: false, text: `Planned a ${plan.structure.toLowerCase()}; this trade was a ${actual}` });
  return checks;
}

const CSV_COLUMNS = [
  ['Type', row => row.spread ? 'Option spread' : recordedTradeMetrics(row).option ? 'Option' : 'Stock'], ['Ticker', row => row.ticker],
  ['Side', row => recordedTradeMetrics(row).option ? tradeLabel(row) : 'stock'],
  ['Strike', row => row.spread ? `${row.spread.long_strike}/${row.spread.short_strike}` : row.strike], ['Expiry', row => row.expiry], ['Quantity', row => row.quantity],
  ['Account', row => row.account || 'Default'],
  ['Opened', row => String(row.opened_at || row.acquired_at || '').slice(0, 10)], ['Closed', row => String(row.closed_at || '').slice(0, 10)],
  ['Open price', row => row.open_premium ?? row.buy_price], ['Close price', row => row.close_premium ?? row.sell_price],
  ['Gross P&L', row => row.pnl], ['Fees', row => row.fees], ['Net P&L', row => row.net_pnl],
  ['Exit reason', row => EXIT_REASONS[row.review?.exit_reason] || ''],
  ['Followed plan', row => row.review?.followed_plan == null ? '' : row.review.followed_plan ? 'Yes' : 'No'],
  ['Habit tags', row => (row.review?.tags || []).map(tag => REVIEW_TAGS[tag]?.[0] || tag).join('; ')],
  ['Review note', row => row.review?.review_note], ['Notes', row => row.notes],
];

function csvCell(value) {
  if (value == null || value === '') return '';
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '';
  // A leading = + - @ would run as a formula in Excel/Sheets
  const text = /^[=+\-@\t\r]/.test(String(value)) ? `'${value}` : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

export const tradesCsv = rows => [CSV_COLUMNS.map(([name]) => csvCell(name)).join(','),
  ...rows.map(row => CSV_COLUMNS.map(([, get]) => csvCell(get(row))).join(','))].join('\r\n');

function downloadCsv(rows) {
  const url = URL.createObjectURL(new Blob(['\ufeff', tradesCsv(rows)], { type: 'text/csv;charset=utf-8' }));
  const link = Object.assign(document.createElement('a'), { href: url, download: `stockpilot-trades-${today()}.csv` });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
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
  strategy: ['Strategy', row => row.spread ? `${row.spread.label} spread` : `${row.position === 'short' ? 'Short' : 'Long'} ${row.option_type}`],
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
    <div className="edge-report" id="edge-report" aria-label="Your edge">
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

function PlanTrade({ canSave = false }) {
  const dialog = useRef(null);
  return (
    <>
      <span className="plan-trade-launch">
        <span className="market-sub">Checklist and position size before you enter</span>
        <button className="btn-primary btn-sm" aria-haspopup="dialog" onClick={() => dialog.current.showModal()}><span aria-hidden="true">📝 </span>Plan a trade</button>
      </span>
      <dialog ref={dialog} className="journal-plan-dialog" aria-labelledby="journal-plan-title">
        <div className="journal-plan-header">
          <h2 id="journal-plan-title">Plan a trade</h2>
          <button className="btn-secondary btn-sm" onClick={() => dialog.current.close()}>Close</button>
        </div>
        <div className="tools-grid">
          <PreTradeChecklist canSave={canSave} />
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
  const [plan, setPlan] = useState(trade.review?.followed_plan == null ? '' : trade.review.followed_plan ? 'yes' : 'no');
  const [tags, setTags] = useState(trade.review?.tags || []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [savedPlan, setSavedPlan] = useState(undefined);
  const metrics = recordedTradeMetrics(trade);
  useEffect(() => { dialog.current.showModal(); }, []);
  useEffect(() => {
    let active = true;
    fetchTradePlans(trade.ticker).then(data => { if (active) setSavedPlan(matchPlan(data.items || [], trade)); })
      .catch(() => { if (active) setSavedPlan(null); });
    return () => { active = false; };
  }, [trade]);
  const valid = target === '' || (Number.isFinite(Number(target)) && Number(target) >= 0 && Number(target) <= 100);
  const submit = async event => {
    event.preventDefault();
    if (pending.current || !valid) return;
    const body = { kind: 'review', event_id: trade.ledger_event_id, exit_reason: reason || null,
      target_capture_pct: metrics.option && trade.position === 'short' && target !== '' ? Number(target) : null, note,
      followed_plan: plan === '' ? null : plan === 'yes', tags: tags.length ? tags : null };
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
    {savedPlan ? <section className="review-plan" aria-label="Your saved plan">
      <h4>Your plan <span className="market-sub">saved {shortDate(localDay(savedPlan.created_at)) || 'earlier'}</span></h4>
      <dl>
        <dt>Thesis</dt><dd>{savedPlan.thesis}</dd>
        <dt>Structure</dt><dd>{savedPlan.structure} · {savedPlan.horizon} · max loss {money(Number(savedPlan.max_loss))} ({savedPlan.max_loss_pct}% of account)</dd>
        <dt>If right</dt><dd>{savedPlan.exit_up}</dd>
        <dt>If wrong</dt><dd>{savedPlan.exit_down}</dd>
        <dt>Invalidation</dt><dd>{savedPlan.invalidation}</dd>
      </dl>
      <ul className="review-plan-checks">{planChecks(savedPlan, trade).map(check =>
        <li key={check.text} className={check.ok ? 'positive' : 'negative'}>{check.ok ? '✓' : '✗'} {check.text}</li>)}</ul>
    </section> : savedPlan === null && <p className="market-sub">No saved plan for {trade.ticker} from the {PLAN_WINDOW_DAYS} days before this trade opened.
      Next time, use 📝 Plan a trade → Save plan before you enter.</p>}
    <form onSubmit={submit} className="closed-option-form" aria-label="Trade review">
      <fieldset disabled={busy}>
        <label>Exit reason<select className="tool-input" value={reason} onChange={event => setReason(event.target.value)}>
          <option value="">Not recorded</option>{Object.entries(EXIT_REASONS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        {metrics.option && trade.position === 'short' && <label>Target capture (%)<input className="tool-input" type="number"
          min="0" max="100" step="0.01" value={target} onChange={event => setTarget(event.target.value)} /></label>}
        <label>Did you follow your plan?<select className="tool-input" value={plan} onChange={event => setPlan(event.target.value)}>
          <option value="">Not recorded</option><option value="yes">Yes</option><option value="no">No</option></select></label>
        <fieldset className="closed-option-wide review-tags">
          <legend>What happened? <span className="market-sub">(up to 6)</span></legend>
          {Object.entries(REVIEW_TAGS).map(([key, [label, good]]) => {
            const on = tags.includes(key);
            return <button key={key} type="button" aria-pressed={on} disabled={!on && tags.length >= 6}
              className={`signal-chip ${on ? (good ? 'signal-bullish' : 'signal-bearish') : ''}`}
              onClick={() => setTags(list => on ? list.filter(tag => tag !== key) : [...list, key])}>{label}</button>;
          })}
        </fieldset>
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
        ...options.trades.map(trade => ({ ...trade, key: `option:${trade.id}`, kind: `${tradeLabel(trade)} ${tradeStrikes(trade)} ${trade.expiry}`, quantity: trade.contracts }))]
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
  const unreviewed = rows.filter(row => !row.review && row.ledger_event_id);
  const filtered = rows.filter(row => (kind === 'all' || (kind === 'unreviewed' ? !row.review && row.ledger_event_id : (kind === 'options') === row.key.startsWith('option:')))
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
    <ReviewLessons rows={rows} />
    {unreviewed.length > 0 && <p className="review-nudge" role="status">
      📝 {unreviewed.length} closed trade{unreviewed.length === 1 ? ' has' : 's have'} no review yet. A one-minute review (plan followed? what happened?) builds your Lessons list.
      {' '}<button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => { setSaved(null); setReviewTrade(unreviewed[0]); }}>
        Review {unreviewed[0].ticker} ({shortDate(unreviewed[0].closed_at) || 'latest'})</button></p>}
    <div className="trade-history-toolbar">
      <input className="tool-input" type="search" aria-label="Filter by ticker" placeholder="Filter by ticker" maxLength={12}
        value={query} onChange={event => { setQuery(event.target.value); setLimit(PAGE); }} />
      {!optionsOnly && <div className="trade-history-kinds" role="group" aria-label="Trade type">
        {[['all', 'All'], ['options', 'Options'], ['stocks', 'Stocks'], ['unreviewed', `Needs review (${unreviewed.length})`]].map(([value, label]) =>
          <button key={value} type="button" className={`watchlist-tab${kind === value ? ' active' : ''}`} aria-pressed={kind === value}
            onClick={() => { setKind(value); setLimit(PAGE); }}>{label}</button>)}
      </div>}
      <span className="market-sub">{filtered.length === rows.length ? `${rows.length} trades` : `${filtered.length} of ${rows.length} trades`}</span>
      {filtered.length > 0 && <button type="button" className="btn-secondary btn-sm" aria-label={`Export ${filtered.length} trades to CSV`}
        title="Download the trades matching this filter as a spreadsheet file" onClick={() => downloadCsv(filtered)}>⬇ Export CSV</button>}
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
            <span className={`trade-badge trade-${metrics.option ? row.position : 'stock'}`}>{metrics.option ? tradeLabel(row) : 'stock'}</span>
            {row.account && row.account !== 'Default' && <span className="account-badge">{row.account}</span>}
            <span className="trade-sub">{metrics.option ? `${tradeStrikes(row)} · exp ${shortDate(row.expiry) || row.expiry} · ` : ''}{size}</span></td>
          <td className="nowrap" data-label="Dates">{opened ? <>{opened} → {closed}</> : closed || <Missing reason="Close date unavailable" />}
            {timing && <span className="trade-sub">{timing}</span>}</td>
          <td className="nowrap" data-label="Premium / price">{metrics.option && row.open_premium != null ? <>{price(row.open_premium)} → {price(row.close_premium)}
              {row.spread && <span className="trade-sub">net {row.spread.style} per share</span>}</>
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
          <td data-label="Exit reason">{EXIT_REASONS[row.review?.exit_reason] || <Missing reason="Exit reason not recorded" />}
            {row.review?.followed_plan != null && <span className="trade-sub">{row.review.followed_plan ? '✓ Followed plan' : '✗ Broke plan'}</span>}
            {row.review?.tags?.length > 0 && <span className="review-tag-list">{row.review.tags.map(tag =>
              <span key={tag} className={`signal-chip ${REVIEW_TAGS[tag]?.[1] ? 'signal-bullish' : 'signal-bearish'}`}>{REVIEW_TAGS[tag]?.[0] || tag}</span>)}</span>}</td>
          <td className="trade-pnl">{row.net_pnl != null
            ? <><strong className={pnlClass(row.net_pnl)}>{money(row.net_pnl)}</strong><span className="trade-sub">Gross {money(row.pnl)} · fees {money(row.fees)}</span></>
            : <><strong className={pnlClass(row.pnl)}>{money(row.pnl)}</strong><span className="trade-sub">Gross · no fees recorded</span></>}</td>
          <td className="closed-option-actions">
            <button className="btn-secondary btn-sm" type="button" title="Exit reason, target and review notes" aria-label={`Review ${row.ticker} trade ${row.id}`}
              disabled={busy || !row.ledger_event_id} onClick={() => { setSaved(null); setReviewTrade(row); }}>Review</button>
            {onEdit && row.is_manual && <>
              {!row.spread && <button className="btn-icon" type="button" title="Edit manual option" aria-label={`Edit ${row.ticker} option`} disabled={busy} onClick={() => onEdit(row)}>✏️</button>}
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

const EMPTY_SPREAD = { ticker: '', kind: 'bull_put', expiry: '', contracts: '1', lower: '', upper: '', open_lower: '', open_upper: '',
  close_lower: '', close_upper: '', opened_at: '', closed_at: '', fees: '0', notes: '' };

/** Log a completed two-leg vertical spread; both legs are stored together and shown as one trade. */
function ClosedSpreadForm({ onSaved }) {
  const [form, setForm] = useState(EMPTY_SPREAD);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const attempt = useRef(null);
  const set = key => event => setForm(value => ({ ...value, [key]: event.target.value }));
  const meta = SPREAD_KINDS[form.kind];
  const bull = form.kind.startsWith('bull');
  const pick = (lowerValue, upperValue) => bull ? { long: lowerValue, short: upperValue } : { long: upperValue, short: lowerValue };
  const opens = pick(form.open_lower, form.open_upper), closes = pick(form.close_lower, form.close_upper);
  const contracts = Number(form.contracts);
  const preview = spreadPreview({ kind: form.kind, lower: form.lower, upper: form.upper, longPremium: opens.long, shortPremium: opens.short, contracts });
  const closeValid = [form.close_lower, form.close_upper].every(value => value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0);
  const feesValid = form.fees !== '' && Number.isFinite(Number(form.fees)) && Number(form.fees) >= 0;
  const openFillsValid = Number(form.open_lower) > 0 && Number(form.open_upper) > 0;
  const dateError = form.opened_at && form.closed_at && form.opened_at > form.closed_at ? 'Closing date cannot precede opening date.'
    : form.closed_at && form.closed_at > today() ? 'Completed trades cannot have future dates.'
      : form.expiry && form.closed_at && form.closed_at > form.expiry ? 'Closing date cannot be after expiry.' : null;
  const valid = preview && !preview.error && openFillsValid && closeValid && feesValid && Number.isInteger(contracts) && contracts > 0
    && /^[A-Z^][A-Z0-9.^=-]{0,19}$/.test(form.ticker.trim().toUpperCase()) && form.opened_at && form.closed_at && form.expiry && !dateError;
  const gross = valid ? Math.round(((Number(closes.long) - Number(opens.long)) + (Number(opens.short) - Number(closes.short))) * contracts * 100 * 100) / 100 : null;
  const legLabel = (when, low) => `${when}: ${when === 'Opened' ? ((low === bull) ? 'bought' : 'sold') : ((low === bull) ? 'sold' : 'bought back')} ${low ? 'lower' : 'upper'} ${meta.type} ($/share)`;
  const save = async event => {
    event.preventDefault();
    if (!valid || busy) return;
    const { long_strike, short_strike } = spreadLegs(form.kind, Number(form.lower), Number(form.upper));
    const payload = { ticker: form.ticker.trim().toUpperCase(), kind: form.kind, expiry: form.expiry, contracts, long_strike, short_strike,
      long_open: Number(opens.long), short_open: Number(opens.short), long_close: Number(closes.long), short_close: Number(closes.short),
      opened_at: form.opened_at, closed_at: form.closed_at, fees: Number(form.fees), notes: form.notes };
    const signature = JSON.stringify(payload);
    if (attempt.current?.signature !== signature) attempt.current = { signature, key: crypto.randomUUID() };
    setBusy(true); setError(null);
    try {
      await logClosedSpread({ ...payload, idempotency_key: attempt.current.key });
      attempt.current = null; setForm(EMPTY_SPREAD);
      onSaved(`${payload.ticker} ${meta.label.toLowerCase()} spread recorded.`);
    } catch (reason) { setError(reason.message); }
    finally { setBusy(false); }
  };
  return <form className="closed-option-form" aria-label="Closed spread entry" onSubmit={save}>
    <fieldset disabled={busy}>
      <legend>Completed vertical spread · two legs, same expiry · Standard 100-share contracts</legend>
      <label>Ticker<input className="tool-input" required maxLength={20} value={form.ticker} onChange={set('ticker')} /></label>
      <label>Spread<select className="tool-input" value={form.kind} onChange={set('kind')}>
        {Object.entries(SPREAD_KINDS).map(([key, kind]) => <option key={key} value={key}>{kind.label} ({kind.style})</option>)}</select></label>
      <OptionDateField name="spread-expiry" label="Expiry" value={form.expiry} onChange={set('expiry')} />
      <label>Contracts<input className="tool-input" type="number" required min="1" step="1" value={form.contracts} onChange={set('contracts')} /></label>
      <label>Lower strike ($)<input className="tool-input" type="number" required min="0.000001" step="0.000001" value={form.lower} onChange={set('lower')} /></label>
      <label>Upper strike ($)<input className="tool-input" type="number" required min="0.000001" step="0.000001" value={form.upper} onChange={set('upper')} /></label>
      <OptionDateField name="spread-opened" label="Opened on" max={today()} value={form.opened_at} onChange={set('opened_at')} />
      <OptionDateField name="spread-closed" label="Closed on" max={today()} value={form.closed_at} onChange={set('closed_at')} />
      <label>{legLabel('Opened', true)}<input className="tool-input" type="number" required min="0.000001" step="0.000001" value={form.open_lower} onChange={set('open_lower')} /></label>
      <label>{legLabel('Opened', false)}<input className="tool-input" type="number" required min="0.000001" step="0.000001" value={form.open_upper} onChange={set('open_upper')} /></label>
      <label>{legLabel('Closed', true)}<input className="tool-input" type="number" required min="0" step="0.000001" value={form.close_lower} onChange={set('close_lower')} /></label>
      <label>{legLabel('Closed', false)}<input className="tool-input" type="number" required min="0" step="0.000001" value={form.close_upper} onChange={set('close_upper')} /></label>
      <label>Total fees ($, all legs)<input className="tool-input" type="number" required min="0" step="0.01" value={form.fees} onChange={set('fees')} /></label>
      <div className="closed-option-wide closed-option-notes-field">
        <label htmlFor="closed-spread-notes">Spread notes</label>
        <textarea id="closed-spread-notes" className="tool-input" rows={3} maxLength={1000} value={form.notes} onChange={set('notes')} />
      </div>
      <p className="closed-option-wide market-sub" role="status">{preview?.error ? <span className="negative">{preview.error}</span>
        : preview ? `Opened for a net ${preview.style} of $${preview.net.toFixed(2)}/share · max profit ${money(preview.maxProfit)} · max loss ${money(preview.maxLoss)}`
          : meta.hint}</p>
      <div className="closed-option-wide doctor-stats" aria-label="Spread P&L preview">
        <div><span>Gross P&L</span><strong>{money(gross)}</strong></div>
        <div><span>Recorded fees</span><strong>{feesValid ? money(Number(form.fees)) : '—'}</strong></div>
        <div><span>Net P&L</span><strong>{gross == null ? '—' : money(gross - Number(form.fees))}</strong></div>
      </div>
      <p className="closed-option-wide market-sub">For previously unrecorded trades only. Use 0 for a leg that expired worthless. Fees and notes are kept on the leg that defines the trade; delete and re-enter to correct a spread.</p>
      {dateError && <p className="closed-option-wide error-text" role="alert">{dateError}</p>}
      {error && <p className="closed-option-wide error-text" role="alert">{error}</p>}
      <button className="btn-primary btn-sm" disabled={!valid || busy} type="submit">{busy ? 'Saving...' : 'Record closed spread'}</button>
    </fieldset>
  </form>;
}

function ClosedOptionJournal() {
  const [form, setForm] = useState(EMPTY_OPTION);
  const [mode, setMode] = useState('single');
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
    const what = row.spread ? `${row.ticker} ${row.spread.label.toLowerCase()} spread (both legs)` : `${row.ticker} manual option entry`;
    if (pending.current || !window.confirm(`Delete this ${what} and its recorded fees? The audit history will be retained.`)) return;
    pending.current = true; setBusy(true); setError(null); setSaved(null);
    try {
      if (row.spread) await deleteClosedSpread(row.id);
      else await deleteClosedOption(row.id);
      if (editId === row.id) { setEditId(null); setForm(EMPTY_OPTION); setShow(false); attempt.current = null; }
      setSaved(`${row.ticker} closed ${row.spread ? 'spread' : 'option'} deleted.`); setVersion(value => value + 1);
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
    {show && editId === null && <div className="trade-history-kinds" role="group" aria-label="Entry type">
      {[['single', 'Single option'], ['spread', 'Spread (2 legs)']].map(([value, label]) =>
        <button key={value} type="button" className={`watchlist-tab${mode === value ? ' active' : ''}`} aria-pressed={mode === value}
          onClick={() => setMode(value)}>{label}</button>)}
    </div>}
    {show && mode === 'spread' && editId === null && <ClosedSpreadForm onSaved={message => { setSaved(message); setShow(false); setVersion(value => value + 1); }} />}
    {show && (mode === 'single' || editId !== null) && <form className="closed-option-form" aria-label="Closed option entry" onSubmit={save}>
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
  return <div className="journal-workspace" key={user?.id ?? user?.username ?? 'guest'}>
    <header className="journal-plan-header"><h2>Journal</h2><PlanTrade canSave={Boolean(user)} /></header>
    <JournalViews {...props} />
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
