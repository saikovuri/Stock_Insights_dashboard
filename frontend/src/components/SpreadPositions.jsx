import { useState } from 'react';
import { openSpread, editSpread, closeSpread, expireSpread, deleteSpread, linkSpread, unlinkSpread } from '../api/stockApi';
import { STRUCTURES, legName, structureName, previewStructure, templateLegs } from '../spreads';
import { PayoffToggle } from './IdeaTrust';
import { RiskCheck } from './RiskGuard';

const usd = value => `${value < 0 ? '-' : ''}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const sign = l => (l.position === 'long' ? 1 : -1);
/** Per-share amount paid for one structure at the given leg premiums (a credit is negative). */
export const netPaid = legs => legs.reduce((sum, l) => sum + sign(l) * Number(l.ratio || 1) * Number(l.premium), 0);

/** One fieldset per leg: strike, expiry (calendars/diagonals) and the price fields given as [key, label, aria name]. */
export function LegsEditor({ legs, onChange, multi, prices, idPrefix }) {
  return <div className="structure-legs-editor form-field-wide">
    {legs.map((l, i) => <fieldset key={i} className="structure-leg-editor">
      <legend>Leg {i + 1} · {legName(l)}{l.hint ? ` (${l.hint})` : ''}</legend>
      <label>Strike ($)<input type="number" className="tool-input" min="0.01" step="any" aria-label={`Leg ${i + 1} strike`}
        id={`${idPrefix}-strike-${i}`} value={l.strike} onChange={event => onChange(i, { strike: event.target.value })} /></label>
      {multi && <label>Expiry<input type="date" className="tool-input" aria-label={`Leg ${i + 1} expiry`}
        value={l.expiry} onChange={event => onChange(i, { expiry: event.target.value })} /></label>}
      {prices.map(([key, label, name]) => <label key={key}>{label}<input type="number" className="tool-input" min="0" step="any"
        placeholder="Fill price" aria-label={`Leg ${i + 1} ${name}`} value={l[key]} onChange={event => onChange(i, { [key]: event.target.value })} /></label>)}
    </fieldset>)}
  </div>;
}

export function PreviewLine({ preview, kind }) {
  if (preview?.error) return <span className="negative">{preview.error}</span>;
  if (!preview) return <span className="market-sub">{STRUCTURES[kind]?.hint} Enter every leg&apos;s strike and fill price.</span>;
  return <>Net {preview.style} <strong>${preview.net.toFixed(2)}</strong>/share
    {' '}· max profit <strong className="positive">{preview.maxProfit == null ? 'depends on volatility' : usd(preview.maxProfit)}</strong>
    {' '}· max loss <strong className="negative">{preview.multi ? `about ${usd(preview.maxLoss)}` : usd(preview.maxLoss)}</strong>
    {preview.breakevens.length > 0 && <> · breakeven{preview.breakevens.length > 1 ? 's' : ''} {preview.breakevens.map(b => `$${b.toFixed(2)}`).join(' and ')}</>}
    {preview.collateral > 0 && <> · reserves {usd(preview.collateral)} of cash</>}
    {preview.multi && <span className="market-sub"> · max loss assumes the later leg keeps at least its intrinsic value</span>}</>;
}

const toPayloadLeg = l => ({ position: l.position, option_type: l.option_type, strike: Number(l.strike), expiry: l.expiry,
  premium: Number(l.premium), ratio: Number(l.ratio), ...(l.id ? { id: l.id } : {}) });

/** Open a structure (inside the option form) or, given `spread`, correct an open one. */
export function StructureBuilder({ ticker, account, spread, onDone, onCancel, setMsg }) {
  const editing = Boolean(spread);
  const initialLegs = editing ? [...spread.legs].sort((a, b) => a.expiry.localeCompare(b.expiry) || a.strike - b.strike)
    .map(l => ({ ...l, strike: String(l.strike), premium: String(l.premium) })) : templateLegs('bull_put');
  const [kind, setKind] = useState(editing ? spread.kind : 'bull_put');
  const [units, setUnits] = useState(editing ? spread.contracts : 1);
  const [expiry, setExpiry] = useState(editing ? initialLegs[0].expiry : '');
  const [legs, setLegs] = useState(initialLegs);
  const [busy, setBusy] = useState(false);
  const [risk, setRisk] = useState(null);
  const multi = editing ? spread.multi_expiry : Boolean(STRUCTURES[kind].multi);
  const effective = legs.map(l => ({ ...l, expiry: multi ? l.expiry : expiry }));
  const preview = previewStructure(effective, units, editing ? null : kind);
  const count = Number(units);
  const valid = preview && !preview.error && (ticker || '').trim() && Number.isInteger(count) && count > 0;
  const submit = async event => {
    event?.preventDefault();
    if (!valid || busy) return;
    const symbol = ticker.trim().toUpperCase();
    const payload = { ticker: symbol, contracts: count, legs: effective.map(toPayloadLeg), ...(editing ? {} : { kind }), ...(account ? { account } : {}) };
    setBusy(true);
    try {
      const result = editing ? await editSpread(spread.spread_id, payload) : await openSpread(payload);
      setMsg(`${editing ? 'Updated' : 'Opened'} ${count} ${symbol} ${structureName(result).toLowerCase()} ${result.strikes} for a net ${result.style} of $${result.net_open.toFixed(2)}`);
      if (!editing) { setLegs(templateLegs(kind)); setExpiry(''); setUnits(1); }
      onDone();
    } catch (error) { setMsg(error.message); }
    finally { setBusy(false); }
  };
  const fields = <>
    {!editing && <div className="form-field form-field-wide">
      <label htmlFor="spread-kind">Structure</label>
      <select id="spread-kind" value={kind} onChange={event => { setKind(event.target.value); setLegs(templateLegs(event.target.value)); }}>
        {Object.entries(STRUCTURES).map(([key, s]) => <option key={key} value={key}>{structureName(s)}{s.style ? ` (${s.style})` : ''}</option>)}
      </select>
    </div>}
    <div className="form-field"><label htmlFor={editing ? 'spread-edit-contracts' : 'spread-contracts'}>Contracts</label>
      <input id={editing ? 'spread-edit-contracts' : 'spread-contracts'} type="number" min={1} step={1} value={units} onChange={event => setUnits(event.target.value)} /></div>
    {!multi && <div className="form-field"><label htmlFor={editing ? 'spread-edit-expiry' : 'spread-expiry'}>Expiry Date</label>
      <input id={editing ? 'spread-edit-expiry' : 'spread-expiry'} type="date" value={expiry} onChange={event => setExpiry(event.target.value)} /></div>}
    <LegsEditor legs={legs} multi={multi} idPrefix={editing ? 'spread-edit' : 'spread'} prices={[['premium', 'Fill ($/share)', 'fill']]}
      onChange={(i, patch) => setLegs(list => list.map((l, j) => (j === i ? { ...l, ...patch } : l)))} />
    <p className="form-field-wide spread-preview" role="status"><PreviewLine preview={preview} kind={kind} /></p>
    {valid && <div className="form-field-wide spread-preview"><PayoffToggle multiExpiry={multi} spot={spread?.current_price}
      legs={effective.map(l => ({ ...l, strike: Number(l.strike), ratio: Number(l.ratio) }))} net={netPaid(effective)} units={count} /></div>}
  </>;
  if (!editing) return <>{fields}
    <RiskCheck onResult={setRisk} proposal={valid ? { kind: 'structure', ticker: ticker.trim().toUpperCase(), contracts: count,
      legs: effective.map(toPayloadLeg), ...(account ? { account } : {}) } : null} />
    <div className="form-actions">
    <button className="btn-primary" onClick={submit} disabled={!valid || busy}>{busy ? 'Opening…' : risk?.warnings?.length ? 'Open spread anyway' : 'Open spread'}</button></div></>;
  return <form className="card roll-panel spread-close" id="spread-edit-panel" onSubmit={submit} aria-label="Edit spread">
    <div className="ivrank-header">
      <h3 style={{ margin: 0 }}>Edit {spread.ticker} {structureName(spread).toLowerCase()}</h3>
      <button type="button" className="btn-icon" title="Cancel" onClick={onCancel}>✕</button>
    </div>
    <div className="portfolio-form labeled-form">
      {fields}
      <p className="form-field-wide market-sub">Corrects the recorded legs in place (each keeps its open date). To change the structure type, delete it and open a new one.</p>
      <div className="form-actions"><button type="submit" className="btn-primary" disabled={!valid || busy}>{busy ? 'Saving…' : 'Save changes'}</button></div>
    </div>
  </form>;
}

const ZONES = { max_profit: ['Max profit', 'positive'], max_loss: ['Max loss', 'negative'], between: ['Between strikes', ''] };

export function SpreadRow({ spread, account, open, onToggle, onClose, onEdit, onChanged, setMsg }) {
  const [confirm, setConfirm] = useState(false);
  const [label, labelClass] = ZONES[spread.zone] || [spread.current_price == null ? 'Unknown' : '—', ''];
  const name = structureName(spread);
  const settle = async () => {
    if (!window.confirm(`Settle the expired legs of the ${spread.ticker} ${name.toLowerCase()} at their value from the expiry-day close? `
      + 'If a sold leg finished in the money it may have been assigned instead: open the legs and use 📥 on that leg.')) return;
    try {
      const result = await expireSpread(spread.spread_id);
      setMsg(`Settled at the $${result.settle_price} close: ${usd(result.pnl)}${result.remaining_legs ? ` · ${result.remaining_legs} later leg(s) still open` : ''}`);
      onChanged();
    } catch (error) { setMsg(error.message); }
  };
  const remove = async () => {
    try { await deleteSpread(spread.spread_id); setMsg('Spread deleted'); onChanged(); }
    catch (error) { setMsg(error.message); }
  };
  const unlink = async () => {
    if (!window.confirm(`Treat the legs of this ${name.toLowerCase()} as separate options? Nothing is closed.`)) return;
    try { await unlinkSpread(spread.spread_id); setMsg('Legs unlinked'); onChanged(); }
    catch (error) { setMsg(error.message); }
  };
  return <tr className="spread-row">
    <td><button type="button" className="btn-icon spread-toggle" aria-expanded={open} title={open ? 'Hide legs' : 'Show the legs'}
      onClick={onToggle}>{open ? '▾' : '▸'}</button><strong>{spread.ticker}</strong>
      {!account && spread.account && spread.account !== 'Default' && <span className="account-badge">{spread.account}</span>}</td>
    <td className={spread.style === 'credit' ? 'positive' : ''} data-label="Type">{name.toUpperCase()}</td>
    <td data-label="Side"><span className={`side-badge side-${spread.style === 'credit' ? 'short' : 'long'}`}>{spread.style.toUpperCase()}</span></td>
    <td data-label="Strikes">{spread.strikes}</td>
    <td data-label="Stock">{spread.current_price == null ? 'Unavailable' : `$${spread.current_price.toFixed(2)}`}</td>
    <td className={labelClass} data-label="Status"><span className="moneyness-badge"
      title={spread.breakevens?.length ? `Breakeven ${spread.breakevens.map(b => `$${b}`).join(' and ')}` : undefined}>{label}</span></td>
    <td className="nowrap" data-label="Expiry">{spread.expiry}<span className="dte-badge" title="Days to the nearest expiry">{spread.dte}d</span></td>
    <td data-label="Qty">{spread.contracts}</td>
    <td data-label={`Net ${spread.style}`} title={`Max profit ${spread.max_profit == null ? 'depends on volatility' : usd(spread.max_profit)} · max loss ${usd(spread.max_loss)}`}>${spread.net_open.toFixed(2)}</td>
    <td data-label="Net mark" title="Value of the legs at their midpoints (credit structures: cost to close)">{spread.net_mark == null ? 'Unavailable' : `$${spread.net_mark.toFixed(2)}`}</td>
    <td data-label="IV">—</td>
    <td className={spread.pnl == null ? '' : spread.pnl >= 0 ? 'positive' : 'negative'} data-label="P/L">
      {spread.pnl == null ? `Unavailable · risk ${usd(spread.max_loss)}` : `${usd(spread.pnl)} (${spread.pnl_pct_of_risk ?? 0}% of ${usd(spread.max_loss)} risk)`}</td>
    <td className="action-cell">
      <button className="btn-icon" title="Close every leg" aria-label={`Close ${spread.ticker} spread`} onClick={() => onClose(spread)}>×</button>
      <button className="btn-icon" title="Edit strikes, fills or size" aria-label={`Edit ${spread.ticker} spread`} onClick={() => onEdit(spread)}>✏️</button>
      <button className="btn-icon" title="Unlink: treat the legs as separate options" aria-label={`Unlink ${spread.ticker} spread`} onClick={unlink}>🔗</button>
      {spread.expired && <button className="btn-icon" title="Expired: settle the expired legs at the expiry-day close" aria-label={`Settle ${spread.ticker} spread`}
        onClick={settle}>⌛</button>}
      {confirm ? <>
        <button className="btn-icon btn-confirm-del" title="Confirm delete (every leg, no close recorded)" onClick={remove}>✔</button>
        <button className="btn-icon" title="Cancel" onClick={() => setConfirm(false)}>✕</button>
      </> : <button className="btn-icon" title="Delete spread entry (every leg)" aria-label={`Delete ${spread.ticker} spread`} onClick={() => setConfirm(true)}>🗑️</button>}
    </td>
  </tr>;
}

export function SpreadClosePanel({ spread, onDone, onCancel, setMsg }) {
  const [prices, setPrices] = useState({});
  const [contracts, setContracts] = useState(spread.contracts);
  const [busy, setBusy] = useState(false);
  const qty = Number(contracts);
  const filled = spread.legs.every(l => prices[l.id] !== undefined && prices[l.id] !== '' && Number.isFinite(Number(prices[l.id])) && Number(prices[l.id]) >= 0);
  const valid = filled && Number.isInteger(qty) && qty > 0 && qty <= spread.contracts;
  const credit = spread.style === 'credit';
  const raw = filled ? spread.legs.reduce((sum, l) => sum + sign(l) * l.ratio * Number(prices[l.id]), 0) : null;
  const closeNet = raw == null ? null : credit ? -raw : raw;
  const pnl = valid ? (credit ? spread.net_open - closeNet : closeNet - spread.net_open) * 100 * qty : null;
  const submit = async event => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    try {
      const result = await closeSpread(spread.spread_id, { prices: spread.legs.map(l => ({ id: l.id, premium: Number(prices[l.id]) })), contracts: qty });
      setMsg(`Closed ${qty} ${spread.ticker} ${structureName(spread).toLowerCase()} ${spread.strikes}: ${usd(result.pnl)}`);
      onDone();
    } catch (error) { setMsg(error.message); }
    finally { setBusy(false); }
  };
  return <form className="card roll-panel spread-close" id="spread-close-panel" onSubmit={submit} aria-label="Close spread">
    <div className="ivrank-header">
      <h3 style={{ margin: 0 }}>Close {spread.ticker} {structureName(spread).toLowerCase()} {spread.strikes}</h3>
      <button type="button" className="btn-icon" title="Cancel" onClick={onCancel}>✕</button>
    </div>
    <div className="portfolio-form labeled-form">
      {spread.legs.map(l => <div className="form-field" key={l.id}>
        <label htmlFor={`spread-close-${l.id}`}>{l.position === 'short' ? 'Buy back' : 'Sell'} {l.ratio > 1 ? `${l.ratio}× ` : ''}${l.strike} {l.option_type}{spread.multi_expiry ? ` ${l.expiry}` : ''} at ($/share)</label>
        <input id={`spread-close-${l.id}`} type="number" min={0} step="any" required value={prices[l.id] ?? ''}
          onChange={event => setPrices(value => ({ ...value, [l.id]: event.target.value }))} />
      </div>)}
      <div className="form-field"><label htmlFor="spread-close-qty">Contracts (of {spread.contracts})</label>
        <input id="spread-close-qty" type="number" min={1} max={spread.contracts} step={1} value={contracts} onChange={event => setContracts(event.target.value)} /></div>
      <p className="form-field-wide spread-preview" role="status">
        {valid ? <>Net {credit ? 'debit to close' : 'credit received'} ${closeNet.toFixed(2)}/share · P/L <strong className={pnl >= 0 ? 'positive' : 'negative'}>{usd(pnl)}</strong>
          {spread.net_mark != null && <span className="market-sub"> · current mark ${spread.net_mark.toFixed(2)}</span>}</>
          : <span className="market-sub">Enter each leg&apos;s fill. Every leg closes together; a partial close keeps the rest of the structure open.</span>}
      </p>
      <div className="form-actions"><button type="submit" className="btn-primary" disabled={!valid || busy}>{busy ? 'Closing…' : 'Close spread'}</button></div>
    </div>
  </form>;
}

/** Open legs that look like one structure (often from a broker import), with a button to link them. */
export function LinkSuggestions({ suggestions, onLinked, setMsg }) {
  const [busy, setBusy] = useState(null);
  if (!suggestions?.length) return null;
  const link = async item => {
    setBusy(item.option_ids.join());
    try {
      const result = await linkSpread(item.option_ids);
      setMsg(`Linked ${item.ticker} ${item.strikes} as a ${structureName(result).toLowerCase()}`);
      onLinked();
    } catch (error) { setMsg(error.message); }
    finally { setBusy(null); }
  };
  return <ul className="link-suggestions" aria-label="Possible spreads">
    {suggestions.map(item => <li key={item.option_ids.join()}>
      🔗 <strong>{item.ticker}</strong> {item.strikes}: these {item.option_ids.length} legs look like {item.contracts > 1 ? `${item.contracts} ` : 'a '}
      {structureName(STRUCTURES[item.kind] || item).toLowerCase()}{item.contracts > 1 ? 's' : ''}.{' '}
      <button type="button" className="btn-secondary btn-sm" disabled={busy === item.option_ids.join()} onClick={() => link(item)}>Link as spread</button>
    </li>)}
  </ul>;
}
