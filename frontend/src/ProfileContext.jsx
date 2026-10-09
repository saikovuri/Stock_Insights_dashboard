import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';
import { fetchProfile, saveProfile } from './api/stockApi';

// hide: dashboard cards not shown for this style (a "show all" toggle reveals them)
// options: option-hub tabs in priority order
export const PROFILES = {
  day: {
    label: 'Day trader', icon: '⚡',
    chart: { period: '1d', interval: '5m' },
    subTabs: ['overview', 'analysis', 'news', 'fundamentals'],
    hide: ['thesis', 'longterm', 'financials', 'ownership'],
    options: ['volatility', 'directional', 'income'],
  },
  swing: {
    label: 'Swing trader', icon: '🌊',
    chart: { period: '6mo', interval: '1d' },
    subTabs: ['overview', 'analysis', 'fundamentals', 'news'],
    hide: ['financials'],
    options: ['volatility', 'directional', 'income'],
  },
  long: {
    label: 'Long-term investor', icon: '🌳',
    chart: { period: '5y', interval: '1wk' },
    subTabs: ['overview', 'fundamentals', 'news', 'analysis'],
    hide: ['rs'],
    options: ['income', 'volatility'],
  },
};

export const ALL_OPTION_TABS = ['volatility', 'income', 'directional'];

const KEY = 'trader_profile';
const ProfileContext = createContext(null);

export function ProfileProvider({ children }) {
  const { user } = useAuth();
  const [profile, setProfileState] = useState(() => {
    const p = localStorage.getItem(KEY);
    return PROFILES[p] ? p : 'swing';
  });

  useEffect(() => {
    if (!user) return;
    fetchProfile()
      .then(({ profile: server }) => {
        if (server && PROFILES[server]) {
          setProfileState(server);
          localStorage.setItem(KEY, server);
        } else {
          saveProfile(localStorage.getItem(KEY) || 'swing').catch(() => {});
        }
      })
      .catch(() => {});
  }, [user]);

  const setProfile = useCallback((p) => {
    if (!PROFILES[p]) return;
    setProfileState(p);
    localStorage.setItem(KEY, p);
    if (user) saveProfile(p).catch(() => {});
  }, [user]);

  return <ProfileContext.Provider value={{ profile, setProfile, config: PROFILES[profile] }}>{children}</ProfileContext.Provider>;
}

export function useProfile() {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error('useProfile must be used within ProfileProvider');
  return ctx;
}
