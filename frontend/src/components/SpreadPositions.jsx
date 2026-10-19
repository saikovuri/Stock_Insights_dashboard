import { useState } from 'react';
import { openSpread, closeSpread, expireSpread, deleteSpread } from '../api/stockApi';
import { SPREAD_KINDS, spreadLegs, spreadPreview, spreadName } from '../spreads';

const usd = value => `${value < 0 ? '-' : ''}$${Math.abs(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const EMPTY = { kind: 'bull_put', lower: '', upper: '', lowerPrice: '', upperPrice: '', contracts: 1 };

/** Fields for opening a two-leg spread; ticker and expiry come from the shared option form. */
export function SpreadFields({ ticker, expiry, account, onOpened, setMsg }) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const meta = SPREAD_KINDS[form.kind];
  const bull = form.kind.startsWith('bull');
  const set = key => event => setForm(value => ({ ...value, [key]: event.target.value }));
  const prices = bull ? { longPremium: form.lowerPrice, shortPremium: form.upperPrice } : { longPremium: form.upperPrice, shortPremium: form.lowerPrice };
  const preview = spreadPreview({ kind: form.kind, lower: form.lower, upper: form.upper, contracts: form.contracts, ...prices });
  const contracts = Number(form.contracts);
  const valid = preview && !preview.error && ticker.trim() && expiry && Number.isInteger(contracts) && contracts > 0;
  const legLabel = (low) => `${(low === bull) ? 'Buy' : 'Sell'} ${low ? 'lower' : 'upper'} ${meta.type} ($/share)`;
  const submit = async () => {
    if (!valid || busy) return;
    const { long_strike, short_strike } = spreadLegs(form.kind, Number(form.lower), Number(form.upper));
    setBusy(true);
    try {
      const result = await openSpread({ ticker: ticker.trim().toUpperCase(), kind: form.kind, expiry, long_strike, short_strike,
        long_premium: Number(prices.longPremium), short_premium: Number(prices.shortPremium), contracts, ...(account ? { account } : {}) });
      setMsg(`Opened ${contracts} ${result.label.toLowerCase()} spread on ${ticker.trim().toUpperCase()} for a net ${result.style} of $${result.net_open.toFixed(2)}`);
      setForm(EMPTY);
      onOpened();
    } catch (error) { setMsg(error.message); }
    finally { setBusy(false); }
  };
  return <>
    <div className="form-field form-field-wide">
      <label htmlFor="spread-kind">Spread</label>
      <select id="spread-kind" value={form.kind} onChange={set('kind')}>
        {Object.entries(SPREAD_KINDS).map(([key, kind]) => <option key={key} value={key}>{kind.label} ({kind.style})</option>)}
      </select>
    </div>
    <div className="form-field"><label htmlFor="spread-lower">Lower strike ($)</label>
      <input id="spread-lower" type="number" min={0.01} step="any" value={form.lower} onChange={set('lower')} /></div>
    <div className="form-field"><label htmlFor="spread-upper">Upper strike ($)</label>
      <input id="spread-upper" type="number" min={0.01} step="any" value={form.upper} onChange={set('upper')} /></div>
    <div className="form-field"><label htmlFor="spread-lower-price">{legLabel(true)}</label>
      <input id="spread-lower-price" type="number" min={0} step="any" placeholder="Fill price" value={form.lowerPrice} onChange={set('lowerPrice')} /></div>
    <div className="form-field"><label htmlFor="spread-upper-price">{legLabel(false)}</label>
      <input id="spread-upper-price" type="number" min={0} step="any" placeholder="Fill price" value={form.upperPrice} onChange={set('upperPrice')} /></div>
    <div className="form-field"><label htmlFor="spread-contracts">Contracts</label>
      <input id="spread-contracts" type="number" min={1} step={1} value={form.contracts} onChange={set('contracts')} /></div>
    <p className="form-field-wide spread-preview" role="status">
      {preview?.error ? <span className="negative">{preview.error}</span>
        : preview ? <>Net {preview.style} <strong>${preview.net.toFixed(2)}</strong>/share · max profit <strong className="positive">{usd(preview.maxProfit)}</strong>
          {' '}· max loss <strong className="negative">{usd(preview.maxLoss)}</strong> · breakeven ${preview.breakeven.toFixed(2)}
          {preview.collateral > 0 && <> · reserves {usd(preview.collateral)} of cash</>}</>
          : <span className="market-sub">{meta.hint} Enter both strikes and each leg&apos;s fill price.</span>}
    </p>
    <div className="form-actions">
      <button className="btn-primary" onClick={submit} disabled={!valid || busy}>{busy ? 'Opening…' : 'Open spread'}</button>
    </div>
  </>;
}

/** Where the stock sits relative to the strikes, from the spread's point of view. */
function zone(spread) {
  const price = spread.current_price;
  if (price == null) return ['Unknown', ''];
  const lower = Math.min(spread.long_strike, spread.short_strike), upper = Math.max(spread.long_strike, spread.short_strike);
  const bull = spread.kind.startsWith('bull');
  if (price >= upper) return bull ? ['Max profit', 'positive'] : ['Max loss', 'negative'];
  if (price <= lower) return bull ? ['Max loss', 'negative'] : ['Max profit', 'positive'];
  return ['Between strikes', ''];
}

export function SpreadRow({ spread, account, open, onToggle, onClose, onChanged, setMsg }) {
  const [confirm, setConfirm] = useState(false);
  const [label, labelClass] = zone(spread);
  const settle = async () => {
    if (!window.confirm(`Settle the ${spread.ticker} ${spreadName(spread)} spread at its value from the ${spread.expiry} close? `
      + 'If the stock closed between the strikes, the short leg was probably assigned instead: open the legs and use 📥 on the short leg.')) return;
    try {
      const result = await expireSpread(spread.spread_id);
      setMsg(`Settled at the $${result.settle_price} close: ${usd(result.pnl)}`);
      onChanged();
    } catch (error) { setMsg(error.message); }
  };
  const remove = async () => {
    try { await deleteSpread(spread.spread_id); setMsg('Spread deleted'); onChanged(); }
    catch (error) { setMsg(error.message); }
  };
  return <tr className="spread-row">
    <td><button type="button" className="btn-icon spread-toggle" aria-expanded={open} title={open ? 'Hide legs' : 'Show the two legs'}
      onClick={onToggle}>{open ? '▾' : '▸'}</button><strong>{spread.ticker}</strong>
      {!account && spread.account && spread.account !== 'Default' && <span className="account-badge">{spread.account}</span>}</td>
    <td className={spread.kind.startsWith('bull') ? 'positive' : 'negative'} data-label="Type">{spread.label.toUpperCase()} SPREAD</td>
    <td data-label="Side"><span className={`side-badge side-${spread.style === 'credit' ? 'short' : 'long'}`}>{spread.style.toUpperCase()}</span></td>
    <td data-label="Strikes" title="Long strike / short strike">${spread.long_strike}/${spread.short_strike}</td>
    <td data-label="Stock">{spread.current_price == null ? 'Unavailable' : `$${spread.current_price.toFixed(2)}`}</td>
    <td className={labelClass} data-label="Status"><span className="moneyness-badge" title={`Breakeven $${spread.breakeven}`}>{label}</span></td>
    <td className="nowrap" data-label="Expiry">{spread.expiry}<span className="dte-badge" title="Days to expiry">{spread.dte}d</span></td>
    <td data-label="Qty">{spread.contracts}</td>
    <td data-label={`Net ${spread.style}`} title={`Max profit ${usd(spread.max_profit)} · max loss ${usd(spread.max_loss)}`}>${spread.net_open.toFixed(2)}</td>
    <td data-label="Net mark" title="Long leg mark minus short leg mark (credit spreads: cost to close)">{spread.net_mark == null ? 'Unavailable' : `$${spread.net_mark.toFixed(2)}`}</td>
    <td data-label="IV" title={`Max loss ${usd(spread.max_loss)} · max profit ${usd(spread.max_profit)}`}>—</td>
    <td className={spread.pnl == null ? '' : spread.pnl >= 0 ? 'positive' : 'negative'} data-label="P/L">
      {spread.pnl == null ? `Unavailable · risk ${usd(spread.max_loss)}` : `${usd(spread.pnl)} (${spread.pnl_pct_of_risk ?? 0}% of ${usd(spread.max_loss)} risk)`}</td>
    <td className="action-cell">
      <button className="btn-icon" title="Close both legs" aria-label={`Close ${spread.ticker} spread`} onClick={() => onClose(spread)}>×</button>
      {spread.expired && <button className="btn-icon" title="Expired: settle both legs at the expiry-day close" aria-label={`Settle ${spread.ticker} spread`}
        onClick={settle}>⌛</button>}
      {confirm ? <>
        <button className="btn-icon btn-confirm-del" title="Confirm delete (both legs, no close recorded)" onClick={remove}>✔</button>
        <button className="btn-icon" title="Cancel" onClick={() => setConfirm(false)}>✕</button>
      </> : <button className="btn-icon" title="Delete spread entry (both legs)" aria-label={`Delete ${spread.ticker} spread`} onClick={() => setConfirm(true)}>🗑️</button>}
    </td>
  </tr>;
}

export function SpreadClosePanel({ spread, onDone, onCancel, setMsg }) {
  const [longPrice, setLongPrice] = useState('');
  const [shortPrice, setShortPrice] = useState('');
  const [contracts, setContracts] = useState(spread.contracts);
  const [busy, setBusy] = useState(false);
  const qty = Number(contracts);
  const ok = value => value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0;
  const valid = ok(longPrice) && ok(shortPrice) && Number.isInteger(qty) && qty > 0 && qty <= spread.contracts;
  const credit = spread.style === 'credit';
  const closeNet = valid ? (credit ? Number(shortPrice) - Number(longPrice) : Number(longPrice) - Number(shortPrice)) : null;
  const pnl = valid ? (credit ? spread.net_open - closeNet : closeNet - spread.net_open) * 100 * qty : null;
  const submit = async event => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    try {
      const result = await closeSpread(spread.spread_id, { long_premium: Number(longPrice), short_premium: Number(shortPrice), contracts: qty });
      setMsg(`Closed ${qty} ${spread.ticker} ${spreadName(spread)} spread${qty === 1 ? '' : 's'}: ${usd(result.pnl)}`);
      onDone();
    } catch (error) { setMsg(error.message); }
    finally { setBusy(false); }
  };
  return <form className="card roll-panel spread-close" id="spread-close-panel" onSubmit={submit} aria-label="Close spread">
    <div className="ivrank-header">
      <h3 style={{ margin: 0 }}>Close {spread.ticker} {spreadName(spread)} · {spread.expiry}</h3>
      <button type="button" className="btn-icon" title="Cancel" onClick={onCancel}>✕</button>
    </div>
    <div className="portfolio-form labeled-form">
      <div className="form-field"><label htmlFor="spread-close-short">Buy back ${spread.short_strike} {spread.type} at ($/share)</label>
        <input id="spread-close-short" type="number" min={0} step="any" required value={shortPrice} onChange={event => setShortPrice(event.target.value)} /></div>
      <div className="form-field"><label htmlFor="spread-close-long">Sell ${spread.long_strike} {spread.type} at ($/share)</label>
        <input id="spread-close-long" type="number" min={0} step="any" required value={longPrice} onChange={event => setLongPrice(event.target.value)} /></div>
      <div className="form-field"><label htmlFor="spread-close-qty">Contracts (of {spread.contracts})</label>
        <input id="spread-close-qty" type="number" min={1} max={spread.contracts} step={1} value={contracts} onChange={event => setContracts(event.target.value)} /></div>
      <p className="form-field-wide spread-preview" role="status">
        {valid ? <>Net {credit ? 'debit to close' : 'credit received'} ${closeNet.toFixed(2)}/share · P/L <strong className={pnl >= 0 ? 'positive' : 'negative'}>{usd(pnl)}</strong>
          {spread.net_mark != null && <span className="market-sub"> · current mark ${spread.net_mark.toFixed(2)}</span>}</>
          : <span className="market-sub">Enter each leg&apos;s fill. Both legs close together; a partial close keeps the rest of the spread open.</span>}
      </p>
      <div className="form-actions"><button type="submit" className="btn-primary" disabled={!valid || busy}>{busy ? 'Closing…' : 'Close spread'}</button></div>
    </div>
  </form>;
}
