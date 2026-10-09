import { useState, useEffect } from 'react';
import TabStrip from './TabStrip';
import SetupScanner from './SetupScanner';
import EconomicCalendar from './EconomicCalendar';
import InPlay from './InPlay';
import StrategyTester from './StrategyTester';
import WheelIdeas from './WheelIdeas';
import { useProfile } from '../ProfileContext';
import { FlowTable } from './OptionsFlow';
import { fetchUnusualOptions, fetchInsiderBuying, fetchTrackRecord } from '../api/stockApi';

const money = v => v >= 1e9 ? `$${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(1)}M` : `$${(v / 1e3).toFixed(0)}K`;
const TABS = [
  ['inplay', '⚡ In play'], ['setups', '🎯 Setups'], ['wheel', '🎡 Wheel'], ['flow', '🌊 Unusual options'], ['insiders', '🕴️ Insider buying'],
  ['macro', '📅 Macro calendar'], ['tester', '🧪 Strategy tester'], ['record', '📋 Options track record'],
];

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
          or spread activity. Volume does not establish institutional intent; notional uses volume times a quote proxy, not observed execution proceeds.
        </p>
        {callShare != null && (
          <div className="doctor-stats">
            <div><span>Call notional, last near ask</span><strong>{money(data.bought_call_premium)}</strong></div>
            <div><span>Put notional, last near ask</span><strong>{money(data.bought_put_premium)}</strong></div>
            <div><span>Call share of proxy notional</span><strong>{callShare}%</strong></div>
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

function TrackRecord() {
  const [data, error] = useLoad(fetchTrackRecord);
  if (error) return <div className="card"><p className="error-text">{error}</p></div>;
  if (!data) return <div className="card"><p className="loading-text">Loading…</p></div>;
  const pct = v => v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`;
  return (
    <div className="card">
      <h3>📋 How our option ideas actually did</h3>
      <p className="structures-intro">
        Every income, wheel and directional idea is recorded the first time it's shown and scored at expiry from the
        closing price. {data.settled} settled, {data.open} still open{data.since ? ` (tracking since ${data.since})` : ''}.
      </p>
      {data.groups.length === 0 ? (
        <p className="empty-state">
          No ideas have expired yet{data.next_expiry ? ` — the first results come in after ${data.next_expiry}` : ''}.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="market-table">
            <thead><tr><th>Idea</th><th>Count</th><th>Avg delta</th><th>Profitable</th><th>Kept full premium</th><th>Avg return on risk</th><th>Worst</th></tr></thead>
            <tbody>
              {data.groups.map(g => (
                <tr key={g.kind + g.label}>
                  <td><strong>{g.name}</strong>{g.label && <span className="market-sub"> · {g.label}</span>}</td>
                  <td>{g.ideas}</td>
                  <td>{g.avg_delta}</td>
                  <td className={g.win_rate >= 60 ? 'positive' : g.win_rate < 45 ? 'negative' : ''}><strong>{g.win_rate}%</strong></td>
                  <td>{g.expired_worthless_pct != null ? `${g.expired_worthless_pct}%` : '—'}</td>
                  <td className={g.avg_return_on_risk_pct >= 0 ? 'positive' : 'negative'}>{pct(g.avg_return_on_risk_pct)}</td>
                  <td className="negative">{pct(g.worst_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="ivrank-note">{data.note}</p>
    </div>
  );
}

export default function Ideas({ onSelect }) {
  const { profile } = useProfile();
  const [tab, setTab] = useState(() => {
    const saved = sessionStorage.getItem('ideas_tab');
    return TABS.some(([id]) => id === saved) ? saved : profile === 'day' ? 'inplay' : 'setups';
  });
  const choose = t => { setTab(t); sessionStorage.setItem('ideas_tab', t); };
  useEffect(() => {
    const onGoto = event => { if (event.detail?.ideasTab) setTab(event.detail.ideasTab); };
    window.addEventListener('stockpilot:goto', onGoto);
    return () => window.removeEventListener('stockpilot:goto', onGoto);
  }, []);
  return (
    <div className="ideas-page">
      <TabStrip label="Ideas views" activeKey={tab}>
        {TABS.map(([id, label]) => (
          <button key={id} className={`sub-tab ${tab === id ? 'active' : ''}`} onClick={() => choose(id)}>{label}</button>
        ))}
      </TabStrip>
      {tab === 'inplay' && <InPlay onSelect={onSelect} />}
      {tab === 'setups' && <SetupScanner onSelect={onSelect} />}
      {tab === 'wheel' && <WheelIdeas onSelect={onSelect} />}
      {tab === 'flow' && <UnusualOptions onSelect={onSelect} />}
      {tab === 'insiders' && <InsiderBuying onSelect={onSelect} />}
      {tab === 'macro' && <EconomicCalendar />}
      {tab === 'tester' && <StrategyTester />}
      {tab === 'record' && <TrackRecord />}
    </div>
  );
}
