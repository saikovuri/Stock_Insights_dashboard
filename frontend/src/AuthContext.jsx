import { createContext, useContext, useState, useEffect } from 'react';
import { API_BASE } from './api/config';
import { fetchCurrentUser } from './api/stockApi';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [loading, setLoading] = useState(true);
  const [sessionError, setSessionError] = useState(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    if (localStorage.getItem('token')) {
      const timeout = setTimeout(() => controller.abort(), 60000);
      fetchCurrentUser(controller.signal)
        .then(current => { if (active) setUser(current); })
        .catch(error => {
          if (!active) return;
          if (error.status === 401 || error.status === 403) {
            localStorage.removeItem('token'); localStorage.removeItem('refresh_token'); setToken(null); setUser(null);
          } else setSessionError(error.message);
        })
        .finally(() => { clearTimeout(timeout); if (active) setLoading(false); });
    } else {
      setLoading(false);
    }
    return () => { active = false; controller.abort(); };
  }, []);

  useEffect(() => {
    const sync = () => {
      const current = localStorage.getItem('token');
      setToken(current);
      if (!current) setUser(null);
    };
    window.addEventListener('stockpilot:auth', sync);
    return () => window.removeEventListener('stockpilot:auth', sync);
  }, []);

  const login = async (username, password) => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Login failed');
    }
    const data = await res.json();
    localStorage.setItem('token', data.token);
    localStorage.setItem('refresh_token', data.refresh_token);
    setToken(data.token);
    setUser(data.user);
  };

  const register = async (username, password, displayName) => {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, display_name: displayName }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Registration failed');
    }
    const data = await res.json();
    localStorage.setItem('token', data.token);
    localStorage.setItem('refresh_token', data.refresh_token);
    setToken(data.token);
    setUser(data.user);
  };

  const logout = async () => {
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch { /* ignore */ }
    localStorage.removeItem('token');
    localStorage.removeItem('refresh_token');
    sessionStorage.clear();
    setSessionError(null);
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout }}>
      {sessionError && !user ? <main className="card" role="alert">
        <h2>Session unavailable</h2><p>{sessionError}</p>
        <button onClick={() => window.location.reload()}>Retry</button>
        <button onClick={logout}>Sign out</button>
      </main> : children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
