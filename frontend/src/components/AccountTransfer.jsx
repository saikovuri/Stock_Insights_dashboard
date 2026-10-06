import { useEffect, useRef, useState } from 'react';
import { useAuth } from '../AuthContext';
import { exportAccountData, previewAccountImport, importAccountData } from '../api/stockApi';

const CATEGORIES = { holdings: 'Open stock lots', options: 'Open option lots', closed_trades: 'Closed stock trades',
  closed_options: 'Closed options', journal: 'Manual Journal entries', transactions: 'Transactions', watchlist: 'Watchlist symbols' };
const MAX_BYTES = 10 * 1024 * 1024;

export default function AccountTransfer({ onImported }) {
  const { user } = useAuth();
  return user ? <TransferControls key={user.id ?? user.username} user={user} onImported={onImported} /> : null;
}

function TransferControls({ user, onImported }) {
  const [show, setShow] = useState(false);
  const [bundle, setBundle] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const dialog = useRef(null);
  const pending = useRef(false);
  const mounted = useRef(true);
  const destination = user.display_name || user.username || `Account ${user.id}`;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (show && !dialog.current.open) dialog.current.showModal(); }, [show]);
  const close = () => {
    if (pending.current) return;
    setShow(false); setBundle(null); setPreview(null); setConfirmed(false); setError('');
  };
  const download = async () => {
    if (pending.current) return;
    pending.current = true; setBusy('export'); setError(''); setStatus('');
    try {
      const data = await exportAccountData();
      if (!mounted.current) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = `stockpilot-account-transfer-${new Date().toISOString().slice(0, 10)}.json`;
      anchor.click(); URL.revokeObjectURL(url);
      setStatus('Export downloaded. The source account is unchanged. This file contains private financial data.');
    } catch (failure) { if (mounted.current) setError(failure.message); }
    finally { pending.current = false; if (mounted.current) setBusy(''); }
  };
  const selectFile = async event => {
    const file = event.target.files?.[0];
    if (!file || pending.current) return;
    pending.current = true; setBusy('preview'); setError(''); setStatus(''); setPreview(null); setBundle(null); setConfirmed(false);
    try {
      if (file.size > MAX_BYTES) throw new Error('Transfer file exceeds 10 MB.');
      let data;
      try { data = JSON.parse(await file.text()); }
      catch { throw new Error('Choose a valid StockPilot transfer JSON file.'); }
      if (!mounted.current) return;
      const result = await previewAccountImport(data);
      if (mounted.current) { setBundle(data); setPreview(result); }
    } catch (failure) { if (mounted.current) setError(failure.message); }
    finally { pending.current = false; if (mounted.current) setBusy(''); }
  };
  const submit = async event => {
    event.preventDefault();
    if (pending.current || !confirmed || !bundle || !preview || preview.already_imported) return;
    pending.current = true; setBusy('import'); setError('');
    try {
      const result = await importAccountData(bundle);
      if (!mounted.current) return;
      setShow(false); setBundle(null); setPreview(null); setConfirmed(false);
      setStatus(result.already_imported ? 'This export was already imported. No duplicate records were added.'
        : `Portfolio and Journal imported into ${destination}. Existing records and the source account were kept.`);
      onImported?.();
    } catch (failure) { if (mounted.current) setError(failure.message); }
    finally { pending.current = false; if (mounted.current) setBusy(''); }
  };
  return <section className="account-transfer" aria-label="Account transfer">
    <div className="accounting-toolbar">
      <button className="btn-secondary btn-sm" disabled={!!busy} onClick={download}><span aria-hidden="true">&#8595; </span>{busy === 'export' ? 'Exporting...' : 'Export to another account'}</button>
      <button className="btn-secondary btn-sm" disabled={!!busy} aria-haspopup="dialog" onClick={() => { setError(''); setStatus(''); setShow(true); }}><span aria-hidden="true">&#8593; </span>Import from another account</button>
    </div>
    {status && <p role="status">{status}</p>}
    {error && !show && <p className="error-text" role="alert">{error}</p>}
    {show && <dialog ref={dialog} className="journal-plan-dialog account-transfer-dialog" aria-labelledby="account-transfer-title"
      onCancel={event => { event.preventDefault(); close(); }}>
      <div className="journal-plan-header"><h3 id="account-transfer-title">Import from another account</h3>
        <button className="btn-secondary btn-sm" disabled={!!busy} onClick={close}>Cancel</button></div>
      <p>Destination: <strong>{destination}</strong> (account {user.id})</p>
      <p className="market-sub">Adds portfolio, Journal, recorded fees, reviews, wheel links and watchlist data. Existing trades are not matched or overwritten. The source account is not deleted.</p>
      <p className="market-sub">Combining financial histories makes time-weighted return unavailable: separate account valuations are not consolidated NAV.</p>
      <label className="transfer-file">Transfer file (.json)<input type="file" accept=".json,application/json" disabled={!!busy} onChange={selectFile} /></label>
      {busy === 'preview' && <p role="status">Validating transfer file...</p>}
      {error && <p className="error-text" role="alert">{error}</p>}
      {preview && <>
        <p>From <strong>{preview.source_name}</strong> (account {preview.source_user_id})</p>
        <div className="table-scroll"><table className="market-table"><thead><tr><th>Records</th><th>Incoming</th><th>Already here</th></tr></thead>
          <tbody>{Object.entries(CATEGORIES).map(([key, label]) => <tr key={key}><td>{label}</td><td>{preview.counts[key] ?? 0}</td><td>{preview.destination_counts[key] ?? 0}</td></tr>)}</tbody></table></div>
        <p className="market-sub">{preview.ledger_events} ledger events. Existing watchlist symbols are kept once. Conflicting cycle names receive an import suffix.</p>
        {preview.already_imported ? <p role="status">This export was already imported. No duplicate records will be added.</p> : <form onSubmit={submit}>
          <label className="transfer-confirm"><input type="checkbox" checked={confirmed} disabled={!!busy} onChange={event => setConfirmed(event.target.checked)} />
            I confirm adding these records to {destination}. I have checked for overlapping trades.</label>
          <button className="btn-primary" type="submit" disabled={!!busy || !confirmed}>{busy === 'import' ? 'Importing...' : 'Confirm import'}</button>
        </form>}
      </>}
      <p className="market-sub">Signed StockPilot exports only, maximum 10 MB. Files are not encrypted. Passwords, sessions, alerts and account settings are not transferred. A changed export from an already imported source is blocked to prevent duplicate trades.</p>
    </dialog>}
  </section>;
}