import { useState, useEffect } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';
import { fetchShortInterest, fetchSmartMoney } from '../api/stockApi';

const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', fontSize: '0.8rem' } };
const m = v => v == null ? '—' : v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : `${(v / 1e3).toFixed(0)}K`;
const ACTION = { new: '🆕 New position', added: '➕ Added', reduced: '➖ Reduced', sold: '❌ Sold out' };

export default function ShortAndSmartMoney({ ticker }) {
  const [si, setSi] = useState(null);
  const [siErr, setSiErr] = useState(null);
  const [sm, setSm] = useState(null);

  useEffect(() => {
    setSi(null); setSiErr(null); setSm(null);
    fetchShortInterest(ticker).then(setSi).catch(e => setSiErr(e.message));
    fetchSmartMoney(ticker).then(setSm).catch(() => setSm({ superinvestors: [], insider_buying: null }));
  }, [ticker]);

  const l = si?.latest;
  const squeeze = l && ((si.pct_of_shares ?? 0) >= 10 || (l.days_to_cover ?? 0) >= 7);
  return (
    <div className="card">
      <h3>🧲 Short interest & smart money</h3>
      {siErr && <p className="market-sub">{siErr}</p>}
      {!si && !siErr && <p className="loading-text">Loading short interest…</p>}
      {l && (
        <>
          <div className="doctor-stats">
            <div><span>Shares short ({l.date})</span><strong>{m(l.short_shares)}</strong></div>
            <div><span>% of shares outstanding</span><strong className={squeeze ? 'negative' : ''}>{si.pct_of_shares != null ? `${si.pct_of_shares}%` : '—'}</strong></div>
            <div><span>Days to cover</span><strong className={l.days_to_cover >= 7 ? 'negative' : ''}>{l.days_to_cover ?? '—'}</strong></div>
            <div><span>Change vs prior</span><strong className={l.change_pct > 0 ? 'negative' : 'positive'}>{l.change_pct != null ? `${l.change_pct > 0 ? '+' : ''}${l.change_pct}%` : '—'}</strong></div>
          </div>
          {squeeze && <p className="ivrank-verdict-desc">⚠️ Heavy short interest — good news could force a short squeeze; bad news may already be crowded.</p>}
          {si.history.length > 2 && (
            <ResponsiveContainer width="100%" height={110}>
              <BarChart data={si.history.map(h => ({ date: h.date.slice(5), short: h.short_shares }))}>
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
                <YAxis hide />
                <Tooltip {...tip} formatter={v => [m(v), 'Shares short']} />
                <Bar dataKey="short" fill="#ef5350" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
          <p className="ivrank-note">{si.source}</p>
        </>
      )}

      {sm && (
        <>
          <h4 className="sub-chart-title">Insider buying (last 30 days)</h4>
          {sm.insider_buying ? (
            <p>
              <strong className="positive">{sm.insider_buying.insiders} insider{sm.insider_buying.insiders > 1 ? 's' : ''}</strong> bought
              {' '}${m(sm.insider_buying.total_value)} on the open market (avg ${sm.insider_buying.avg_price}, last {sm.insider_buying.last_date}):
              {' '}{sm.insider_buying.names.join(', ')}
            </p>
          ) : <p className="market-sub">No notable open-market insider purchases.</p>}
          <h4 className="sub-chart-title">Superinvestors (latest 13F)</h4>
          {sm.superinvestors.length ? (
            <ul className="smart-list">
              {sm.superinvestors.map(s => (
                <li key={s.manager}>
                  <strong>{s.manager}</strong> <span className="market-sub">({s.firm})</span>
                  {s.weight != null && <> · {s.weight}% of portfolio</>}
                  {s.action && <> · {ACTION[s.action]}</>}
                  <span className="market-sub"> · as of {s.period}</span>
                </li>
              ))}
            </ul>
          ) : <p className="market-sub">Not a top holding or recent change for the tracked superinvestors.</p>}
        </>
      )}
    </div>
  );
}
