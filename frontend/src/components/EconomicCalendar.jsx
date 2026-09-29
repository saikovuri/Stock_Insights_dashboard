import { useState, useEffect } from 'react';
import { fetchEconomicCalendar } from '../api/stockApi';

const day = d => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });

export default function EconomicCalendar({ compact = false }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [all, setAll] = useState(!compact);

  useEffect(() => {
    fetchEconomicCalendar(compact ? 7 : 14).then(setData).catch(e => setError(e.message));
  }, [compact]);

  if (error) return compact ? null : <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading economic calendar…</p></div>;

  const events = data.events.filter(e => all || e.impact === 'high');
  const byDay = {};
  events.forEach(e => { (byDay[e.date] = byDay[e.date] || []).push(e); });

  return (
    <div className="card econ-cal">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>📅 Economic calendar</h3>
        <label className="market-sub">
          <input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> include medium impact
        </label>
      </div>
      {data.next_fomc && <p className="market-sub">Next Fed decision: <b>{day(data.next_fomc)}</b> · times are ET · {data.source}</p>}
      {Object.keys(byDay).length === 0 ? (
        <p className="empty-state" style={{ padding: 0 }}>No {all ? '' : 'high-impact '}US releases in this window.</p>
      ) : (
        Object.entries(byDay).map(([d, evs]) => (
          <div key={d} className="econ-day">
            <div className="econ-date">{day(d)}</div>
            <ul>
              {evs.map((e, i) => (
                <li key={i}>
                  <span className={`econ-dot ${e.impact}`} title={`${e.impact} impact`} />
                  <span className="econ-time">{e.time_et}</span>
                  <span className="econ-name">{e.event}</span>
                  <span className="market-sub">
                    {e.actual ? <>actual <b>{e.actual}</b> · </> : null}
                    {e.consensus ? <>est {e.consensus} · </> : null}
                    {e.previous ? <>prev {e.previous}</> : null}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      {!compact && <p className="ivrank-note">High-impact releases (CPI, jobs, Fed, GDP, PCE) often move the whole market and inflate option prices the day before.</p>}
    </div>
  );
}
