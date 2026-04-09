import { useState, useEffect } from 'react';
import { AuthProvider, useAuth } from './AuthContext';
import { ThemeProvider, useTheme } from './ThemeContext';
import LoginPage from './components/LoginPage';
import SearchBar from './components/SearchBar';
import KeyMetrics from './components/KeyMetrics';
import PriceChart from './components/PriceChart';
import NewsSentiment from './components/NewsSentiment';
import AiSummary from './components/AiSummary';
import Alerts from './components/Alerts';
import Portfolio from './components/Portfolio';
import Screener from './components/Screener';
import WhyMoving from './components/WhyMoving';
import BullBear from './components/BullBear';
import AiChat from './components/AiChat';
import PeerBenchmark from './components/PeerBenchmark';
import PositionCalculator from './components/PositionCalculator';
import DcaSimulator from './components/DcaSimulator';
import WatchlistRail from './components/WatchlistRail';
import AnalystRatings from './components/AnalystRatings';
import Financials from './components/Financials';
import Ownership from './components/Ownership';
import DividendHistory from './components/DividendHistory';
import { fetchMetrics, fetchHistory, fetchNews, fetchAlerts, fetchEvents } from './api/stockApi';

const VALID_TABS = ['dashboard', 'screener', 'portfolio', 'tools'];
function getInitialTab() {
  const hash = window.location.hash.slice(1);
  return VALID_TABS.includes(hash) ? hash : 'dashboard';
}

function AppShell() {
  const { user, logout, loading: authLoading } = useAuth();
  const { theme, toggle: toggleTheme } = useTheme();
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
  const [period, setPeriod] = useState('6mo');
  const [interval, setChartInterval] = useState('1d');
  const [prepost, setPrepost] = useState(false);
  const [subTab, setSubTab] = useState('overview');

  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash.slice(1);
      if (VALID_TABS.includes(hash)) setActiveTab(hash);
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

  const tabs = [
    { id: 'dashboard', label: '📊 Dashboard' },
    { id: 'screener', label: '🔍 Screener' },
    { id: 'portfolio', label: '💼 Portfolio' },
    { id: 'tools', label: '🧰 Tools' },
  ];

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <h1 onClick={() => { setActiveTab('dashboard'); window.location.hash = 'dashboard'; }} style={{ cursor: 'pointer' }}><span className="header-emoji">📈</span><span className="header-title-text">Stock Insights</span></h1>
          <div className="user-menu">
            <button className="btn-theme" onClick={toggleTheme} title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
              {theme === 'dark' ? '☀️' : '🌙'}
            </button>
            {user ? (
              <>
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
              <div className="dashboard-welcome">
                <div className="dashboard-welcome-icon">📈</div>
                <h2>Search a stock to get started</h2>
                <p>Enter any ticker symbol above, or click one from your watchlist on the right.</p>
              </div>
            )}

            {ticker && metrics && (
              <>
                {/* ── Sub-tab navigation ──────────────────────── */}
                <nav className="sub-tabs">
                  {[
                    { id: 'overview', label: '📋 Overview' },
                    { id: 'analysis', label: '🔬 Analysis' },
                    { id: 'fundamentals', label: '📑 Fundamentals' },
                    { id: 'news', label: '📰 News & AI' },
                  ].map(t => (
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
                    <WhyMoving ticker={ticker} changePct={metrics.change_pct} />
                    <PriceChart data={history} events={events}
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
                  </>
                )}

                {/* ── Analysis ────────────────────────────────── */}
                {subTab === 'analysis' && (
                  <>
                    <AnalystRatings ticker={ticker} />
                    <PeerBenchmark ticker={ticker} />
                    <div className="two-column">
                      <BullBear ticker={ticker} />
                      <AiChat ticker={ticker} context={metrics} />
                    </div>
                  </>
                )}

                {/* ── Fundamentals ────────────────────────────── */}
                {subTab === 'fundamentals' && (
                  <>
                    <Financials ticker={ticker} />
                    <div className="two-column">
                      <Ownership ticker={ticker} />
                      <DividendHistory ticker={ticker} />
                    </div>
                  </>
                )}

                {/* ── News & AI ───────────────────────────────── */}
                {subTab === 'news' && (
                  <>
                    <div className="two-column">
                      <NewsSentiment newsData={newsData} />
                      <AiSummary ticker={ticker} dataReady={!loading} />
                    </div>
                  </>
                )}
              </>
            )}
          </div>
          <WatchlistRail
            activeTicker={ticker}
            onSelect={(t) => handleSearch(t)}
            onGoToScreener={() => handleTabClick('screener')}
          />
        </div>
      )}

      {activeTab === 'screener' && <Screener />}

      {activeTab === 'portfolio' && <Portfolio />}

      {activeTab === 'tools' && (
        <div className="tools-page">
          <h2 className="tools-heading">🧰 Trading Tools</h2>
          <p className="tools-subheading">Calculators and simulators to help plan your trades.</p>
          <div className="tools-grid">
            <PositionCalculator />
            <DcaSimulator />
          </div>
        </div>
      )}

      <footer className="app-footer">
        Data from Yahoo Finance &middot; News from NewsAPI &middot; AI by Groq &middot; Not financial advice
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
        <App />
      </AuthProvider>
    </ThemeProvider>
  );
}
