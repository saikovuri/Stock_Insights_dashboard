import { useState } from 'react';
import { useAuth } from '../AuthContext';

export default function LoginPage({ onBack }) {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        await register(username, password, displayName || username);
      } else {
        await login(username, password);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-header">
          <h1>📈 Stock Insights</h1>
          <p>Sign in to save your portfolio &amp; watchlist</p>
        </div>

        {onBack && (
          <button className="btn-back-guest" onClick={onBack}>
            ← Continue as Guest
          </button>
        )}

        <div className="login-tabs">
          <button
            className={!isRegister ? 'active' : ''}
            onClick={() => { setIsRegister(false); setError(''); }}
          >
            Sign In
          </button>
          <button
            className={isRegister ? 'active' : ''}
            onClick={() => { setIsRegister(true); setError(''); }}
          >
            Create Account
          </button>
        </div>

        <form onSubmit={handleSubmit} className="login-form">
          {isRegister && (
            <div className="form-group">
              <label>Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="How should we call you?"
                autoComplete="name"
              />
            </div>
          )}

          <div className="form-group">
            <label>Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              placeholder="Enter username"
              required
              autoComplete="username"
            />
          </div>

          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder={isRegister ? 'Min 6 characters' : 'Enter password'}
              required
              autoComplete={isRegister ? 'new-password' : 'current-password'}
            />
          </div>

          {error && <div className="login-error">{error}</div>}

          <button type="submit" className="login-submit" disabled={loading}>
            {loading ? '...' : isRegister ? 'Create Account' : 'Sign In'}
          </button>
        </form>

        <div className="login-footer">
          <p>Data from Yahoo Finance &middot; Not financial advice</p>
        </div>
      </div>
    </div>
  );
}
