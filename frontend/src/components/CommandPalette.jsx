import { useEffect, useMemo, useRef, useState } from 'react';

export const COMMANDS = [
  { label: 'Dashboard', keywords: 'home market overview briefing', go: { tab: 'dashboard' } },
  { label: 'Ideas: Wheel candidates', keywords: 'cash secured put csp wheel premium income', go: { tab: 'ideas', ideasTab: 'wheel' } },
  { label: 'Ideas: Covered calls / manage a wheel position', keywords: 'covered call assigned roll repair', go: { tab: 'ideas', ideasTab: 'wheel', anchor: 'wheel-manager' } },
  { label: 'Ideas: Setup scanner', keywords: 'breakout pullback squeeze scanner setups', go: { tab: 'ideas', ideasTab: 'setups' } },
  { label: 'Ideas: In play', keywords: 'movers gappers', go: { tab: 'ideas', ideasTab: 'inplay' } },
  { label: 'Ideas: Unusual options', keywords: 'flow options activity', go: { tab: 'ideas', ideasTab: 'flow' } },
  { label: 'Ideas: Insider buying', keywords: 'form 4 insiders', go: { tab: 'ideas', ideasTab: 'insiders' } },
  { label: 'Ideas: Macro calendar', keywords: 'economic calendar fed cpi', go: { tab: 'ideas', ideasTab: 'macro' } },
  { label: 'Ideas: Strategy tester', keywords: 'backtest', go: { tab: 'ideas', ideasTab: 'tester' } },
  { label: 'Ideas: Options track record', keywords: 'results history', go: { tab: 'ideas', ideasTab: 'record' } },
  { label: 'Watchlist', keywords: 'screener list', go: { tab: 'watchlist' } },
  { label: 'Watchlist: Buy zones', keywords: 'target entry price get paid to wait put', go: { tab: 'watchlist', anchor: 'buy-zones' } },
  { label: 'Watchlist: Earnings & ex-dividend week', keywords: 'calendar dividends reports', go: { tab: 'watchlist', anchor: 'event-week' } },
  { label: 'Portfolio: Holdings', keywords: 'stocks options lots positions', go: { tab: 'portfolio', section: 'holdings' } },
  { label: 'Portfolio: Import broker CSV', keywords: 'upload etrade fidelity schwab robinhood webull sync', go: { tab: 'portfolio', section: 'holdings', anchor: 'import-csv' } },
  { label: 'Portfolio Risk: Suggested next steps', keywords: 'suggestions todo', go: { tab: 'portfolio', section: 'risk' } },
  { label: 'Portfolio Risk: Position alerts', keywords: 'option alerts take profit tested', go: { tab: 'portfolio', section: 'risk', anchor: 'position-alerts' } },
  { label: 'Portfolio Risk: Expiration ladder', keywords: 'expiry assignment tax lots', go: { tab: 'portfolio', section: 'risk', anchor: 'expiry-ladder' } },
  { label: 'Portfolio Risk: Trim planner', keywords: 'concentration sell reduce exit', go: { tab: 'portfolio', section: 'risk', anchor: 'trim-planner' } },
  { label: 'Portfolio Risk: My trading rules', keywords: 'rules limits discipline', go: { tab: 'portfolio', section: 'risk', anchor: 'trading-rules' } },
  { label: 'Income & Performance', keywords: 'ledger premium dividends tax spy weekly review', go: { tab: 'portfolio', section: 'performance' } },
  { label: 'Journal: Trade history', keywords: 'closed trades', go: { tab: 'journal' } },
  { label: 'Journal: Your edge', keywords: 'stats win rate best worst patterns', go: { tab: 'journal', anchor: 'edge-report' } },
  { label: 'Journal: Daily P&L calendar', keywords: 'calendar profit loss month', go: { tab: 'journal', anchor: 'pnl-calendar' } },
  { label: 'System status', keywords: 'health providers diagnostics', go: { action: 'status' }, signedIn: true },
  { label: 'Toggle light / dark theme', keywords: 'theme dark light mode', go: { action: 'theme' } },
];

export function matchCommands(query, signedIn) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const list = COMMANDS.filter(c => signedIn || !c.signedIn)
    .filter(c => words.every(w => `${c.label} ${c.keywords}`.toLowerCase().includes(w)));
  const ticker = /^[A-Za-z][A-Za-z.-]{0,5}$/.test(words[0] || '') && words.length === 1 ? words[0].toUpperCase() : null;
  if (!ticker) return list;
  const open = { label: `Open ${ticker} stock page`, go: { ticker } };
  return list.length ? [...list, open] : [open];
}

export default function CommandPalette({ onClose, onRun, signedIn }) {
  const dialog = useRef(null);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const results = useMemo(() => matchCommands(query, signedIn).slice(0, 12), [query, signedIn]);
  useEffect(() => { dialog.current.showModal(); }, []);
  const run = item => { if (item) { onClose(); onRun(item.go); } };
  const onKey = event => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive(i => Math.min(i + 1, results.length - 1)); }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive(i => Math.max(i - 1, 0)); }
    if (event.key === 'Enter') { event.preventDefault(); run(results[active]); }
  };
  return <dialog ref={dialog} className="command-palette" aria-label="Jump to"
    onCancel={event => { event.preventDefault(); onClose(); }} onClick={event => { if (event.target === dialog.current) onClose(); }}>
    <input autoFocus className="tool-input" placeholder="Type a ticker, tab or tool…  (Esc to close)" aria-label="Jump to"
      role="combobox" aria-expanded="true" aria-controls="command-results" aria-activedescendant={results[active] ? `command-${active}` : undefined}
      value={query} onChange={event => { setQuery(event.target.value); setActive(0); }} onKeyDown={onKey} />
    <ul id="command-results" role="listbox">
      {results.map((item, i) => <li key={item.label} id={`command-${i}`} role="option" aria-selected={i === active}
        className={i === active ? 'active' : ''} onMouseEnter={() => setActive(i)} onClick={() => run(item)}>{item.label}</li>)}
      {!results.length && <li className="market-sub" role="option" aria-selected="false">No matches</li>}
    </ul>
  </dialog>;
}
