import { useMemo, useState } from 'react';

const FIELDS = [
  { id: 'ticker', label: 'Ticker', type: 'text', placeholder: 'AAPL' },
  { id: 'thesis', label: 'Thesis (1 sentence)', type: 'textarea', placeholder: 'Why this, why now, why this expiry?' },
  { id: 'horizon', label: 'Time horizon', type: 'select', options: ['Same day (0DTE)', '1–7 days', '1–4 weeks', '1–3 months', '> 3 months'] },
  { id: 'iv_check', label: 'IV rank check', type: 'select', options: ['Low (favors long options)', 'Mid', 'High (avoid buying naked options)', 'Did not check'] },
  { id: 'earnings', label: 'Earnings before expiry?', type: 'select', options: ['No', 'Yes — that is the trade', 'Yes — accidental (re-think)'] },
  { id: 'structure', label: 'Structure', type: 'select', options: ['Long call', 'Long put', 'Debit spread', 'Credit spread', 'Other'] },
  { id: 'max_loss', label: 'Max loss ($)', type: 'number', placeholder: 'Total premium at risk' },
  { id: 'max_loss_pct', label: 'Max loss as % of account', type: 'number', placeholder: 'Stay ≤ 1–2%' },
  { id: 'exit_up', label: 'Exit plan if RIGHT', type: 'textarea', placeholder: 'e.g. Scale out 50% at +50%, trail rest' },
  { id: 'exit_down', label: 'Exit plan if WRONG', type: 'textarea', placeholder: 'e.g. Cut at –40% or if thesis breaks' },
  { id: 'invalidation', label: 'What would invalidate the thesis?', type: 'textarea', placeholder: 'Specific event/level — not "if it goes down"' },
];

const REQUIRED = FIELDS.map(f => f.id);

export default function PreTradeChecklist() {
  const [vals, setVals] = useState({});
  const [submitted, setSubmitted] = useState(false);

  const set = (id, v) => {
    setVals(prev => ({ ...prev, [id]: v }));
    setSubmitted(false);
  };

  const missing = useMemo(
    () => REQUIRED.filter(id => !String(vals[id] ?? '').trim()),
    [vals],
  );

  const loss = Number(vals.max_loss);
  const lossPct = Number(vals.max_loss_pct);
  const validRisk = Number.isFinite(loss) && loss > 0 && Number.isFinite(lossPct) && lossPct > 0 && lossPct <= 100;
  const invalidRisk = !missing.includes('max_loss') && !missing.includes('max_loss_pct') && !validRisk;
  const validTicker = /^[A-Z^][A-Z0-9.^=-]{0,14}$/.test((vals.ticker || '').trim().toUpperCase());
  const sizingWarning = Number.isFinite(lossPct) && lossPct > 2;
  const ivWarning = vals.iv_check === 'High (avoid buying naked options)' && (vals.structure === 'Long call' || vals.structure === 'Long put');
  const earningsWarning = vals.earnings === 'Yes — accidental (re-think)';
  const noCheck = vals.iv_check === 'Did not check';

  const ready = missing.length === 0 && validRisk && validTicker && !sizingWarning && !ivWarning && !earningsWarning && !noCheck;

  const reset = () => {
    setVals({});
    setSubmitted(false);
  };

  return (
    <div className="tool-card">
      <h3>✅ Pre-Trade Checklist</h3>
      <p className="tool-desc">
        Self-reported plan. Market data, account balances and trade suitability are not independently verified.
      </p>

      <div className="tool-form">
        {FIELDS.map(f => (
          <div key={f.id} className="tool-row">
            <label htmlFor={`plan-${f.id}`}>{f.label}</label>
            {f.type === 'textarea' ? (
              <textarea
                id={`plan-${f.id}`}
                className="tool-input"
                rows={2}
                placeholder={f.placeholder}
                value={vals[f.id] || ''}
                onChange={e => set(f.id, e.target.value)}
              />
            ) : f.type === 'select' ? (
              <select
                id={`plan-${f.id}`}
                className="tool-input"
                value={vals[f.id] || ''}
                onChange={e => set(f.id, e.target.value)}
              >
                <option value="">Select…</option>
                {f.options.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                id={`plan-${f.id}`}
                className="tool-input"
                type={f.type}
                min={f.type === 'number' ? '0' : undefined}
                max={f.id === 'max_loss_pct' ? '100' : undefined}
                step={f.type === 'number' ? 'any' : undefined}
                placeholder={f.placeholder}
                value={vals[f.id] || ''}
                onChange={e => set(f.id, e.target.value)}
              />
            )}
          </div>
        ))}
      </div>

      {submitted && (
        <div className="tool-result" role="status">
          {missing.length > 0 && (
            <div className="checklist-block bad">
              <strong>Checklist incomplete.</strong> {missing.length} field{missing.length === 1 ? '' : 's'} missing.
            </div>
          )}
          {!missing.includes('ticker') && !validTicker && (
            <div className="checklist-block bad"><strong>Invalid ticker format.</strong> Enter a symbol, not a company name.</div>
          )}
          {invalidRisk && (
            <div className="checklist-block bad"><strong>Invalid risk values.</strong> Enter a positive, finite maximum loss and an account percentage above zero and no greater than 100.</div>
          )}
          {sizingWarning && (
            <div className="checklist-block bad">
              <strong>Risk guideline exceeded.</strong> Reported risk of {lossPct}% exceeds this checklist's 2% guideline.
            </div>
          )}
          {ivWarning && (
            <div className="checklist-block bad">
              <strong>High IV + long option.</strong> Your answers indicate high IV with a long call or put. Review premium and volatility exposure against current quotes.
            </div>
          )}
          {earningsWarning && (
            <div className="checklist-block bad">
              <strong>Accidental earnings.</strong> You reported an unplanned earnings overlap. Verify the date and review event risk.
            </div>
          )}
          {noCheck && (
            <div className="checklist-block warn">
              <strong>No IV check.</strong> Your IV assessment is still missing.
            </div>
          )}
          {ready && (
            <div className="checklist-block good">
              <strong>Checklist complete.</strong> Your answers meet the checklist rules. This is not trade qualification or a recommendation; market data and account risk remain unverified.
            </div>
          )}
        </div>
      )}

      <div className="checklist-actions">
        <button className="btn-primary btn-sm" onClick={() => setSubmitted(true)}>Review checklist</button>
        <button className="btn-secondary btn-sm" onClick={reset}>Reset</button>
      </div>
    </div>
  );
}
