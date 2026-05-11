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

  const lossPct = parseFloat(vals.max_loss_pct);
  const sizingWarning = !isNaN(lossPct) && lossPct > 2;
  const ivWarning = vals.iv_check === 'High (avoid buying naked options)' && (vals.structure === 'Long call' || vals.structure === 'Long put');
  const earningsWarning = vals.earnings === 'Yes — accidental (re-think)';
  const noCheck = vals.iv_check === 'Did not check';

  const ready = missing.length === 0 && !sizingWarning && !ivWarning && !earningsWarning && !noCheck;

  const reset = () => {
    setVals({});
    setSubmitted(false);
  };

  return (
    <div className="tool-card">
      <h3>✅ Pre-Trade Checklist</h3>
      <p className="tool-desc">
        Fill every field before you submit an options order. The point is friction — most blowups are
        trades you would not have placed if you had to write the bear case down first.
      </p>

      <div className="tool-form">
        {FIELDS.map(f => (
          <div key={f.id} className="tool-row">
            <label>{f.label}</label>
            {f.type === 'textarea' ? (
              <textarea
                className="tool-input"
                rows={2}
                placeholder={f.placeholder}
                value={vals[f.id] || ''}
                onChange={e => set(f.id, e.target.value)}
              />
            ) : f.type === 'select' ? (
              <select
                className="tool-input"
                value={vals[f.id] || ''}
                onChange={e => set(f.id, e.target.value)}
              >
                <option value="">Select…</option>
                {f.options.map(o => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input
                className="tool-input"
                type={f.type}
                placeholder={f.placeholder}
                value={vals[f.id] || ''}
                onChange={e => set(f.id, e.target.value)}
              />
            )}
          </div>
        ))}
      </div>

      {submitted && (
        <div className="tool-result">
          {missing.length > 0 && (
            <div className="checklist-block bad">
              <strong>Stop.</strong> {missing.length} field{missing.length === 1 ? '' : 's'} missing.
              You should not place this trade until you can fill them in.
            </div>
          )}
          {sizingWarning && (
            <div className="checklist-block bad">
              <strong>Position too large.</strong> {lossPct}% of account on a single options trade is past the standard 1–2% rule. This is the #1 cause of account blowups.
            </div>
          )}
          {ivWarning && (
            <div className="checklist-block bad">
              <strong>High IV + long option.</strong> You are buying expensive premium. Consider a debit spread instead — same direction, less theta and vega risk.
            </div>
          )}
          {earningsWarning && (
            <div className="checklist-block bad">
              <strong>Accidental earnings.</strong> Expiry crosses earnings but you did not plan for it. IV crush after the print is the #1 unforced loss for retail.
            </div>
          )}
          {noCheck && (
            <div className="checklist-block warn">
              <strong>No IV check.</strong> Open the IV Rank panel for this ticker before you decide. Long options into high IV is the most common losing setup.
            </div>
          )}
          {ready && (
            <div className="checklist-block good">
              <strong>Cleared.</strong> Every check passed. Place the trade and log it in your journal.
            </div>
          )}
        </div>
      )}

      <div className="checklist-actions">
        <button className="btn-primary btn-sm" onClick={() => setSubmitted(true)}>Run Check</button>
        <button className="btn-secondary btn-sm" onClick={reset}>Reset</button>
      </div>
    </div>
  );
}
