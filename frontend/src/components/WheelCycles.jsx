import { useEffect, useRef, useState } from 'react';
import { fetchAccountingReport, recordAccountingEntry } from '../api/stockApi';

const money = value => value == null ? 'Unavailable' : new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(value);
const color = value => value > 0 ? 'positive' : value < 0 ? 'negative' : '';

export default function WheelCycles() {
  const [report, setReport] = useState(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(null);
  const [busy, setBusy] = useState(false);
  const [eventId, setEventId] = useState('');
  const [cycleName, setCycleName] = useState('');
  const [quantity, setQuantity] = useState('');
  const attempt = useRef(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let active = true;
    setError(null); setReport(null);
    fetchAccountingReport().then(data => { if (active) setReport(data); }).catch(failure => { if (active) setError(failure.message); });
    return () => { active = false; };
  }, [revision]);
  const lots = (report?.tax_lots || []).filter(lot => lot.opening_event_id).map(lot => {
    const allocated = (report.manual_entries || []).filter(entry => entry.kind === 'link' && entry.event_id === lot.opening_event_id)
      .reduce((sum, entry) => sum + Number(entry.quantity), 0);
    return { ...lot, available: Math.max(0, lot.quantity - allocated) };
  });
  const selected = lots.find(lot => String(lot.opening_event_id) === eventId);
  const option = selected?.source === 'closed_options';
  const valid = selected && cycleName.trim() && Number(quantity) > 0 && Number(quantity) <= selected.available
    && (!option || Number.isInteger(Number(quantity)));
  const save = async body => {
    if (pending.current) return;
    const signature = JSON.stringify(body);
    if (attempt.current?.signature !== signature) attempt.current = { signature,
      payload: { ...body, occurred_at: new Date().toISOString(), idempotency_key: crypto.randomUUID() } };
    pending.current = true; setBusy(true); setError(null); setSaved(null);
    try {
      await recordAccountingEntry(attempt.current.payload);
      if (!mounted.current) return;
      attempt.current = null; setQuantity(''); setEventId('');
      setSaved(body.kind === 'reverse' ? 'Allocation reversed; audit history retained.' : 'Cycle allocation saved.');
      setRevision(value => value + 1);
    } catch (failure) { if (mounted.current) setError(failure.message); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  };
  const unlink = link => {
    if (window.confirm(`Remove this ${link.ticker} allocation? The trade remains unchanged and the reversal is audited.`)) {
      save({ kind: 'reverse', event_id: link.link_id, note: 'Cycle allocation removed from Journal' });
    }
  };
  return <section className="portfolio-section wheel-cycles">
    <div className="journal-plan-header"><h3>Wheel cycles</h3><button className="btn-secondary btn-sm" disabled={busy}
      onClick={() => setRevision(value => value + 1)}>Refresh cycles</button></div>
    <p className="market-sub">Recorded realized results from explicitly linked quantities only. Stock losses can exceed collected option premiums.
      Open positions, unlinked trades, dividends, taxes and unrecorded costs are excluded; this is not a complete cycle valuation.</p>
    {error && <p className="error-text" role="alert">{error}</p>}
    {saved && <p className="positive" role="status">{saved}</p>}
    {!report && !error && <p role="status">Loading wheel cycles...</p>}
    {report && <>
      <form className="accounting-form" aria-label="Cycle allocation" onSubmit={event => {
        event.preventDefault(); if (valid) save({ kind: 'link', event_id: Number(eventId), cycle: cycleName.trim(), quantity });
      }}>
        <label>Closed trade<select required disabled={busy} value={eventId} onChange={event => { setEventId(event.target.value); setQuantity(''); }}>
          <option value="">Select trade...</option>
          {lots.filter(lot => lot.available > 0).map(lot => <option key={lot.opening_event_id} value={lot.opening_event_id}>
            {lot.ticker} {lot.source === 'closed_trades' ? 'stock' : `${lot.position} ${lot.option_type}`} #{lot.source_id} - {lot.closed_at} - {lot.available} available
          </option>)}
        </select></label>
        <label>Cycle name<input required maxLength={80} disabled={busy} list="journal-cycle-names" value={cycleName} onChange={event => setCycleName(event.target.value)} /></label>
        <datalist id="journal-cycle-names">{report.cycles.map(cycle => <option key={cycle.name} value={cycle.name} />)}</datalist>
        <label>{option ? 'Contracts to link' : 'Shares / contracts to link'}<input required type="number" disabled={busy || !selected}
          min={option ? '1' : '0.000001'} max={selected?.available} step={option ? '1' : 'any'} value={quantity} onChange={event => setQuantity(event.target.value)} /></label>
        <button className="btn-primary btn-sm" type="submit" disabled={busy || !valid}>Link to cycle</button>
      </form>
      {!lots.some(lot => lot.available > 0) && <p className="empty-state">No unallocated closed trades available.</p>}
      {!report.cycles.length && <p className="empty-state">No cycle allocations recorded.</p>}
      {report.cycles.map(cycle => <section className="journal-cycle" key={cycle.name} aria-label={`Cycle ${cycle.name}`}>
        <h4>{cycle.name}</h4>
        <div className="doctor-stats">
          <div><span>Put P&L before fees</span><strong className={color(cycle.put_pnl)}>{money(cycle.put_pnl)}</strong></div>
          <div><span>Call P&L before fees</span><strong className={color(cycle.call_pnl)}>{money(cycle.call_pnl)}</strong></div>
          <div><span>Stock P&L before fees</span><strong className={color(cycle.stock_pnl)}>{money(cycle.stock_pnl)}</strong></div>
          <div><span>Allocated fees</span><strong>{money(cycle.fees)}</strong></div>
          <div><span>Recorded net realized subtotal</span><strong className={color(cycle.realized_pnl)}>{money(cycle.realized_pnl)}</strong></div>
        </div>
        {!!cycle.open_links && <p className="income-warning">{cycle.open_links} open lot allocations are excluded from realized results.</p>}
        {!!cycle.unresolved_links && <p className="income-warning">{cycle.unresolved_links} unresolved allocations are excluded. Review deleted, closed or resized lots before relinking.</p>}
        <div className="table-scroll"><table className="market-table"><thead><tr><th>Ticker</th><th>Source</th><th>Quantity</th><th>Status</th><th>Allocation</th></tr></thead>
          <tbody>{cycle.links.map(link => <tr key={link.link_id}><td>{link.ticker}</td><td>{link.source.replaceAll('_', ' ')}</td><td>{link.quantity}</td>
            <td>{link.status || 'Unavailable'}</td><td><button className="btn-icon" title="Remove allocation" aria-label={`Remove allocation ${link.link_id}`}
              disabled={busy} onClick={() => unlink(link)}>&times;</button></td></tr>)}</tbody></table></div>
      </section>)}
    </>}
  </section>;
}