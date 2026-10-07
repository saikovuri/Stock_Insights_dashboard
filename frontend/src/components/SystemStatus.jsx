import { useEffect, useRef, useState } from 'react';
import { fetchSystemStatus } from '../api/stockApi';

const ago = iso => {
  if (!iso) return 'never';
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return minutes < 1 ? 'just now' : minutes < 60 ? `${minutes} min ago` : minutes < 2880 ? `${Math.round(minutes / 60)} h ago` : `${Math.round(minutes / 1440)} days ago`;
};
const uptime = s => s < 3600 ? `${Math.round(s / 60)} min` : s < 172800 ? `${Math.round(s / 3600)} h` : `${Math.round(s / 86400)} days`;
const JOBS = { alert_scan: 'Alert scan', position_checks: 'Option position checks', rule_checks: 'Trading rule checks', morning_briefing: 'Morning briefing',
  setup_scan: 'Setup scanner', account_value_snapshot: 'Account value snapshot' };
const mark = ok => ok === true ? <span className="positive" aria-label="OK">●</span>
  : ok === false ? <span className="negative" aria-label="Problem">●</span> : <span className="market-sub" aria-label="Optional, off">○</span>;

export default function SystemStatus({ onClose }) {
  const dialog = useRef(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    dialog.current.showModal();
    fetchSystemStatus().then(setData).catch(e => setError(e.message));
  }, []);
  const rows = data ? [...data.checks, ...data.config] : [];
  const scheduler = data?.scheduler;
  const stale = scheduler?.enabled && scheduler.last_tick && Date.now() - new Date(scheduler.last_tick).getTime() > 5 * 60000;

  return <dialog ref={dialog} className="journal-plan-dialog system-status" aria-labelledby="system-status-title"
    onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="journal-plan-header">
      <h2 id="system-status-title">System status</h2>
      <button className="btn-secondary btn-sm" onClick={onClose}>Close</button>
    </div>
    {error && <p className="error-text" role="alert">{error}</p>}
    {!data && !error && <p className="loading-text">Checking services…</p>}
    {data && <>
      <p className="market-sub">Version {data.version || 'unknown'} · running {uptime(data.uptime_seconds)} · Python {data.python} · checked {ago(data.generated_at)}</p>
      <table className="market-table" aria-label="Services">
        <tbody>{rows.map(row => <tr key={row.name} className="no-click">
          <td>{mark(row.ok)} {row.name}</td><td>{row.detail}{row.ms != null && <span className="market-sub"> · {row.ms} ms</span>}</td>
        </tr>)}</tbody>
      </table>
      <h3>Background jobs</h3>
      {!scheduler.enabled ? <p className="market-sub">Scheduler is off (SCHEDULER_ENABLED=0): no alert scans, briefings or position checks.</p> : <>
        <p className={stale ? 'negative' : 'market-sub'}>Scheduler heartbeat: {ago(scheduler.last_tick)}{stale ? ' — the background loop seems stuck; restart the backend.' : ''}</p>
        <table className="market-table" aria-label="Background jobs">
          <tbody>{Object.entries(JOBS).map(([key, label]) => <tr key={key} className="no-click"><td>{label}</td><td>{ago(scheduler.jobs[key])}</td></tr>)}</tbody>
        </table>
        {scheduler.last_error && <p className="negative">Last scheduler error: {scheduler.last_error.error} ({ago(scheduler.last_error.at)}). Details are in the server log.</p>}
        <p className="market-sub">Jobs run on market days: alert scans every few minutes while the market is open, option checks after 10:15 ET, the briefing each weekday morning, the setup scan after the close. &quot;never&quot; is normal right after a restart or on weekends.</p>
      </>}
      <p className="market-sub">Provider checks are cached for 5 minutes. Secret values are never shown. See setup.md → Troubleshooting for fixes.</p>
    </>}
  </dialog>;
}
