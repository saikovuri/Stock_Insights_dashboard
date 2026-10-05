import { useEffect, useState } from 'react';
import { fetchMarketContext } from '../api/stockApi';

const number = value => value == null ? 'Unavailable' : Number(value).toLocaleString();
const money = value => value == null ? 'Unavailable' : `$${Number(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const stamp = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : 'Unavailable';
const signed = value => `${value > 0 ? '+' : ''}${value}`;

export default function MarketContext({ kind, onSelect }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [retry, setRetry] = useState(0);
  const attention = kind === 'attention';

  useEffect(() => {
    let active = true;
    setData(null); setError(null);
    const load = () => fetchMarketContext(kind).then(result => {
      if (active) { setData(result); setError(null); }
    }).catch(() => {
      if (active) { setData(null); setError('Market context is unavailable. Missing data does not mean no activity.'); }
    });
    load();
    const timer = setInterval(load, 600_000);
    return () => { active = false; clearInterval(timer); };
  }, [kind, retry]);

  const unavailable = error || (data && data.status !== 'ready' ? data.message : null);
  return (
    <section className="market-context" aria-label={attention ? 'Reddit attention' : 'Prediction-market context'}>
      <header>
        <h3>{attention ? 'Reddit attention' : 'Prediction-market context'}</h3>
        <a href={attention ? 'https://apewisdom.io/api' : 'https://polymarket.com/economy'} target="_blank" rel="noopener noreferrer">
          {attention ? 'ApeWisdom / Reddit' : 'Polymarket'}
        </a>
      </header>
      <p className="market-sub">{attention
        ? 'Mention counts are attention, not sentiment or verified news. Bots, promotion and ambiguous tickers can distort rankings. X is not connected.'
        : 'Market-implied Yes prices, not verified probabilities or stock forecasts. Resolution rules and liquidity matter. Read-only context; not a trade signal.'}</p>
      {!data && !error && <p role="status">Loading market context...</p>}
      {unavailable && <div role="status"><p>{unavailable}</p>
        {data?.status !== 'disabled' && <button className="btn-secondary btn-sm" onClick={() => setRetry(value => value + 1)}>Retry</button>}
      </div>}
      {data?.status === 'ready' && <>
        <p className="market-sub">Retrieved {stamp(data.fetched_at)}. {data.scope}</p>
        {attention && <p className="market-sub">Provider update time is unavailable. Comparison is against the provider snapshot 24h ago, not a historical average.</p>}
        {data.rows.length === 0 && <p role="status">No qualifying records in the provider sample.</p>}
        {attention && data.rows.length > 0 && <div className="table-scroll">
          <table className="market-table">
            <thead><tr><th>Stock</th><th>Mentions</th><th>24h-ago snapshot</th><th>Change</th><th>Source</th></tr></thead>
            <tbody>{data.rows.map(row => <tr key={row.ticker}>
              <td><button className="link-btn" onClick={() => onSelect?.(row.ticker)}>{row.ticker}</button><div className="market-sub">{row.name}</div></td>
              <td>{number(row.mentions)}</td><td>{number(row.previous_mentions)}</td>
              <td>{row.change_pct == null ? row.previous_mentions === 0 ? 'No baseline' : 'Unavailable' : `${signed(row.change_pct)}%`}</td>
              <td><a href={row.url} target="_blank" rel="noopener noreferrer">Source</a></td>
            </tr>)}</tbody>
          </table>
        </div>}
        {!attention && <ul className="prediction-list">{data.rows.map(row => <li key={row.id}>
          <div className="prediction-heading"><a href={row.url} target="_blank" rel="noopener noreferrer">{row.question}</a>
            <strong>Yes {row.yes_pct}%</strong></div>
          <dl className="prediction-metrics">
            <div><dt>24h change</dt><dd>{row.change_pp == null ? 'Unavailable' : `${signed(row.change_pp)} pp`}</dd></div>
            <div><dt>24h volume</dt><dd>{money(row.volume_24h)}</dd></div>
            <div><dt>Reported liquidity</dt><dd>{money(row.liquidity)}</dd></div>
          </dl>
          <p className="market-sub">Market end {stamp(row.end_at)} · Provider updated {stamp(row.updated_at)}</p>
          {row.warnings.map(warning => <p className="rvol-warm" key={warning}>{warning}</p>)}
          <a href={row.url} target="_blank" rel="noopener noreferrer">Market and resolution rules</a>
        </li>)}</ul>}
      </>}
    </section>
  );
}