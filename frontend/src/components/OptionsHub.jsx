import { useState, useEffect } from 'react';
import IvRank from './IvRank';
import IncomeIdeas from './IncomeIdeas';
import Structures from './Structures';
import OptionsFlow from './OptionsFlow';
import EarningsIntel from './EarningsIntel';

const Volatility = ({ ticker }) => <><IvRank ticker={ticker} /><EarningsIntel ticker={ticker} /></>;

const TABS = {
  volatility: { icon: '📊', label: 'Volatility', short: 'Volatility', Comp: Volatility },
  income: { icon: '💵', label: 'Sell premium', short: 'Income', Comp: IncomeIdeas },
  directional: { icon: '🛠', label: 'Directional', short: 'Directional', Comp: Structures },
  flow: { icon: '🌊', label: 'Flow & positioning', short: 'Flow', Comp: OptionsFlow },
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
