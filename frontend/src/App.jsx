import { useState, useEffect } from 'react';
import { AuthProvider, useAuth } from './AuthContext';
import { ThemeProvider, useTheme } from './ThemeContext';
import LoginPage from './components/LoginPage';
import SearchBar from './components/SearchBar';
import KeyMetrics from './components/KeyMetrics';
import PriceChart from './components/CandleChart';
import NewsSentiment from './components/NewsSentiment';
import AiBrief from './components/AiBrief';
import Alerts from './components/Alerts';
import Portfolio from './components/Portfolio';
import Watchlist from './components/Watchlist';
import AiChat from './components/AiChat';
import PeerBenchmark from './components/PeerBenchmark';
import WatchlistRail from './components/WatchlistRail';
import AnalystRatings from './components/AnalystRatings';
import Financials from './components/Financials';
import Ownership from './components/Ownership';
import OptionsHub from './components/OptionsHub';
import NotificationBell from './components/NotificationBell';
import DailyBriefing from './components/DailyBriefing';
import MarketOverview from './components/MarketOverview';
import PriceAlerts from './components/PriceAlerts';
import EarningsIntel from './components/EarningsIntel';
import Ideas from './components/Ideas';
import RelativeStrength from './components/RelativeStrength';
import Journal from './components/Journal';
import LongTermView from './components/LongTermView';
import ShortAndSmartMoney from './components/ShortAndSmartMoney';
import ThesisCard from './components/ThesisCard';
import EconomicCalendar from './components/EconomicCalendar';
import { ProfileProvider, useProfile, PROFILES, ALL_OPTION_TABS } from './ProfileContext';
import { fetchMetrics, fetchHistory, fetchNews, fetchAlerts, fetchEvents } from './api/stockApi';

const VALID_TABS = ['dashboard', 'ideas', 'watchlist', 'portfolio', 'journal'];
// Old bookmarks keep working
const LEGACY_TABS = { setups: 'ideas', screener: 'watchlist', tools: 'journal' };
const SUB_TAB_LABELS = {
  overview: '📋 Overview', analysis: '🔬 Analysis', fundamentals: '📑 Fundamentals', news: '📰 News',
};
function tabFromHash() {
  const hash = window.location.hash.slice(1);
  const t = LEGACY_TABS[hash] || hash;
  return VALID_TABS.includes(t) ? t : null;
}
function getInitialTab() {
  return tabFromHash() || 'dashboard';
}

