import { useState, useEffect, useMemo } from 'react';
import { fetchScanner } from '../api/stockApi';
import Tip from './Tip';
import { usePortfolioFit, FitBadge } from './PortfolioFit';

const FIT_ROWS = 25;

const TAG_CLS = { breakout: 'signal-bullish', pullback: 'signal-bullish', golden_cross: 'signal-bullish', squeeze: '', oversold: 'signal-bearish' };
const SHORT = { breakout: 'Breakout', pullback: 'Pullback', squeeze: 'Squeeze', oversold: 'Oversold', golden_cross: 'Golden X' };

const EXPLAIN = {
  breakout: {
    what: 'Price just closed at a new 52-week high on at least 1.5× normal volume.',
    why: 'Stocks breaking to new highs on heavy buying often keep going — nobody above is waiting to sell at break-even.',
    how: 'Buy near the breakout level. The idea is wrong if price falls back below it. Avoid chasing if it is already far above.',
  },
  pullback: {
    what: 'A stock in an uptrend (above its 50- and 200-day averages) has dipped back to its 21-day EMA, with RSI cooled to 40–60.',
    why: 'Buying a dip in a strong trend gets a better price than chasing, with a nearby level to measure risk from.',
    how: 'Enter near the 21-day EMA; stop below the recent swing low. Best when volume is light on the dip and picks up on the bounce.',
  },
  squeeze: {
    what: 'Bollinger Bands are the tightest in 6 months while price holds above the 50-day average.',
    why: 'Quiet periods tend to be followed by big moves. Direction is not known yet — this is a "get ready" signal.',
    how: 'Wait for a break out of the tight range on strong volume, then trade in that direction.',
  },
  oversold: {
    what: 'RSI dropped below 35 while the stock is still above its 200-day average.',
    why: 'A sharp dip inside a long-term uptrend often snaps back.',
    how: 'Wait for a reversal day before buying and take profits quicker. Riskier — sometimes the dip is the start of a bigger drop.',
  },
  golden_cross: {
    what: 'The 50-day average crossed above the 200-day in the last 10 days.',
    why: 'Marks the medium-term trend turning up. Slow and widely watched.',
    how: 'Use it as a trend filter for longer holds rather than a precise entry — price has often already moved.',
  },
};

