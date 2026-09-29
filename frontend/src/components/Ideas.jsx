import { useState, useEffect } from 'react';
import SetupScanner from './SetupScanner';
import EconomicCalendar from './EconomicCalendar';
import { FlowTable } from './OptionsFlow';
import { fetchUnusualOptions, fetchInsiderBuying, fetchSuperinvestors } from '../api/stockApi';

const money = v => v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${(v / 1e3).toFixed(0)}K`;
const TABS = [
  ['setups', '🎯 Setups'], ['flow', '🌊 Unusual options'], ['insiders', '🕴️ Insider buying'],
  ['super', '🧠 Superinvestors'], ['macro', '📅 Macro calendar'],
];
const ACTION = { new: ['🆕 New', 'positive'], added: ['➕ Added', 'positive'], reduced: ['➖ Reduced', 'negative'], sold: ['❌ Sold', 'negative'] };

function useLoad(fn, poll) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let timer;
    const load = () => fn().then(d => {
      setData(d);
      if (poll && d.status === 'building') timer = setTimeout(load, 15_000);
    }).catch(e => setError(e.message));
    load();
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return [data, error];
}

function UnusualOptions({ onSelect }) {
  const [data, error] = useLoad(fetchUnusualOptions);
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Scanning option chains across {40}+ liquid stocks…</p></div>;
  const total = data.bought_call_premium + data.bought_put_premium;
  const callShare = total ? Math.round(data.bought_call_premium / total * 100) : null;
  return (
    <>
      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>🌊 Unusual options activity</h3>
          <span className="market-sub">{data.scanned} stocks · {new Date(data.as_of).toLocaleTimeString()}</span>
        </div>
        <p className="structures-intro">
          Contracts trading more than their open interest with at least $25K premium, 2–60 days out — often new positions
          by large traders. Includes the liquid leaders plus everything in users' portfolios and watchlists.
        </p>
        {callShare != null && (
          <div className="doctor-stats">
            <div><span>Premium bought at the ask: calls</span><strong className="positive">{money(data.bought_call_premium)}</strong></div>
            <div><span>Premium bought at the ask: puts</span><strong className="negative">{money(data.bought_put_premium)}</strong></div>
            <div><span>Bullish share</span><strong className={callShare >= 55 ? 'positive' : callShare <= 45 ? 'negative' : ''}>{callShare}%</strong></div>
          </div>
        )}
        <FlowTable trades={data.trades} showTicker onSelect={onSelect} />
      </div>
      <div className="two-column">
        {[['Most call-heavy (put/call volume)', data.most_bullish, 'positive'], ['Most put-heavy', data.most_bearish, 'negative']].map(([title, list, cls]) => (
          <div className="card" key={title}>
            <h4 className="sub-chart-title">{title}</h4>
            <ul className="smart-list">
              {list.map(s => (
                <li key={s.ticker}>
                  <button className="link-btn" onClick={() => onSelect(s.ticker)}><strong>{s.ticker}</strong></button>
                  {' '}<span className={cls}>P/C {s.pc_volume}</span> <span className="market-sub">· {s.volume.toLocaleString()} contracts</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}

function InsiderBuying({ onSelect }) {
  const [data, error] = useLoad(fetchInsiderBuying);
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Reading 30 days of SEC Form 4 filings…</p></div>;
  const table = (rows, cluster) => (
    <div className="table-scroll">
      <table className="market-table">
        <thead><tr><th>Stock</th>{cluster && <th>Insiders</th>}<th>Total bought</th><th>Avg price</th><th>Last buy</th><th>Who</th></tr></thead>
        <tbody>
          {rows.map(g => (
            <tr key={g.symbol} onClick={() => onSelect(g.symbol)}>
              <td><strong>{g.symbol}</strong></td>
              {cluster && <td><span className="rs-badge rs-strong">{g.insiders}</span></td>}
              <td className="positive"><strong>{money(g.total_value)}</strong></td>
              <td>${g.avg_price}</td>
              <td>{g.last_date}</td>
              <td className="market-sub">{g.names.join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
  return (
    <>
      <div className="card">
        <h3>🕴️ Insider cluster buying</h3>
        <p className="structures-intro">
          Two or more executives or directors buying their own stock on the open market within {data.days} days — one of the
          better-documented bullish signals. Grants, option exercises and sales are excluded. {data.purchases} purchases scanned.
        </p>
        {data.unavailable ? <p className="empty-state">Insider feed is unavailable right now.</p>
          : data.clusters.length ? table(data.clusters, true) : <p className="empty-state">No clusters in this window.</p>}
      </div>
      {data.big_buys.length > 0 && (
        <div className="card">
          <h3>💰 Largest single-insider buys</h3>
          {table(data.big_buys, false)}
        </div>
      )}
    </>
  );
}

function Superinvestors({ onSelect }) {
  const [data, error] = useLoad(fetchSuperinvestors, true);
  const [fund, setFund] = useState(null);
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading…</p></div>;
  if (data.status === 'building') {
    return <div className="card"><p className="loading-text">Reading the latest 13F filings from SEC EDGAR — takes about 2 minutes the first time…</p></div>;
  }
  const f = data.funds.find(x => x.cik === fund) || data.funds[0];
  const tick = h => h.ticker
    ? <button className="link-btn" onClick={() => onSelect(h.ticker)}><strong>{h.ticker}</strong></button>
    : <span className="market-sub">—</span>;
  return (
    <>
      {data.consensus.length > 0 && (
        <div className="card">
          <h3>🤝 Consensus holdings</h3>
          <p className="market-sub">Stocks in the top 15 of two or more tracked superinvestors.</p>
          <ul className="smart-list">
            {data.consensus.map(c => (
              <li key={c.ticker}>
                <button className="link-btn" onClick={() => onSelect(c.ticker)}><strong>{c.ticker}</strong></button>
                {' '}<span className="rs-badge rs-mid">{c.holders.length}</span> <span className="market-sub">{c.holders.join(', ')}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="card">
        <div className="ivrank-header">
          <h3 style={{ margin: 0 }}>🧠 Superinvestor portfolios</h3>
          <select className="candle-select" value={f?.cik || ''} onChange={e => setFund(Number(e.target.value))}>
            {data.funds.map(x => <option key={x.cik} value={x.cik}>{x.manager} — {x.firm}</option>)}
          </select>
        </div>
        {f && (
          <>
            <p className="market-sub">
              13F for quarter ending {f.period}, filed {f.filed} · {f.positions} positions · {money(f.total_value)} in US stocks.
              13Fs are filed up to 45 days after quarter end, so positions may have changed.
            </p>
            <div className="two-column">
              <div>
                <h4 className="sub-chart-title">Top holdings</h4>
                <table className="market-table">
                  <tbody>
                    {f.top.map(h => (
                      <tr key={h.cusip}><td>{tick(h)}</td><td>{h.name}</td><td><strong>{h.weight}%</strong></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <h4 className="sub-chart-title">Changes last quarter</h4>
                <table className="market-table">
                  <tbody>
                    {f.changes.map(h => (
                      <tr key={h.cusip + h.action}>
                        <td>{tick(h)}</td><td>{h.name}</td>
                        <td className={ACTION[h.action][1]}>{ACTION[h.action][0]}{h.pct_change != null && h.action !== 'sold' ? ` ${h.pct_change > 0 ? '+' : ''}${h.pct_change}%` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}

export default function Ideas({ onSelect }) {
  const [tab, setTab] = useState(() => sessionStorage.getItem('ideas_tab') || 'setups');
  const choose = t => { setTab(t); sessionStorage.setItem('ideas_tab', t); };
  return (
    <div className="ideas-page">
      <nav className="sub-tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={`sub-tab ${tab === id ? 'active' : ''}`} onClick={() => choose(id)}>{label}</button>
        ))}
      </nav>
      {tab === 'setups' && <SetupScanner onSelect={onSelect} />}
      {tab === 'flow' && <UnusualOptions onSelect={onSelect} />}
      {tab === 'insiders' && <InsiderBuying onSelect={onSelect} />}
      {tab === 'super' && <Superinvestors onSelect={onSelect} />}
      {tab === 'macro' && <EconomicCalendar />}
    </div>
  );
}
