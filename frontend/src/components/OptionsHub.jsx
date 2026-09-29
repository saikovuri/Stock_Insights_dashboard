import { useState, useEffect } from 'react';
import IvRank from './IvRank';
import IncomeIdeas from './IncomeIdeas';
import Structures from './Structures';
import OptionsFlow from './OptionsFlow';

const TABS = {
  volatility: { label: '📊 Volatility', Comp: IvRank },
  income: { label: '💵 Sell premium', Comp: IncomeIdeas },
  directional: { label: '🛠 Directional', Comp: Structures },
  flow: { label: '🌊 Flow & positioning', Comp: OptionsFlow },
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
            {TABS[id].label}
          </button>
        ))}
      </nav>
      <Comp ticker={ticker} />
    </div>
  );
}
