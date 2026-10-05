import { API_BASE } from './config';

const BASE = API_BASE;

async function readError(res, fallback) {
  let payload = null;

  try {
    payload = await res.json();
  } catch {
    payload = null;
  }

  if (res.status === 429) {
    return payload?.detail || 'Rate limited. Try again in a minute.';
  }

  if (Array.isArray(payload?.detail)) return payload.detail.map(item => `${item.loc?.at(-1) || 'Input'}: ${item.msg}`).join('; ');
  return payload?.detail || payload?.message || fallback;
}

function authHeaders() {
  const token = localStorage.getItem('token');
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

// fetch() throws a bare TypeError ("Failed to fetch") when the server is unreachable or drops the request
async function netFetch(url, opts) {
  try {
    return await fetch(url, { ...opts, signal: opts?.signal || AbortSignal.timeout(60000) });
  } catch (e) {
    if (e instanceof TypeError) {
      throw new Error("Couldn't reach the server — it may be waking up or busy. Please try again in a moment.");
    }
    throw e;
  }
}

let _refreshState = null;

function currentCredentials(credentials) {
  return localStorage.getItem('token') === credentials.token
    && localStorage.getItem('refresh_token') === credentials.refresh_token;
}

export async function authFetch(url, opts = {}) {
  const credentials = { token: localStorage.getItem('token'), refresh_token: localStorage.getItem('refresh_token') };
  opts = { ...opts, headers: { ...opts.headers, ...authHeaders() } };
  let res = await netFetch(url, opts);
  if (res.status === 401 && credentials.refresh_token) {
    let state = _refreshState;
    if (!state || state.credentials.token !== credentials.token
        || state.credentials.refresh_token !== credentials.refresh_token
        || !currentCredentials(state.result ?? state.credentials)) {
      if (!currentCredentials(credentials)) throw new Error('Session changed. Retry from the current account.');
      const pending = { credentials, result: null, promise: null };
      _refreshState = pending;
      pending.promise = netFetch(`${BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: credentials.refresh_token }),
      }).then(async (response) => {
        if (!response.ok) {
          const error = new Error(response.status === 401 || response.status === 403 ? 'Session expired' : 'Session refresh unavailable. Retry shortly.');
          error.status = response.status;
          throw error;
        }
        const data = await response.json();
        if (!currentCredentials(credentials)) throw new Error('Session changed. Retry from the current account.');
        if (typeof data.token !== 'string' || !data.token || typeof data.refresh_token !== 'string' || !data.refresh_token) {
          throw new Error('Session refresh unavailable. Retry shortly.');
        }
        localStorage.setItem('token', data.token);
        localStorage.setItem('refresh_token', data.refresh_token);
        pending.result = data;
        window.dispatchEvent(new Event('stockpilot:auth'));
        return data;
      }).catch(error => {
        if (_refreshState === pending) _refreshState = null;
        if (currentCredentials(credentials) && (error.status === 401 || error.status === 403)) {
          localStorage.removeItem('token');
          localStorage.removeItem('refresh_token');
          sessionStorage.clear();
          window.dispatchEvent(new Event('stockpilot:auth'));
        }
        throw error;
      });
      state = pending;
    }
    const data = await state.promise;
    if (!currentCredentials(data)) throw new Error('Session changed. Retry from the current account.');
    opts.headers['Authorization'] = `Bearer ${data.token}`;
    res = await netFetch(url, opts);
  }
  return res;
}

export async function fetchCurrentUser(signal) {
  const response = await authFetch(`${BASE}/auth/me`, { signal });
  if (!response.ok) {
    const error = new Error(await readError(response, 'Could not load your session.'));
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export async function fetchMetrics(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/metrics`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch metrics'));
  return res.json();
}

export async function fetchHistory(ticker, period = '6mo', interval = '1d', prepost = false) {
  const pp = prepost ? '&prepost=true' : '';
  const res = await fetch(`${BASE}/stock/${ticker}/history?period=${period}&interval=${interval}${pp}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch history'));
  return res.json();
}

export async function fetchNews(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/news`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch news'));
  return res.json();
}

export async function fetchAlerts(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/alerts`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch alerts'));
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
  if (!res.ok) throw new Error(await readError(res, 'Failed to sell'));
  return res.json();
}

export async function sellStockLot(holdingId, ticker, shares, price) {
  const res = await authFetch(`${BASE}/portfolio/sell-lot/${holdingId}`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, shares, price }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed to sell lot'));
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

export async function closeOption(ticker, option_type, strike, expiry, premium, contracts, position = 'long', option_id = null) {
  const res = await authFetch(`${BASE}/portfolio/options/close`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ ticker, option_type, strike, expiry, premium, contracts, position, option_id }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed to close option'));
  return res.json();
}

// ── Edit / Delete holdings ────────────────────────────────────────
export async function editHolding(id, ticker, shares, price) {
  const res = await authFetch(`${BASE}/portfolio/${id}`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ ticker, shares, price }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed to edit holding'));
  return res.json();
}

export async function deleteHolding(id) {
  const res = await authFetch(`${BASE}/portfolio/${id}`, { method: 'DELETE', headers: authHeaders() });
  if (!res.ok) throw new Error(await readError(res, 'Failed to delete holding'));
  return res.json();
}

export async function editOption(id, ticker, option_type, strike, expiry, premium, contracts, position = 'long') {
  const res = await authFetch(`${BASE}/portfolio/options/${id}`, {
    method: 'PUT', headers: authHeaders(),
    body: JSON.stringify({ ticker, option_type, strike, expiry, premium, contracts, position }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed to edit option'));
  return res.json();
}

export async function deleteOption(id) {
  const res = await authFetch(`${BASE}/portfolio/options/${id}`, { method: 'DELETE', headers: authHeaders() });
  if (!res.ok) throw new Error(await readError(res, 'Failed to delete option'));
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

export async function logClosedOption(payload) {
  const res = await authFetch(`${BASE}/portfolio/options/closed`, { method: 'POST', body: JSON.stringify(payload) });
  if (!res.ok) throw new Error(await readError(res, 'Failed to record closed option'));
  return res.json();
}

export async function updateClosedOption(id, payload) {
  const res = await authFetch(`${BASE}/portfolio/options/closed/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
  if (!res.ok) throw new Error(await readError(res, 'Failed to update closed option'));
  return res.json();
}

// ── AI (sign-in required) ────────────────────────────────────────
export async function fetchBrief(ticker, profile) {
  const res = await authFetch(`${BASE}/stock/${ticker}/brief${profile ? `?profile=${profile}` : ''}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load AI brief'));
  return res.json();
}

export async function sendChat(ticker, messages) {
  const res = await authFetch(`${BASE}/stock/${ticker}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed'));
  return res.json();
}

export async function fetchPortfolioDoctor() {
  const res = await authFetch(`${BASE}/portfolio/doctor`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to run portfolio check'));
  return res.json();
}

export async function fetchBriefing(refresh = false) {
  const res = await authFetch(`${BASE}/briefing${refresh ? '?refresh=true' : ''}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load briefing'));
  return res.json();
}

// ── Notifications ────────────────────────────────────────────────
export async function fetchNotifications() {
  const res = await authFetch(`${BASE}/notifications`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load notifications'));
  return res.json();
}

export async function markNotificationsRead() {
  const res = await authFetch(`${BASE}/notifications/read`, { method: 'POST', headers: authHeaders() });
  if (!res.ok) throw new Error(await readError(res, 'Failed'));
  return res.json();
}

export async function fetchNotificationSettings() {
  const res = await authFetch(`${BASE}/notifications/settings`);
  if (!res.ok) throw new Error(await readError(res, 'Failed'));
  return res.json();
}

export async function saveNotificationSettings(ntfy_topic) {
  const res = await authFetch(`${BASE}/notifications/settings`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ ntfy_topic }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed to save'));
  return res.json();
}

export async function fetchPeers(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/peers`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load peers'));
  return res.json();
}

export async function fetchEvents(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/events`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load events'));
  return res.json();
}

export async function fetchReturns(ticker, period = '3mo') {
  const res = await fetch(`${BASE}/stock/${ticker}/history-returns?period=${period}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load returns'));
  return res.json();
}

export async function fetchAnalyst(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/analyst`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load analyst ratings'));
  return res.json();
}

export async function fetchFinancials(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/financials`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load financials'));
  return res.json();
}

export async function fetchOwnership(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/ownership`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load ownership'));
  return res.json();
}

export async function fetchDividends(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/dividends`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load dividends'));
  return res.json();
}

export async function fetchBatchSparklines(tickers) {
  const res = await fetch(`${BASE}/stock/batch-sparklines`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tickers }),
  });
  if (!res.ok) throw new Error(await readError(res, 'Failed to load sparklines'));
  return res.json();
}

export async function fetchIvRank(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/iv-rank`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch IV rank'));
  return res.json();
}

export async function fetchIncomeIdeas(ticker, expiry) {
  const q = expiry ? `?expiry=${encodeURIComponent(expiry)}` : '';
  const res = await fetch(`${BASE}/stock/${ticker}/income${q}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch income ideas'));
  return res.json();
}

export async function fetchOptionExpirations(ticker) {
  const res = await fetch(`${BASE}/stock/${ticker}/option-expirations`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load listed expiries'));
  return res.json();
}

export async function fetchAssignedCalls(ticker, costBasis, shares, cadence = 'all') {
  const params = new URLSearchParams({ cost_basis: String(costBasis), shares: String(shares), cadence });
  const res = await fetch(`${BASE}/stock/${ticker}/assigned-calls?${params}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to load covered calls'));
  return res.json();
}

export async function fetchRollIdeas(ticker, { strategy, expiry, shortStrike, longStrike, credit }) {
  const params = new URLSearchParams({ strategy, expiry, short_strike: String(shortStrike) });
  if (strategy === 'pcs' && longStrike) params.set('long_strike', String(longStrike));
  if (credit !== '' && credit != null) params.set('credit', String(credit));
  const res = await fetch(`${BASE}/stock/${ticker}/roll?${params}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to find rolls'));
  return res.json();
}

async function getJson(url, fallback, auth = false) {
  const res = auth ? await authFetch(url) : await netFetch(url);
  if (!res.ok) throw new Error(await readError(res, fallback));
  return res.json();
}

async function sendJson(url, method, body, fallback) {
  const res = await authFetch(url, { method, headers: authHeaders(), body: body ? JSON.stringify(body) : undefined });
  if (!res.ok) throw new Error(await readError(res, fallback));
  return res.json();
}

// ── Profile & custom alerts ──────────────────────────────────────
export const askWheel = (ticker) =>
  sendJson(`${BASE}/ideas/wheel/ask/${encodeURIComponent(ticker)}`, 'POST', null, 'Could not analyze that ticker');
export const fetchProfile = () => getJson(`${BASE}/profile`, 'Failed to load profile', true);
export const saveProfile = (profile) => sendJson(`${BASE}/profile`, 'PUT', { profile }, 'Failed to save profile');
export const fetchCustomAlerts = (ticker) =>
  getJson(`${BASE}/alerts/custom${ticker ? `?ticker=${encodeURIComponent(ticker)}` : ''}`, 'Failed to load alerts', true);
export const addCustomAlert = (alert) => sendJson(`${BASE}/alerts/custom`, 'POST', alert, 'Failed to add alert');
export const deleteCustomAlert = (id) => sendJson(`${BASE}/alerts/custom/${id}`, 'DELETE', null, 'Failed to delete alert');

// ── Market ───────────────────────────────────────────────────────
export const fetchMarketOverview = () => getJson(`${BASE}/market/overview`, 'Failed to load market overview');
export const fetchMovers = (kind) => getJson(`${BASE}/market/movers?kind=${kind}`, 'Failed to load movers');
export const fetchMyEarnings = () => getJson(`${BASE}/market/my-earnings`, 'Failed to load earnings', true);

// ── Earnings, scanner, fundamentals ──────────────────────────────
export const fetchEarningsIntel = (t) => getJson(`${BASE}/stock/${t}/earnings-intel`, 'Failed to load earnings history');
export const fetchEarningsRelease = (t) => getJson(`${BASE}/stock/${t}/earnings-release`, 'Failed to load press release', true);
export const fetchScanner = () => getJson(`${BASE}/scanner`, 'Failed to load scanner');
export const fetchRelativeStrength = (t) => getJson(`${BASE}/stock/${t}/rs`, 'Failed to load relative strength');
export const fetchLongTerm = (t) => getJson(`${BASE}/stock/${t}/longterm`, 'Failed to load long-term data');

// ── Journal ──────────────────────────────────────────────────────
export const fetchJournal = () => getJson(`${BASE}/journal`, 'Failed to load journal', true);
export const addJournalEntry = (e) => sendJson(`${BASE}/journal`, 'POST', e, 'Failed to save trade');
export const updateJournalEntry = (id, e) => sendJson(`${BASE}/journal/${id}`, 'PUT', e, 'Failed to update trade');
export const deleteJournalEntry = (id) => sendJson(`${BASE}/journal/${id}`, 'DELETE', null, 'Failed to delete trade');
export const fetchJournalCoach = () => getJson(`${BASE}/journal/coach`, 'Failed to load coaching', true);

// ── Options flow, macro, smart money ─────────────────────────────
export const fetchOptionsFlow = (t) => getJson(`${BASE}/stock/${t}/flow`, 'Failed to load options flow');
export const fetchUnusualOptions = () => getJson(`${BASE}/ideas/unusual-options`, 'Failed to load unusual options');
export const fetchWheelIdeas = (shortDated = false) => getJson(`${BASE}/ideas/wheel?short_dated=${shortDated}`, 'Failed to load wheel candidates');
export const fetchEconomicCalendar = (days = 7) => getJson(`${BASE}/market/calendar?days=${days}`, 'Failed to load calendar');
export const fetchMarketContext = (kind) => getJson(`${BASE}/market/context/${kind}`, 'Market context is unavailable');
export const fetchShortInterest = (t) => getJson(`${BASE}/stock/${t}/short-interest`, 'No short interest data');
export const fetchInsiderBuying = () => getJson(`${BASE}/ideas/insiders`, 'Failed to load insider buying');
export const fetchSuperinvestors = () => getJson(`${BASE}/ideas/superinvestors`, 'Failed to load superinvestors');
export const fetchSmartMoney = (t) => getJson(`${BASE}/stock/${t}/smart-money`, 'Failed to load smart money');

// ── Portfolio insights ───────────────────────────────────────────
export const fetchPerformance = () => getJson(`${BASE}/portfolio/performance`, 'Failed to load performance', true);
export const fetchDividendIncome = () => getJson(`${BASE}/portfolio/dividends`, 'Failed to load dividend income', true);
export const fetchTaxWarnings = () => getJson(`${BASE}/portfolio/tax`, 'Failed to load tax check', true);

// ── Options desk & track record ──────────────────────────────────
export const fetchOptionActions = () => getJson(`${BASE}/portfolio/options/actions`, 'Failed to check positions', true);
export const fetchPortfolioEarnings = () => getJson(`${BASE}/portfolio/earnings`, 'Failed to load earnings', true);
export const fetchWheelLedger = () => getJson(`${BASE}/portfolio/wheel-ledger`, 'Failed to load wheel ledger', true);
export const fetchOptionsReview = () => getJson(`${BASE}/portfolio/options/review`, 'Failed to load review', true);
export const fetchOptionsCoach = () => getJson(`${BASE}/portfolio/options/coach`, 'Failed to load AI review', true);
export const fetchTrackRecord = () => getJson(`${BASE}/ideas/track-record`, 'Failed to load track record');
export const fetchWheelPlan = (capital, maxPct, maxPerSector, shortDated = false) =>
  getJson(`${BASE}/ideas/wheel/plan?capital=${capital}&max_pct=${maxPct}&max_per_sector=${maxPerSector}&short_dated=${shortDated}`, 'Failed to build plan', true);
export const fetchEarningsMoves = (t) => getJson(`${BASE}/stock/${t}/earnings-moves`, 'Failed to load earnings moves');
export const assignOption = (id) => sendJson(`${BASE}/portfolio/options/${id}/assign`, 'POST', null, 'Could not record assignment');
export const deleteClosedTrade = (id) => sendJson(`${BASE}/portfolio/closed/${id}`, 'DELETE', null, 'Failed to delete trade');
export const deleteClosedOption = (id) => sendJson(`${BASE}/portfolio/options/closed/${id}`, 'DELETE', null, 'Failed to delete trade');
export const fetchPremiumIncome = () => getJson(`${BASE}/portfolio/premium-income`, 'Failed to load premium income', true);
export const saveIncomeGoal = (goal) => sendJson(`${BASE}/portfolio/income-goal`, 'PUT', { goal }, 'Failed to save goal');
export const importPortfolioCsv = (csv, commit) =>
  sendJson(`${BASE}/portfolio/import`, 'POST', { csv, commit }, 'Import failed');
export const fetchWeeklyReview = (refresh = false) =>
  getJson(`${BASE}/weekly-review${refresh ? '?refresh=true' : ''}`, 'Failed to load weekly review', true);

// ── Day trading ──────────────────────────────────────────────────
export const fetchKeyLevels = (t) => getJson(`${BASE}/stock/${t}/levels`, 'Failed to load levels');
export const fetchInPlay = (universe = 'all') => getJson(`${BASE}/ideas/in-play?universe=${universe}`, 'Failed to load stocks in play');
export const fetchBacktestStrategies = () => getJson(`${BASE}/backtest/strategies`, 'Failed to load strategies');
export const runBacktest = (opts) => {
  const q = new URLSearchParams();
  Object.entries(opts).forEach(([k, v]) => { if (v !== '' && v != null) q.set(k, v); });
  return getJson(`${BASE}/backtest?${q}`, 'Backtest failed');
};
export const compareBacktests = (ticker, timeframe, cost_bps) =>
  getJson(`${BASE}/backtest/compare?${new URLSearchParams({ ticker, timeframe, cost_bps })}`, 'Comparison failed');

// ── Theses ───────────────────────────────────────────────────────
export const fetchThesis = (t) => getJson(`${BASE}/thesis/${t}`, 'Failed to load thesis', true);
export const saveThesis = (t, thesis) => sendJson(`${BASE}/thesis/${t}`, 'PUT', { thesis }, 'Failed to save thesis');
export const deleteThesis = (t) => sendJson(`${BASE}/thesis/${t}`, 'DELETE', null, 'Failed to delete thesis');
export const checkThesis = (t) => sendJson(`${BASE}/thesis/${t}/check`, 'POST', null, 'Thesis check failed');

export async function fetchStructures(ticker, direction, budget, risk) {
  const params = new URLSearchParams({ direction, budget: String(budget), risk });
  const res = await fetch(`${BASE}/stock/${ticker}/structures?${params}`);
  if (!res.ok) throw new Error(await readError(res, 'Failed to fetch structures'));
  return res.json();
}