function SetupExplainer({ k, record, label, pointInTime }) {
  const e = EXPLAIN[k];
  if (!e) return <p className="market-sub">{label}</p>;
  const p = v => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`);
  return (
    <div className="setup-explain">
      <div className="setup-explain-head">
        <span className={`signal-chip ${TAG_CLS[k]}`}>{SHORT[k]}</span>
        {record && (
          <span className="market-sub">
            Past year: {record.signals} signals · up after 20 days {record.win_20d ?? '—'}% of the time ·
            {' '}<span className={record.excess_20d >= 0 ? 'positive' : 'negative'}>{p(record.excess_20d)} vs SPY</span>
          </span>
        )}
      </div>
      <p><b>What:</b> {e.what}</p>
      {record && <p className="market-sub">{pointInTime ? `Dated membership source: ${pointInTime.source}. Provider and delisting coverage require review.` : 'Current S&P 500 and Nasdaq-100 constituents only: survivorship bias applies.'} Forward stock returns are not executable strategy P&L and exclude fees and slippage.</p>}
      <p><b>Why it can work:</b> {e.why}</p>
      <p><b>How traders use it:</b> {e.how}</p>
    </div>
  );
}

function rsClass(rs) {
  return rs >= 80 ? 'rs-strong' : rs >= 50 ? 'rs-mid' : 'rs-weak';
}

export default function SetupScanner({ onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [setup, setSetup] = useState('all');
  const [sector, setSector] = useState('all');
  const [minRs, setMinRs] = useState(0);
  const [sort, setSort] = useState({ key: 'rs_rating', dir: -1 });

  useEffect(() => {
    let timer;
    const load = () => fetchScanner()
      .then(d => {
        setData(d);
        if (d.status !== 'ready') timer = setTimeout(load, 10_000);
      })
      .catch(e => setError(e.message));
    load();
    return () => clearTimeout(timer);
  }, []);

  const rows = useMemo(() => {
    if (!data?.rows) return [];
    return data.rows
      .filter(r => (setup === 'all' ? r.setups.length > 0 : setup === 'any' ? true : r.setups.includes(setup)))
      .filter(r => sector === 'all' || r.sector === sector)
      .filter(r => r.rs_rating >= minRs)
      .sort((a, b) => ((a[sort.key] ?? -1e9) > (b[sort.key] ?? -1e9) ? 1 : -1) * sort.dir)
      .slice(0, 150);
  }, [data, setup, sector, minRs, sort]);
  const fits = usePortfolioFit(rows.slice(0, FIT_ROWS).map(r => ({ ticker: r.symbol })));

  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading scanner…</p></div>;
  if (data.status === 'building' || !data.rows?.length) {
    return (
      <div className="card">
        <h3>🎯 Setup Scanner</h3>
        <p className="loading-text">Scanning S&P 500 and Nasdaq-100 stocks for the first time — this takes about a minute…</p>
      </div>
    );
  }

  const counts = {};
  data.rows.forEach(r => r.setups.forEach(s => { counts[s] = (counts[s] || 0) + 1; }));
  const th = (key, label, term) => (
    <th onClick={() => setSort(s => ({ key, dir: s.key === key ? -s.dir : -1 }))} className="sortable">
      {label}{term && <Tip term={term} />}{sort.key === key ? (sort.dir < 0 ? ' ▼' : ' ▲') : ''}
    </th>
  );

  return (
    <div className="setup-scanner">
      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>🎯 Setup Scanner · S&P 500 + Nasdaq-100</h3>
          <span className="market-sub">End-of-day scan · daily candles as of {new Date(data.updated_at).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
            {data.status === 'running' ? ' · refreshing…' : ' · rescans after each close (~4:30 PM ET)'}</span>
        </div>
        <p className="structures-intro">
          Rescanned every weekday after the close. <b>RS rating</b> (1–99) ranks 12-month performance across scanned S&P 500 and Nasdaq-100 stocks,
          weighted toward the last 3 months — 80+ means a market leader. Stops are 1.5 × ATR below price, targets 3 × ATR above (2:1 reward/risk).
        </p>

        <div className="scanner-filters">
          <div className="chart-toggle">
            <button className={setup === 'all' ? 'active' : ''} onClick={() => setSetup('all')}>All setups</button>
            {Object.entries(data.setup_labels).map(([k, label]) => (
              <button key={k} className={setup === k ? 'active' : ''} onClick={() => setSetup(k)} title={label}>
                {SHORT[k]} ({counts[k] || 0})
              </button>
            ))}
            <button className={setup === 'any' ? 'active' : ''} onClick={() => setSetup('any')}>Everything</button>
          </div>
          <select className="candle-select" value={sector} onChange={e => setSector(e.target.value)}>
            <option value="all">All sectors</option>
            {data.sectors.map(s => <option key={s.sector} value={s.sector}>{s.sector}</option>)}
          </select>
          <label className="market-sub">
            Min RS {minRs}
            <input type="range" min={0} max={95} step={5} value={minRs} onChange={e => setMinRs(Number(e.target.value))} />
          </label>
        </div>
        {setup !== 'all' && setup !== 'any' ? (
          <SetupExplainer k={setup} record={data.track_record?.[setup]} label={data.setup_labels[setup]} pointInTime={data.point_in_time} />
        ) : (
          <details className="setup-guide">
            <summary>What do these setups mean?</summary>
            {Object.keys(data.setup_labels).map(k => (
              <SetupExplainer key={k} k={k} record={data.track_record?.[k]} label={data.setup_labels[k]} pointInTime={data.point_in_time} />
            ))}
          </details>
        )}
      </div>

      {data.point_in_time && !data.point_in_time.available && <p className="income-warning" role="status">Historical results unavailable: {data.point_in_time.uncovered_signal_dates.length} uncovered signal dates and {data.point_in_time.missing_price_symbols.length} missing price series. Source: {data.point_in_time.source}.</p>}
      {data.track_record && (
        <div className="card">
          <h3>📈 Setup track record</h3>
          <p className="structures-intro">
            Every time a setup fired on an S&P 500 or Nasdaq-100 stock over the past year, what happened next? Counted once per
            signal (not again within 10 days). This is a backtest, not a guarantee.
          </p>
          <div className="table-scroll">
            <table className="market-table">
              <thead>
                <tr>
                  <th>Setup</th><th>Signals</th><th title="Share of signals up after 20 trading days">Win rate 20d</th>
                  <th>Avg 5d</th><th>Avg 10d</th><th>Avg 20d</th><th>Median 20d</th>
                  <th title="Share that gained 5%+ within 20 days (close-to-close)">Hit +5%</th>
                  <th title="Average 20-day return minus SPY over the same days">vs SPY</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(data.track_record)
                  .sort((a, b) => (b[1].excess_20d ?? -99) - (a[1].excess_20d ?? -99))
                  .map(([k, s]) => {
                    const c = v => (v == null ? '' : v >= 0 ? 'positive' : 'negative');
                    const p = v => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`);
                    return (
                      <tr key={k} onClick={() => setSetup(k)} title={data.setup_labels[k]}>
                        <td><span className={`signal-chip ${TAG_CLS[k]}`}>{SHORT[k]}</span></td>
                        <td>{s.signals}</td>
                        <td className={s.win_20d >= 55 ? 'positive' : s.win_20d < 45 ? 'negative' : ''}>{s.win_20d != null ? `${s.win_20d}%` : '—'}</td>
                        <td className={c(s.avg_5d)}>{p(s.avg_5d)}</td>
                        <td className={c(s.avg_10d)}>{p(s.avg_10d)}</td>
                        <td className={c(s.avg_20d)}>{p(s.avg_20d)}</td>
                        <td className={c(s.median_20d)}>{p(s.median_20d)}</td>
                        <td>{s.hit5_20d != null ? `${s.hit5_20d}%` : '—'}</td>
                        <td className={c(s.excess_20d)}><strong>{p(s.excess_20d)}</strong></td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="card">
        <h3>🏆 Sector leadership</h3>
        <div className="sector-rs">
          {data.sectors.map(s => (
            <button key={s.sector} className={`sector-rs-row ${sector === s.sector ? 'active' : ''}`}
              onClick={() => setSector(sector === s.sector ? 'all' : s.sector)}>
              <span>{s.sector}</span>
              <div className="vol-track"><div className="vol-fill vol-iv" style={{ width: `${s.rs_rating}%` }} /></div>
              <strong>{s.rs_rating}</strong>
              <span className={s.r1m >= 0 ? 'positive' : 'negative'}>{s.r1m != null ? `${s.r1m > 0 ? '+' : ''}${s.r1m}% 1M` : ''}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <p className="market-sub">{rows.length} stocks{rows.length === 150 ? ' (showing first 150)' : ''} · click a row to analyze</p>
        <div className="table-scroll">
          <table className="market-table scanner-table">
            <thead>
              <tr>
                {th('symbol', 'Stock')}
                {th('rs_rating', 'RS', 'rs_rating')}
                {th('price', 'Price')}
                {th('change_pct', 'Today')}
                {th('r1m', '1M')}
                {th('r3m', '3M')}
                {th('rsi', 'RSI', 'rsi')}
                {th('rvol', 'Rel vol', 'rvol_daily')}
                {th('pct_from_high', 'From high')}
                <th>Setups</th>
                <th>Stop / Target <Tip term="atr_stop" /></th>
                {Object.keys(fits).length > 0 && <th title={`How each of the top ${FIT_ROWS} rows fits your holdings`}>Fit</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.symbol} onClick={() => onSelect(r.symbol)}>
                  <td><strong>{r.symbol}</strong><div className="market-sub">{r.name}</div></td>
                  <td><span className={`rs-badge ${rsClass(r.rs_rating)}`}>{r.rs_rating}</span></td>
                  <td>${r.price}</td>
                  <td className={r.change_pct >= 0 ? 'positive' : 'negative'}>{r.change_pct > 0 ? '+' : ''}{r.change_pct}%</td>
                  <td className={r.r1m >= 0 ? 'positive' : 'negative'}>{r.r1m != null ? `${r.r1m}%` : '—'}</td>
                  <td className={r.r3m >= 0 ? 'positive' : 'negative'}>{r.r3m != null ? `${r.r3m}%` : '—'}</td>
                  <td>{r.rsi}</td>
                  <td className={r.rvol >= 1.5 ? 'positive' : ''}>{r.rvol != null ? `${r.rvol}×` : '—'}</td>
                  <td>{r.pct_from_high}%</td>
                  <td>{r.setups.map(s => <span key={s} className={`signal-chip ${TAG_CLS[s]}`}>{SHORT[s]}</span>)}</td>
                  <td className="market-sub">${r.stop} / ${r.target}</td>
                  {Object.keys(fits).length > 0 && <td><FitBadge fit={fits[r.symbol]} /></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
