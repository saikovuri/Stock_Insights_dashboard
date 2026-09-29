import { useState, useEffect } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid, Legend,
} from 'recharts';
import { fetchLongTerm } from '../api/stockApi';
import DividendHistory from './DividendHistory';

const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--border)', fontSize: '0.8rem' } };
const axis = { tick: { fontSize: 11, fill: 'var(--text-muted)' }, interval: 0 };

function big(v) {
  if (v == null) return '—';
  const a = Math.abs(v);
  const s = a >= 1e12 ? `${(a / 1e12).toFixed(2)}T` : a >= 1e9 ? `${(a / 1e9).toFixed(1)}B` : a >= 1e6 ? `${(a / 1e6).toFixed(0)}M` : a.toFixed(0);
  return `${v < 0 ? '-' : ''}$${s}`;
}

function pct(v) {
  return v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`;
}

function PeBand({ band }) {
  if (!band) return <p className="market-sub">Not enough profitable years for a P/E history.</p>;
  const lo = Math.min(band.min, band.now), hi = Math.max(band.max, band.now);
  const pos = v => `${((v - lo) / (hi - lo || 1)) * 100}%`;
  return (
    <div className="pe-band">
      <div className="pe-band-track">
        <div className="pe-band-range" style={{ left: pos(band.min), width: `calc(${pos(band.max)} - ${pos(band.min)})` }} />
        <div className="pe-band-median" style={{ left: pos(band.median) }} title={`Median ${band.median}`} />
        <div className="pe-band-now" style={{ left: pos(band.now) }} title={`Now ${band.now}`} />
      </div>
      <div className="ivrank-bar-labels">
        <span>Low {band.min}</span><span>Median {band.median} · <b>Now {band.now}</b></span><span>High {band.max}</span>
      </div>
      <p className="market-sub">
        Today's P/E is higher than {band.percentile}% of its fiscal-year-end readings over the past decade.
      </p>
    </div>
  );
}

export default function LongTermView({ ticker }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setData(null); setError(null);
    fetchLongTerm(ticker).then(setData).catch(e => setError(e.message));
  }, [ticker]);

  if (error) return (
    <>
      <div className="card"><h3>🌳 Long-term view</h3><p className="empty-state" style={{ padding: 0 }}>{error}</p></div>
      <DividendHistory ticker={ticker} />
    </>
  );
  if (!data) return <div className="card"><p className="loading-text">Loading 10 years of SEC filings…</p></div>;

  const years = data.years.map(y => ({
    ...y,
    revB: y.revenue != null ? +(y.revenue / 1e9).toFixed(2) : null,
    niB: y.net_income != null ? +(y.net_income / 1e9).toFixed(2) : null,
    fcfB: y.fcf != null ? +(y.fcf / 1e9).toFixed(2) : null,
    sharesB: y.shares != null ? +(y.shares / 1e9).toFixed(3) : null,
  }));
  const g = data.growth, v = data.valuation, p = data.piotroski, d = data.dividends;

  return (
    <div className="long-term">
      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>🌳 Long-term view</h3>
          <span className="market-sub">{data.source} · FY ends {data.fiscal_year_end}</span>
        </div>
        {data.flags.length > 0 && (
          <div className="ai-brief-signals">
            {data.flags.map((f, i) => <span key={i} className={`signal-chip ${f.type === 'good' ? 'signal-bullish' : 'signal-bearish'}`}>{f.text}</span>)}
          </div>
        )}
        <div className="doctor-stats">
          <div><span>Revenue growth 3y / 5y / 10y</span><strong>{pct(g.revenue_3y)} / {pct(g.revenue_5y)} / {pct(g.revenue_10y)}</strong></div>
          <div><span>FCF growth 5y</span><strong>{pct(g.fcf_5y)}</strong></div>
          <div><span>EPS growth 5y</span><strong>{pct(g.eps_5y)}</strong></div>
          <div><span>Share count 5y</span><strong className={g.shares_5y <= 0 ? 'positive' : 'negative'}>{pct(g.shares_5y)}/yr</strong></div>
        </div>
      </div>

      <div className="two-column">
        <div className="card">
          <h4 className="sub-chart-title">Revenue, net income & free cash flow ($B)</h4>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={years}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="year" {...axis} /><YAxis {...axis} />
              <Tooltip {...tip} /><Legend />
              <Bar dataKey="revB" name="Revenue" fill="#7c6cf0" />
              <Bar dataKey="niB" name="Net income" fill="#26a69a" />
              <Bar dataKey="fcfB" name="Free cash flow" fill="#ffb300" />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="card">
          <h4 className="sub-chart-title">Margins & returns (%)</h4>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={years}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="year" {...axis} /><YAxis {...axis} />
              <Tooltip {...tip} /><Legend />
              <Line dataKey="gross_margin" name="Gross" stroke="#29b6f6" dot={false} connectNulls />
              <Line dataKey="operating_margin" name="Operating" stroke="#7c6cf0" dot={false} connectNulls />
              <Line dataKey="fcf_margin" name="FCF" stroke="#ffb300" dot={false} connectNulls />
              <Line dataKey="roic" name="ROIC" stroke="#26a69a" strokeDasharray="4 3" dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="two-column">
        <div className="card">
          <h3>💰 Valuation</h3>
          <h4 className="sub-chart-title">P/E vs its own history</h4>
          <PeBand band={v.pe_band} />
          <div className="doctor-stats">
            <div><span>FCF yield</span><strong>{v.fcf_yield_pct != null ? `${v.fcf_yield_pct}%` : '—'}</strong></div>
            <div><span>Growth priced in</span><strong>{v.implied_fcf_growth != null ? `${v.implied_fcf_growth}%/yr` : '—'}</strong></div>
            <div><span>Growth delivered (5y)</span><strong>{v.historical_growth != null ? `${v.historical_growth}%/yr` : '—'}</strong></div>
          </div>
          <p className="ivrank-verdict-desc">{v.verdict}</p>
          <p className="market-sub">Reverse DCF: {v.assumptions}. It asks "what must happen to justify today's price?" rather than guessing a fair value.</p>
        </div>

        <div className="card">
          <h3>🛡️ Quality & safety</h3>
          {p && (
            <>
              <div className="ivrank-header">
                <span>Piotroski F-score</span>
                <span className={`rs-badge ${p.score >= 7 ? 'rs-strong' : p.score >= 4 ? 'rs-mid' : 'rs-weak'}`}>{p.score}/9</span>
              </div>
              <ul className="piotroski">
                {p.checks.map(c => <li key={c.label} className={c.pass ? 'positive' : 'negative'}>{c.pass ? '✓' : '✗'} <span>{c.label}</span></li>)}
              </ul>
            </>
          )}
          {data.altman && (
            <p>Altman Z-score <b>{data.altman.z}</b> — <span className={data.altman.zone === 'safe' ? 'positive' : data.altman.zone === 'distress' ? 'negative' : ''}>{data.altman.zone} zone</span> (bankruptcy-risk model; above 3 is safe)</p>
          )}
          <h4 className="sub-chart-title">Diluted shares (B) — falling = buybacks</h4>
          <ResponsiveContainer width="100%" height={120}>
            <LineChart data={years}>
              <XAxis dataKey="year" {...axis} /><YAxis {...axis} domain={['auto', 'auto']} />
              <Tooltip {...tip} />
              <Line dataKey="sharesB" name="Shares (B)" stroke="#ec407a" dot={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>
      <DividendHistory ticker={ticker} profile={d} />
      <p className="ivrank-note">Figures from annual 10-K filings (as reported, split-adjusted per share). Educational only — not financial advice. Revenue {big(years.at(-1)?.revenue)} in the latest fiscal year.</p>
    </div>
  );
}
