import { useState, useEffect } from 'react';
import { useAuth } from '../AuthContext';
import { fetchEarningsIntel, fetchEarningsRelease } from '../api/stockApi';

function fmtDate(d) {
  return new Date(d + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

const TONE = { positive: ['🟢', 'positive'], mixed: ['🟡', ''], negative: ['🔴', 'negative'] };

function ReleaseSummary({ ticker }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { setData(null); setError(null); }, [ticker]);

  const load = async () => {
    setLoading(true); setError(null);
    try { setData(await fetchEarningsRelease(ticker)); } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  if (!data) {
    return (
      <div className="er-release">
        <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? 'Reading the press release…' : '🤖 Summarize latest earnings press release'}
        </button>
        {error && <p className="error-text">{error}</p>}
      </div>
    );
  }
  const [icon, cls] = TONE[data.tone] || ['⚪', ''];
  return (
    <div className="er-release">
      <div className="ivrank-header">
        <strong>{data.period || 'Latest quarter'} press release</strong>
        <span className={`ai-brief-badge ${cls}`}>{icon} {data.tone}</span>
      </div>
      <p className="ai-brief-summary">{data.headline}</p>
      {data.key_numbers?.length > 0 && (
        <div className="doctor-stats">
          {data.key_numbers.map((n, i) => (
            <div key={i}><span>{n.label}</span><strong>{n.value}</strong>{n.change && <small className="market-sub">{n.change}</small>}</div>
          ))}
        </div>
      )}
      {data.guidance && <p><b>Guidance:</b> {data.guidance}</p>}
      <div className="bull-bear-grid">
        {data.positives?.length > 0 && <div className="bull-col bull-bear-col"><div className="bull-bear-col-header">Positives</div><ul>{data.positives.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
        {data.negatives?.length > 0 && <div className="bear-col bull-bear-col"><div className="bull-bear-col-header">Concerns</div><ul>{data.negatives.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
      </div>
      <p className="ai-brief-meta">Filed {data.filed} · <a href={data.url} target="_blank" rel="noopener noreferrer">Read on SEC.gov</a> · AI summary, verify key numbers</p>
    </div>
  );
}

export default function EarningsIntel({ ticker }) {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null); setError(null);
    fetchEarningsIntel(ticker).then(setData).catch(e => setError(e.message));
  }, [ticker]);

  if (error) return <div className="card"><h3>📅 Earnings</h3><p className="empty-state" style={{ padding: 0 }}>{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading earnings history…</p></div>;

  const s = data.stats;
  const maxMove = Math.max(...data.history.map(h => Math.abs(h.move_pct)), 1);

  return (
    <div className="card earnings-intel">
      <h3>📅 Earnings Intelligence</h3>

      {data.upcoming && (
        <div className="er-upcoming">
          <div><span className="market-sub">Next report</span><strong>{fmtDate(data.upcoming.date)}</strong><span className="market-sub">{data.upcoming.timing}</span></div>
          {data.upcoming.eps_estimate != null && <div><span className="market-sub">EPS estimate</span><strong>${data.upcoming.eps_estimate}</strong></div>}
          {data.implied && <div><span className="market-sub">Options pricing</span><strong>±{data.implied.move_pct}%</strong><span className="market-sub">${data.implied.low} – ${data.implied.high}</span></div>}
          {s.avg_move_pct != null && <div><span className="market-sub">Avg actual move</span><strong>±{s.avg_move_pct}%</strong><span className="market-sub">max {s.max_move_pct}%</span></div>}
        </div>
      )}
      {data.verdict && <p className="ivrank-verdict-desc">{data.verdict}</p>}

      {s.count > 0 && (
        <p className="market-sub">
          Last {s.count} reports: beat estimates {s.beat_rate_pct}% of the time · stock rose after {s.up_pct}% of reports
          {s.avg_move_on_beat != null && ` · average reaction after a beat ${s.avg_move_on_beat > 0 ? '+' : ''}${s.avg_move_on_beat}%`}
        </p>
      )}

      {data.history.length > 0 && (
        <table className="market-table er-table">
          <thead><tr><th>Date</th><th>EPS est → actual</th><th>Surprise</th><th>Next-day move</th></tr></thead>
          <tbody>
            {data.history.map(h => (
              <tr key={h.date}>
                <td>{fmtDate(h.date)}<div className="market-sub">{h.timing}</div></td>
                <td>{h.eps_estimate != null ? `$${h.eps_estimate}` : '—'} → <b>${h.eps_actual}</b></td>
                <td className={h.surprise_pct > 0 ? 'positive' : h.surprise_pct < 0 ? 'negative' : ''}>{h.surprise_pct != null ? `${h.surprise_pct > 0 ? '+' : ''}${h.surprise_pct}%` : '—'}</td>
                <td>
                  <div className="er-move">
                    <div className={`er-bar ${h.move_pct >= 0 ? 'er-up' : 'er-down'}`} style={{ width: `${Math.abs(h.move_pct) / maxMove * 100}%` }} />
                    <span className={h.move_pct >= 0 ? 'positive' : 'negative'}>{h.move_pct > 0 ? '+' : ''}{h.move_pct}%</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {user && <ReleaseSummary ticker={ticker} />}
    </div>
  );
}
