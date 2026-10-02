import { useState, useEffect } from 'react';
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ReferenceLine } from 'recharts';
import { fetchEarningsMoves } from '../api/stockApi';

const fmtDate = d => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
const VERDICT = {
  rich: ['Options price a bigger move than usual', 'ivrank-high',
    'The market expects more than this stock typically delivers — historically an edge for premium sellers (defined risk only).'],
  fair: ['Priced about right', 'ivrank-mid', 'The implied move is in line with past reactions.'],
  cheap: ['Options price a smaller move than usual', 'ivrank-low',
    'Past reactions were bigger than what options price now — selling premium through this report is riskier than it looks.'],
};

export default function EarningsMoves({ ticker }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (!ticker) return;
    setD(null); setErr(null);
    fetchEarningsMoves(ticker).then(setD).catch(e => setErr(e.message));
  }, [ticker]);
  if (err) return null;
  if (!d) return <div className="card"><p className="loading-text">Loading earnings reactions…</p></div>;
  if (!d.count) return null;
  const v = d.verdict && VERDICT[d.verdict];
  const chart = [...d.moves].reverse().map(m => ({ ...m, label: fmtDate(m.date) }));
  return (
    <div className="card">
      <div className="ivrank-header">
        <h3 style={{ margin: 0 }}>🎯 Earnings moves: priced vs actual</h3>
        {v && <span className={`ivrank-badge ${v[1]}`}>{v[0]}</span>}
      </div>
      <div className="doctor-stats">
        <div><span>Average move (last {d.count})</span><strong>±{d.avg_abs_move_pct}%</strong></div>
        <div><span>Biggest</span><strong>±{d.max_abs_move_pct}%</strong></div>
        <div><span>Up / down</span><strong>{d.up_count} / {d.count - d.up_count}</strong></div>
        {d.implied_move_pct != null && (
          <div><span>Options price for {new Date(d.next_earnings + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}{d.next_confirmed ? '' : ' (est.)'}</span>
            <strong>±{d.implied_move_pct}%</strong></div>
        )}
      </div>
      {v && <p className="structures-intro">{v[2]} (implied ÷ average = {d.ratio}×)</p>}
      <ResponsiveContainer width="100%" height={170}>
        <BarChart data={chart}>
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} />
          <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickFormatter={x => `${x}%`} width={40} />
          <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: '0.8rem' }}
            formatter={(x, _, p) => [`${x > 0 ? '+' : ''}${x}%${p.payload.implied_pct ? ` (priced ±${p.payload.implied_pct}%)` : ''}`, p.payload.timing]} />
          <ReferenceLine y={0} stroke="var(--text-muted)" />
          {d.implied_move_pct != null && <ReferenceLine y={d.implied_move_pct} stroke="#ffb300" strokeDasharray="4 3" />}
          {d.implied_move_pct != null && <ReferenceLine y={-d.implied_move_pct} stroke="#ffb300" strokeDasharray="4 3" />}
          <Bar dataKey="move_pct" radius={[3, 3, 0, 0]}>
            {chart.map((m, i) => <Cell key={i} fill={m.move_pct >= 0 ? '#66bb6a' : '#ef5350'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="ivrank-note">{d.note}{d.implied_move_pct != null && ' Dashed lines = the move priced now.'}</p>
    </div>
  );
}
