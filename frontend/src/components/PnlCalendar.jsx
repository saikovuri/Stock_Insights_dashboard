import { useMemo, useRef, useState } from 'react';

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
const pad = n => String(n).padStart(2, '0');
const indexOf = ({ y, m }) => y * 12 + m;
const fromIndex = i => ({ y: Math.floor(i / 12), m: i % 12 });
const localToday = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

export const compactMoney = v => {
  const a = Math.abs(v);
  const s = a >= 1e6 ? `${(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${(a / 1e3).toFixed(1)}K` : a.toFixed(0);
  return `${v < 0 ? '-' : '+'}$${s}`;
};
const fullMoney = v => `${v < 0 ? '-' : ''}$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const tone = v => v > 0 ? 'positive' : v < 0 ? 'negative' : '';

/** Realized P&L per closing day: net of recorded fees when available, otherwise gross. */
export function dailyPnl(rows) {
  const days = new Map();
  rows.forEach(row => {
    const day = String(row.closed_at ?? '').slice(0, 10);
    const value = Number(row.net_pnl ?? row.pnl);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(value)) return;
    const entry = days.get(day) || { pnl: 0, trades: [] };
    entry.pnl += value;
    entry.trades.push(row);
    days.set(day, entry);
  });
  return days;
}

export default function PnlCalendar({ rows }) {
  const days = useMemo(() => dailyPnl(rows), [rows]);
  const today = localToday();
  const current = { y: Number(today.slice(0, 4)), m: Number(today.slice(5, 7)) - 1 };
  const [cursor, setCursor] = useState(current);
  const [selected, setSelected] = useState(null);
  const touchX = useRef(null);

  const firstDay = [...days.keys()].sort()[0];
  const earliest = firstDay ? Math.min(indexOf({ y: Number(firstDay.slice(0, 4)), m: Number(firstDay.slice(5, 7)) - 1 }), indexOf(current)) : indexOf(current);
  const canPrev = indexOf(cursor) > earliest;
  const canNext = indexOf(cursor) < indexOf(current);
  const shift = step => {
    const next = indexOf(cursor) + step;
    if (next < earliest || next > indexOf(current)) return;
    setSelected(null);
    setCursor(fromIndex(next));
  };

  const prefix = `${cursor.y}-${pad(cursor.m + 1)}`;
  const lead = new Date(cursor.y, cursor.m, 1).getDay();
  const length = new Date(cursor.y, cursor.m + 1, 0).getDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length }, (_, i) => `${prefix}-${pad(i + 1)}`)];
  while (cells.length % 7) cells.push(null);
  const weeks = Array.from({ length: cells.length / 7 }, (_, i) => cells.slice(i * 7, i * 7 + 7));

  const traded = cells.filter(day => day && days.has(day)).map(day => [day, days.get(day)]);
  const total = traded.reduce((sum, [, entry]) => sum + entry.pnl, 0);
  const green = traded.filter(([, entry]) => entry.pnl > 0).length;
  const red = traded.filter(([, entry]) => entry.pnl < 0).length;
  const largest = Math.max(0, ...traded.map(([, entry]) => Math.abs(entry.pnl)));
  const best = traded.reduce((top, item) => !top || item[1].pnl > top[1].pnl ? item : top, null);
  const worst = traded.reduce((low, item) => !low || item[1].pnl < low[1].pnl ? item : low, null);
  const shade = v => {
    if (!v || !largest) return undefined;
    const alpha = (0.18 + 0.5 * Math.abs(v) / largest).toFixed(2);
    return { background: v > 0 ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})` };
  };
  const detail = selected && days.get(selected);
  const label = `${MONTHS[cursor.m]} ${cursor.y}`;

  return <div className="journal-breakdown pnl-calendar" id="pnl-calendar">
    <div className="pnl-calendar-head">
      <h4>Daily realized P&L</h4>
      <div className="pnl-calendar-nav">
        <button type="button" className="btn-icon" aria-label="Previous month" disabled={!canPrev} onClick={() => shift(-1)}>‹</button>
        <strong aria-live="polite">{label}</strong>
        <button type="button" className="btn-icon" aria-label="Next month" disabled={!canNext} onClick={() => shift(1)}>›</button>
      </div>
    </div>
    <p className="market-sub">
      Month: <strong className={tone(total)}>{traded.length ? fullMoney(total) : '$0.00'}</strong>
      {' · '}{green} green / {red} red day{red === 1 ? '' : 's'}
      {best && best[1].pnl > 0 && <> · best day {MONTHS[cursor.m].slice(0, 3)} {Number(best[0].slice(8))} <span className="positive">{compactMoney(best[1].pnl)}</span></>}
      {worst && worst[1].pnl < 0 && <> · worst day {MONTHS[cursor.m].slice(0, 3)} {Number(worst[0].slice(8))} <span className="negative">{compactMoney(worst[1].pnl)}</span></>}
    </p>
    <div className="pnl-calendar-grid" role="group" aria-label={`Realized P&L calendar, ${label}`}
      onTouchStart={event => { touchX.current = event.touches[0].clientX; }}
      onTouchEnd={event => {
        if (touchX.current == null) return;
        const dx = event.changedTouches[0].clientX - touchX.current;
        touchX.current = null;
        if (dx > 50) shift(-1); else if (dx < -50) shift(1);
      }}>
      {WEEKDAYS.map(day => <div key={day} className="pnl-calendar-weekday" aria-hidden="true">{day}</div>)}
      <div className="pnl-calendar-weekday" aria-hidden="true">Week</div>
      {weeks.map((week, i) => {
        const weekTotal = week.reduce((sum, day) => sum + (day && days.has(day) ? days.get(day).pnl : 0), 0);
        const weekTraded = week.some(day => day && days.has(day));
        return [
          ...week.map((day, j) => {
            if (!day) return <div key={`blank-${i}-${j}`} className="pnl-calendar-day blank" />;
            const entry = days.get(day);
            const name = `${MONTHS[cursor.m]} ${Number(day.slice(8))}`;
            return <button key={day} type="button" style={shade(entry?.pnl)} disabled={!entry}
              className={`pnl-calendar-day${day === today ? ' today' : ''}${selected === day ? ' selected' : ''}`}
              aria-pressed={entry ? selected === day : undefined}
              aria-label={entry ? `${name}: ${fullMoney(entry.pnl)} realized across ${entry.trades.length} closed trade${entry.trades.length === 1 ? '' : 's'}` : `${name}: no closed trades`}
              onClick={() => setSelected(selected === day ? null : day)}>
              <span className="pnl-calendar-date">{Number(day.slice(8))}</span>
              {entry && <span className="pnl-calendar-amount">{compactMoney(entry.pnl)}</span>}
              {entry && <span className="pnl-calendar-count">{entry.trades.length} trade{entry.trades.length === 1 ? '' : 's'}</span>}
            </button>;
          }),
          <div key={`week-${i}`} className={`pnl-calendar-week ${tone(weekTotal)}`} aria-label={weekTraded ? `Week total ${fullMoney(weekTotal)}` : undefined}>
            {weekTraded ? compactMoney(weekTotal) : ''}
          </div>,
        ];
      })}
    </div>
    {detail && <div className="pnl-calendar-detail">
      <strong>{MONTHS[cursor.m]} {Number(selected.slice(8))}: <span className={tone(detail.pnl)}>{fullMoney(detail.pnl)}</span></strong>
      <ul>{detail.trades.map(row => <li key={row.key}>
        {row.ticker} <span className="market-sub">{row.kind}</span>{' '}
        <span className={tone(Number(row.net_pnl ?? row.pnl))}>{fullMoney(Number(row.net_pnl ?? row.pnl))}</span>
      </li>)}</ul>
    </div>}
    <p className="market-sub">Each closing record counts on its close date, net of recorded fees where available (gross otherwise).
      Follows the ticker and trade-type filters above. Swipe or use ‹ › to change months.</p>
  </div>;
}
