import { API_BASE } from './config';

const BASE = API_BASE;

function authHeaders() {
  const token = localStorage.getItem('token');
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

/**
 * Wrapper around fetch that auto-refreshes the access token on 401.
 * If the refresh itself fails, clears auth and reloads.
 */
let _refreshPromise = null;
async function authFetch(url, opts = {}) {
  opts.headers = opts.headers || authHeaders();
  let res = await fetch(url, opts);
  if (res.status === 401 && localStorage.getItem('refresh_token')) {
    // Deduplicate concurrent refresh attempts
    if (!_refreshPromise) {
      _refreshPromise = fetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: localStorage.getItem('refresh_token') }),
      }).then(async (r) => {
        if (!r.ok) throw new Error('refresh failed');
        return r.json();
      }).finally(() => { _refreshPromise = null; });
    }
    try {
      const data = await _refreshPromise;
      localStorage.setItem('token', data.token);
      localStorage.setItem('refresh_token', data.refresh_token);
      // Retry original request with new token
      opts.headers['Authorization'] = `Bearer ${data.token}`;
      res = await fetch(url, opts);
    } catch {
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      window.location.reload();
      throw new Error('Session expired');
    }
  }
  return res;
}

export async function fetchMetrics(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/metrics`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to fetch metrics');
  return res.json();
}

export async function fetchHistory(ticker, period = '6mo', interval = '1d', prepost = false) {
  const pp = prepost ? '&prepost=true' : '';
  const res = await fetch(`${BASE}/stock/${ticker}/history?period=${period}&interval=${interval}${pp}`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to fetch history');
  return res.json();
}

export async function fetchNews(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/news`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to fetch news');
  return res.json();
}

export async function fetchSummary(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/summary`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to fetch summary');
  return res.json();
}

export async function fetchAlerts(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/alerts`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to fetch alerts');
  return res.json();
}

export async function fetchPortfolioSummary() {
  const res = await authFetch(`${BASE}/portfolio/summary`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch portfolio');
  return res.json();
}

export async function buyStock(ticker, shares, price) {
  const res = await authFetch(`${BASE}/portfolio/buy`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, shares, price }),
  });
  if (!res.ok) throw new Error('Failed to buy');
  return res.json();
}

export async function sellStock(ticker, shares, price) {
  const res = await authFetch(`${BASE}/portfolio/sell`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, shares, price }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to sell');
  return res.json();
}

export async function sellStockLot(holdingId, ticker, shares, price) {
  const res = await authFetch(`${BASE}/portfolio/sell-lot/${holdingId}`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, shares, price }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to sell lot');
  return res.json();
}

// ── Options ──────────────────────────────────────────────────────
export async function fetchOptionsSummary() {
  const res = await authFetch(`${BASE}/portfolio/options/summary`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch options');
  return res.json();
}

export async function buyOption(ticker, option_type, strike, expiry, premium, contracts, position = 'long') {
  const res = await authFetch(`${BASE}/portfolio/options/buy`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, option_type, strike, expiry, premium, contracts, position }),
  });
  if (!res.ok) throw new Error('Failed to buy option');
  return res.json();
}

export async function closeOption(ticker, option_type, strike, expiry, premium, contracts, position = 'long') {
  const res = await authFetch(`${BASE}/portfolio/options/close`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, option_type, strike, expiry, premium, contracts, position }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to close option');
  return res.json();
}

// ── Edit / Delete holdings ────────────────────────────────────────
export async function editHolding(id, ticker, shares, price) {
  const res = await authFetch(`${BASE}/portfolio/${id}`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ ticker, shares, price }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to edit holding');
  return res.json();
}

export async function deleteHolding(id) {
  const res = await authFetch(`${BASE}/portfolio/${id}`, { method: 'DELETE', headers: authHeaders() });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to delete holding');
  return res.json();
}

export async function editOption(id, ticker, option_type, strike, expiry, premium, contracts, position = 'long') {
  const res = await authFetch(`${BASE}/portfolio/options/${id}`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ ticker, option_type, strike, expiry, premium, contracts, position }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to edit option');
  return res.json();
}

export async function deleteOption(id) {
  const res = await authFetch(`${BASE}/portfolio/options/${id}`, { method: 'DELETE', headers: authHeaders() });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed to delete option');
  return res.json();
}

// ── Closed trades ────────────────────────────────────────────────
export async function fetchClosedTrades() {
  const res = await authFetch(`${BASE}/portfolio/closed`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch closed trades');
  return res.json();
}

export async function fetchClosedOptions() {
  const res = await authFetch(`${BASE}/portfolio/options/closed`, { headers: authHeaders() });
  if (!res.ok) throw new Error('Failed to fetch closed options');
  return res.json();
}

// ── New AI / analytical endpoints ────────────────────────────────
export async function fetchWhyMoving(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/why-moving`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
  return res.json();
}

export async function fetchBullBear(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/bull-bear`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
  return res.json();
}

export async function sendChat(ticker, messages, context) {
  const res = await fetch(`${BASE}/stock/${ticker}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages, context }),
  });
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
  return res.json();
}

export async function fetchPeers(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/peers`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
  return res.json();
}

export async function fetchEvents(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/events`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
  return res.json();
}

export async function fetchReturns(ticker, period = '3mo') {
  const res = await fetch(`${BASE}/stock/${ticker}/history-returns?period=${period}`);
  if (!res.ok) throw new Error((await res.json()).detail || 'Failed');
  return res.json();
}
