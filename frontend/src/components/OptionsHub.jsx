import { useState, useEffect } from 'react';
import IvRank from './IvRank';
import IncomeIdeas from './IncomeIdeas';
import Structures from './Structures';
import OptionsFlow from './OptionsFlow';
import EarningsIntel from './EarningsIntel';
import { useProfile } from '../ProfileContext';

// Positioning (walls, gamma, max pain, unusual contracts) leads for day traders and is folded away for long-term investors
function Volatility({ ticker }) {
  const { profile } = useProfile();
  const positioning = <OptionsFlow key="flow" ticker={ticker} />;
  const volatility = [<IvRank key="iv" ticker={ticker} />, <EarningsIntel key="er" ticker={ticker} />];
  if (profile === 'day') return <>{positioning}{volatility}</>;
  if (profile === 'long') {
    return <>{volatility}<details className="setup-guide positioning-fold"><summary>🌊 Positioning & unusual activity</summary>{positioning}</details></>;
  }
  return <>{volatility}{positioning}</>;
}

const TABS = {
  volatility: { icon: '📊', label: 'Volatility & positioning', short: 'Volatility', Comp: Volatility },
  income: { icon: '💵', label: 'Sell premium', short: 'Income', Comp: IncomeIdeas },
  directional: { icon: '🛠', label: 'Directional', short: 'Directional', Comp: Structures },
};

export default function OptionsHub({ ticker, tabs }) {
  const [tab, setTab] = useState(tabs[0]);
  useEffect(() => { if (!tabs.includes(tab)) setTab(tabs[0]); }, [tabs, tab]);
  const { Comp } = TABS[tab] || TABS[tabs[0]];
  return (
    <div className="options-hub">
      <nav className="sub-tabs options-hub-tabs">
        <span className="options-hub-title">Options</span>
        {tabs.map(id => (
          <button key={id} className={`sub-tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
            <span className="hub-tab-icon">{TABS[id].icon}</span>{' '}
            <span className="hide-mobile">{TABS[id].label}</span>
            <span className="show-mobile">{TABS[id].short}</span>
          </button>
        ))}
      </nav>
      <Comp ticker={ticker} />
    </div>
  );
}