function AppShell() {
  const { user, logout, loading: authLoading } = useAuth();
  const { theme, toggle: toggleTheme } = useTheme();
  const { profile, setProfile, config } = useProfile();
  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [showLogin, setShowLogin] = useState(false);
  const [ticker, setTicker] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [history, setHistory] = useState(null);
  const [newsData, setNewsData] = useState(null);
  const [alerts, setAlerts] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [events, setEvents] = useState(null);
  const [period, setPeriod] = useState(config.chart.period);
  const [interval, setChartInterval] = useState(config.chart.interval);
  const [prepost, setPrepost] = useState(false);
  const [subTab, setSubTab] = useState('overview');
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    const onHashChange = () => {
      const t = tabFromHash();
      if (t) setActiveTab(t);
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  if (authLoading) return <div className="app"><p className="loading-text">Loading...</p></div>;

  // If user clicks login from the modal
  if (showLogin && !user) {
    return <LoginPage onBack={() => setShowLogin(false)} />;
  }

  const handleSearch = async (t, p, i, pp) => {
    const usePeriod = p ?? period;
    const useInterval = i ?? interval;
    const usePrepost = pp ?? prepost;
    setLoading(true);
    setError(null);
    setTicker(t);

    try {
      const [m, h, n, a, ev] = await Promise.all([
        fetchMetrics(t),
        fetchHistory(t, usePeriod, useInterval, usePrepost),
        fetchNews(t).catch(() => ({ articles: [], sentiment: {} })),
        fetchAlerts(t).catch(() => []),
        fetchEvents(t).catch(() => null),
      ]);
      if (!m) throw new Error(`No data found for "${t}"`);
      setMetrics(m);
      setHistory(h);
      setNewsData(n);
      setAlerts(a);
      setEvents(ev);
    } catch (e) {
      setError(e.message);
      setMetrics(null);
      setHistory(null);
      setNewsData(null);
      setAlerts(null);
      setEvents(null);
    } finally {
      setLoading(false);
    }
  };

  const handleTabClick = (tabId) => {
    setActiveTab(tabId);
    window.history.pushState(null, '', `#${tabId}`);
  };

  const openTicker = (t) => {
    handleTabClick('dashboard');
    setSubTab('overview');
    handleSearch(t);
  };

  const changeProfile = (p) => {
    setProfile(p);
    const { period: np, interval: ni } = PROFILES[p].chart;
    setPeriod(np);
    setChartInterval(ni);
    if (ticker) handleSearch(ticker, np, ni, prepost);
  };

  const tabs = [
    { id: 'dashboard', label: '📊 Dashboard' },
    { id: 'ideas', label: '💡 Ideas' },
    { id: 'watchlist', label: '👀 Watchlist' },
    { id: 'portfolio', label: '💼 Portfolio' },
    { id: 'journal', label: '📓 Journal' },
  ];

  // Cards hidden for the selected trading style (revealed with "show all")
  const SUB_CARDS = {
    overview: ['thesis'], analysis: ['rs'], fundamentals: ['longterm', 'ownership', 'financials'], news: [],
  };
  const show = (id) => showAll || !config.hide.includes(id);
  const hiddenHere = (SUB_CARDS[subTab] || []).filter(id => config.hide.includes(id)).length;
  const optionTabs = showAll ? ALL_OPTION_TABS : config.options;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <h1 onClick={() => { setActiveTab('dashboard'); window.location.hash = 'dashboard'; }} style={{ cursor: 'pointer' }}><span className="header-emoji">📈</span><span className="header-title-text">Stock Insights</span></h1>
          <div className="user-menu">
            <select className="candle-select profile-select" value={profile} onChange={e => changeProfile(e.target.value)}
              title="Your trading style tailors charts, layout and AI analysis">
              {Object.entries(PROFILES).map(([k, p]) => <option key={k} value={k}>{p.icon} {p.label}</option>)}
            </select>
            <button className="btn-theme" onClick={toggleTheme} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            {user ? (
              <>
                <NotificationBell />
                <span className="user-greeting">Hi, {user.display_name}</span>
                <button className="btn-logout" onClick={logout}>Sign Out</button>
              </>
            ) : (
              <button className="btn-login" onClick={() => setShowLogin(true)}>Sign In</button>
            )}
          </div>
        </div>

        <nav className="main-tabs">
          {tabs.map(tab => (
            <button
              key={tab.id}
              className={`main-tab ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => handleTabClick(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      {activeTab === 'dashboard' && (
        <div className="dashboard-layout">
          <div className="dashboard-main">
            <SearchBar onSearch={(t) => handleSearch(t)} loading={loading} activeTicker={ticker} />
            {error && <div className="error-banner">{error}</div>}
            {!ticker && !loading && (
              <>
                {user && <DailyBriefing onSelect={(t) => handleSearch(t)} />}
                <MarketOverview onSelect={(t) => handleSearch(t)} />
                <EconomicCalendar compact />
              </>
            )}

            {ticker && metrics && (
              <>
                {/* ── Sub-tab navigation (ordered by trading style) ── */}
                <nav className="sub-tabs">
                  {config.subTabs.map(id => ({ id, label: SUB_TAB_LABELS[id] })).map(t => (
                    <button
                      key={t.id}
                      className={`sub-tab ${subTab === t.id ? 'active' : ''}`}
                      onClick={() => setSubTab(t.id)}
                    >{t.label}</button>
                  ))}
                </nav>

                {/* ── Overview ────────────────────────────────── */}
                {subTab === 'overview' && (
                  <>
                    <Alerts alerts={alerts} />
                    <KeyMetrics metrics={metrics} />
                    <AiBrief ticker={ticker} profile={profile} onSignIn={() => setShowLogin(true)} />
                    {show('thesis') && <ThesisCard ticker={ticker} />}
                    <PriceChart ticker={ticker} data={history} events={events}
                      period={period} interval={interval} prepost={prepost}
                      onSettingsChange={({ period: p, interval: i, prepost: pp }) => {
                        const newPeriod = p ?? period;
                        const newInterval = i ?? interval;
                        const newPrepost = pp ?? prepost;
                        if (p !== undefined) setPeriod(p);
                        if (i !== undefined) setChartInterval(i);
                        if (pp !== undefined) setPrepost(pp);
                        if (ticker) handleSearch(ticker, newPeriod, newInterval, newPrepost);
                      }}
                    />
                    <PriceAlerts ticker={ticker} price={metrics.price} onSignIn={() => setShowLogin(true)} />
                  </>
                )}

                {/* ── Analysis ────────────────────────────────── */}
                {subTab === 'analysis' && (
                  <>
                    {show('rs') && <RelativeStrength ticker={ticker} />}
                    <OptionsHub ticker={ticker} tabs={optionTabs} />
                    <ShortAndSmartMoney ticker={ticker} />
                    <AnalystRatings ticker={ticker} />
                    <PeerBenchmark ticker={ticker} />
                    <AiChat ticker={ticker} onSignIn={() => setShowLogin(true)} />
                  </>
                )}

                {/* ── Fundamentals ────────────────────────────── */}
                {subTab === 'fundamentals' && (
                  <>
                    {show('longterm') && <LongTermView ticker={ticker} />}
                    <EarningsIntel ticker={ticker} />
                    {show('ownership') && <Ownership ticker={ticker} />}
                    {show('financials') && (
                      <details className="raw-statements">
                        <summary>📑 Raw financial statements (income, balance sheet, cash flow)</summary>
                        <Financials ticker={ticker} />
                      </details>
                    )}
                  </>
                )}

                {/* ── News & AI ───────────────────────────────── */}
                {subTab === 'news' && <NewsSentiment newsData={newsData} />}

                {(hiddenHere > 0 || (subTab === 'analysis' && config.options.length < ALL_OPTION_TABS.length) || showAll) && (
                  <button className="btn-secondary btn-sm show-all-btn" onClick={() => setShowAll(v => !v)}>
                    {showAll ? `Show only ${PROFILES[profile].label.toLowerCase()} essentials` : `Show cards hidden for ${PROFILES[profile].label.toLowerCase()}s`}
                  </button>
                )}
              </>
            )}
          </div>
          <WatchlistRail
            activeTicker={ticker}
            onSelect={(t) => handleSearch(t)}
            onGoToScreener={() => handleTabClick('watchlist')}
          />
        </div>
      )}

      {activeTab === 'ideas' && <Ideas onSelect={openTicker} />}

      {activeTab === 'watchlist' && (
        <>
          <Watchlist onSelect={openTicker} onSignIn={() => setShowLogin(true)} />
          {user && <PriceAlerts />}
        </>
      )}

      {activeTab === 'portfolio' && <Portfolio />}

      {activeTab === 'journal' && <Journal onSignIn={() => setShowLogin(true)} onSelect={openTicker} />}

      <footer className="app-footer">
        Data: Finnhub, Yahoo Finance, CBOE, SEC EDGAR, FINRA, Nasdaq &middot; AI-generated analysis can be wrong &middot; Not financial advice
      </footer>
    </div>
  );
}

export default function App() {
  return <AppShell />;
}

export function AppRoot() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <ProfileProvider>
          <App />
        </ProfileProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}
