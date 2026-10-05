// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { authFetch } from './api/stockApi';
import { calculatePosition } from './components/PositionCalculator';
import { pnlAt } from './components/OptionsDesk';
import IncomeIdeas, { eligibleIncomeIdeas } from './components/IncomeIdeas';
import { alignedCorrelation } from './components/CorrelationHeatmap';
import { render, screen, fireEvent, cleanup, act, waitFor } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import * as auth from './AuthContext';
import StrategyTester from './components/StrategyTester';
import Portfolio from './components/Portfolio';
import Watchlist from './components/Watchlist';
import Structures from './components/Structures';
import Accounting from './components/Accounting';
import WheelIdeas from './components/WheelIdeas';
import MarketContext from './components/MarketContext';
import PreTradeChecklist from './components/PreTradeChecklist';
import Journal from './components/Journal';

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test.each([
  ['stock', 85, '$85', 'positive'], ['stock', -35, '-$35', 'negative'], ['stock', 0, '$0', ''],
  ['option', 85, '$85', 'positive'], ['option', -35, '-$35', 'negative'], ['option', 0, '$0', ''],
])('trade history colors %s gross P&L of %s', async (kind, pnl, formatted, color) => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchJournal').mockResolvedValue({ entries: [] });
  const trade = { id: 1, ticker: 'WDC', pnl, shares: 1, contracts: 1, position: 'short', option_type: 'put',
    strike: 65, expiry: '2025-09-19', closed_at: '2025-09-10' };
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: kind === 'stock' ? [trade] : [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: kind === 'option' ? [trade] : [] });
  render(<Journal />);
  const cell = await screen.findByRole('cell', { name: formatted, exact: true });
  expect(cell.className).toBe(color);
  const total = screen.getByText('Gross realized P&L:').querySelector('span');
  expect(total.className).toBe(color);
  expect(total.textContent).toBe(formatted);
});

test.each([['short', '0.35', 'Buy-back price ($/share)', 'Buy to Close'],
  ['long', '0.35', 'Closing sale price ($/share)', 'Sell to Close'],
  ['short', '0', 'Buy-back price ($/share)', 'Buy to Close']])(
  'option close accepts an actual %s fill of %s for the selected lot', async (position, price, label, action) => {
    vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'fixture' });
    vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 });
    vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
    vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
    vi.spyOn(stockApi, 'fetchOptionsSummary').mockResolvedValue({ total_cost: 120, total_value: null, total_pnl: null,
      options: [{ id: 42, ticker: 'WDC', type: 'put', position, strike: 65, expiry: '2027-01-15', dte: 100,
        contracts: 1, premium: 1.2, market_price: 0.6, current_price: null, pnl: null }] });
    const close = vi.spyOn(stockApi, 'closeOption').mockResolvedValue({ pnl: 85 });
    render(<Portfolio />);
    fireEvent.click(screen.getByRole('button', { name: /Options/ }));
    const launch = await screen.findByTitle('Close this option lot');
    screen.getByLabelText('Premium ($)').scrollIntoView = vi.fn();
    fireEvent.click(launch);
    const input = screen.getByLabelText(label);
    expect(input).toBe(document.activeElement);
    expect(input.value).toBe('');
    expect(screen.getByRole('button', { name: action, exact: true }).disabled).toBe(true);
    fireEvent.change(input, { target: { value: '-1' } });
    expect(screen.getByRole('button', { name: action, exact: true }).disabled).toBe(true);
    fireEvent.change(input, { target: { value: price } });
    expect(input.value).toBe(price);
    fireEvent.click(screen.getByRole('button', { name: action, exact: true }));
    await waitFor(() => expect(close).toHaveBeenCalledWith('WDC', 'put', 65, '2027-01-15', Number(price), 1, position, 42));
  });

async function openClosedOptionForm() {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchJournal').mockResolvedValue({ entries: [] });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
  render(<Journal />);
  fireEvent.click(screen.getByRole('button', { name: 'Manual journal' }));
  fireEvent.click(screen.getByRole('button', { name: 'Log closed option' }));
  for (const [label, value] of Object.entries({ 'Option ticker': 'wdc', 'Strike ($)': '65', Expiry: '2025-09-19',
    'Opened on': '2025-09-01', 'Closed on': '2025-09-10', 'Opening premium ($/share)': '1.20',
    'Closing premium ($/share)': '0.35', 'Total fees ($, both sides)': '1.30', 'Option notes': 'Closed early' })) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
  await screen.findByText('No closed options recorded.');
}

test('closed option journal previews net profit and retries the same canonical entry', async () => {
  const log = vi.spyOn(stockApi, 'logClosedOption').mockRejectedValueOnce(new Error('Temporary failure')).mockResolvedValue({ id: 12 });
  const stockJournal = vi.spyOn(stockApi, 'addJournalEntry');
  await openClosedOptionForm();
  expect(screen.getByLabelText('Option P&L preview').textContent).toContain('$85');
  expect(screen.getByLabelText('Option P&L preview').textContent).toContain('$83.7');
  fireEvent.click(screen.getByRole('button', { name: 'Record closed option' }));
  await screen.findByText('Temporary failure');
  const first = log.mock.calls[0][0];
  expect(first).toMatchObject({ ticker: 'WDC', position: 'short', option_type: 'put', contracts: 1,
    open_premium: '1.20', close_premium: '0.35', fees: '1.30', notes: 'Closed early', opened_at: '2025-09-01', closed_at: '2025-09-10' });
  expect(first.idempotency_key).toBeTruthy();
  stockApi.fetchClosedOptions.mockResolvedValue({ trades: [{ ...first, id: 12, pnl: 85, net_pnl: 83.7, fees: 1.3 }] });
  fireEvent.click(screen.getByRole('button', { name: 'Record closed option' }));
  await screen.findByText('WDC closed option recorded.');
  expect(log.mock.calls[1][0]).toEqual(first);
  expect(stockJournal).not.toHaveBeenCalled();
  await screen.findByText('WDC');
  expect(screen.getByText('$83.7')).toBeTruthy();
});

test('manual option corrections prefill the trade, retry updates and confirm deletion', async () => {
  const create = vi.spyOn(stockApi, 'logClosedOption').mockResolvedValue({ id: 12 });
  const update = vi.spyOn(stockApi, 'updateClosedOption').mockRejectedValueOnce(new Error('Update unavailable')).mockResolvedValue({ id: 12 });
  const remove = vi.spyOn(stockApi, 'deleteClosedOption').mockRejectedValueOnce(new Error('Delete unavailable')).mockResolvedValue({ ok: true });
  await openClosedOptionForm();
  const trade = { id: 12, is_manual: true, ticker: 'WDC', option_type: 'put', position: 'short', strike: 65,
    expiry: '2025-09-19', contracts: 1, open_premium: 1.2, close_premium: .35, opened_at: '2025-09-01',
    closed_at: '2025-09-10', fees: 1.3, pnl: 85, net_pnl: 83.7, notes: 'Original' };
  stockApi.fetchClosedOptions.mockResolvedValue({ trades: [trade] });
  fireEvent.click(screen.getByRole('button', { name: 'Record closed option' }));
  await screen.findByText('WDC closed option recorded.');
  fireEvent.click(await screen.findByRole('button', { name: 'Edit WDC option' }));
  expect(screen.getByLabelText('Closed on').value).toBe('2025-09-10');
  expect(screen.getByLabelText('Option notes').value).toBe('Original');
  fireEvent.change(screen.getByLabelText('Closing premium ($/share)'), { target: { value: '0.25' } });
  fireEvent.change(screen.getByLabelText('Total fees ($, both sides)'), { target: { value: '2.50' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save option changes' }));
  await screen.findByText('Update unavailable');
  expect(screen.getByLabelText('Closing premium ($/share)').value).toBe('0.25');
  stockApi.fetchClosedOptions.mockResolvedValue({ trades: [{ ...trade, close_premium: .25, fees: 2.5, pnl: 95, net_pnl: 92.5 }] });
  fireEvent.click(screen.getByRole('button', { name: 'Save option changes' }));
  await screen.findByText('WDC closed option updated.');
  expect(update.mock.calls[0][0]).toBe(12);
  expect(update.mock.calls[1]).toEqual(update.mock.calls[0]);
  expect(create).toHaveBeenCalledTimes(1);
  await screen.findByText('$92.5');
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Delete WDC option' }));
  expect(remove).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Delete WDC option' }));
  await screen.findByText('Delete unavailable');
  stockApi.fetchClosedOptions.mockResolvedValue({ trades: [] });
  fireEvent.click(screen.getByRole('button', { name: 'Delete WDC option' }));
  await screen.findByText('WDC closed option deleted.');
  await screen.findByText('No closed options recorded.');
  expect(remove).toHaveBeenLastCalledWith(12);
});

test('manual option date fields have explicit calendar controls and keyboard fallback', async () => {
  await openClosedOptionForm();
  for (const label of ['Expiry', 'Opened on', 'Closed on']) {
    const input = screen.getByLabelText(label);
    const picker = vi.fn();
    input.showPicker = picker;
    fireEvent.click(screen.getByRole('button', { name: `Open ${label.toLowerCase()} calendar` }));
    expect(picker).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(input);
    input.showPicker = undefined;
    fireEvent.click(screen.getByRole('button', { name: `Open ${label.toLowerCase()} calendar` }));
    expect(document.activeElement).toBe(input);
  }
});

test('closed option journal validates chronology and updates the direction of profit', async () => {
  await openClosedOptionForm();
  fireEvent.change(screen.getByLabelText('Position'), { target: { value: 'long' } });
  expect(screen.getByLabelText('Option P&L preview').textContent).toContain('-$86.3');
  fireEvent.change(screen.getByLabelText('Closed on'), { target: { value: '2025-08-31' } });
  expect(screen.getByRole('alert').textContent).toContain('precede opening date');
  expect(screen.getByRole('button', { name: 'Record closed option' }).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Closed on'), { target: { value: '2025-09-10' } });
  fireEvent.change(screen.getByLabelText('Contracts'), { target: { value: '1.5' } });
  expect(screen.getByRole('button', { name: 'Record closed option' }).disabled).toBe(true);
});

function fillTradeChecklist() {
  for (const [label, value] of Object.entries({ Ticker: 'AAPL', 'Thesis (1 sentence)': 'Review after earnings',
    'Time horizon': '1–4 weeks', 'IV rank check': 'Mid', 'Earnings before expiry?': 'No', Structure: 'Long call',
    'Max loss ($)': '100', 'Max loss as % of account': '1', 'Exit plan if RIGHT': 'Take profit at target',
    'Exit plan if WRONG': 'Exit on invalidation', 'What would invalidate the thesis?': 'Guidance cut' })) {
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  }
}

test('planning checklist reports completion, never trade approval, and clears stale results', () => {
  render(<PreTradeChecklist />);
  fireEvent.click(screen.getByRole('button', { name: 'Review checklist' }));
  expect(screen.getByText('Checklist incomplete.')).toBeTruthy();
  fillTradeChecklist();
  fireEvent.click(screen.getByRole('button', { name: 'Review checklist' }));
  expect(screen.getByText('Checklist complete.')).toBeTruthy();
  expect(screen.getByRole('status').textContent).toContain('not trade qualification');
  expect(screen.queryByText(/Cleared|Place the trade/)).toBeNull();
  fireEvent.change(screen.getByLabelText('Max loss ($)'), { target: { value: '0' } });
  expect(screen.queryByRole('status')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
  expect(screen.getByLabelText('Ticker').value).toBe('');
});

test.each([['Max loss ($)', '0'], ['Max loss ($)', '-1'], ['Max loss as % of account', '0'],
  ['Max loss as % of account', '-1'], ['Max loss as % of account', '101'], ['Ticker', 'not a ticker']])(
  'planning checklist rejects invalid %s: %s', (label, value) => {
    render(<PreTradeChecklist />);
    fillTradeChecklist();
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'Review checklist' }));
    expect(screen.queryByText('Checklist complete.')).toBeNull();
    expect(screen.getByRole('status').textContent).toContain('Invalid');
  });

test.each([['Max loss as % of account', '3', 'Risk guideline exceeded.'],
  ['IV rank check', 'High (avoid buying naked options)', 'High IV + long option.'],
  ['IV rank check', 'Did not check', 'No IV check.'],
  ['Earnings before expiry?', 'Yes — accidental (re-think)', 'Accidental earnings.']])(
  'planning checklist retains the warning for %s: %s', (label, value, warning) => {
    render(<PreTradeChecklist />);
    fillTradeChecklist();
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.click(screen.getByRole('button', { name: 'Review checklist' }));
    expect(screen.getByText(warning)).toBeTruthy();
    expect(screen.queryByText('Checklist complete.')).toBeNull();
  });

test('market attention keeps missing baselines unknown and opens ticker research', async () => {
  const onSelect = vi.fn();
  vi.spyOn(stockApi, 'fetchMarketContext').mockResolvedValue({ status: 'ready', fetched_at: '2026-10-05T12:00:00Z',
    rows: [{ ticker: 'PYPL', name: 'PayPal', mentions: 20, previous_mentions: 0, change_pct: null, url: 'https://apewisdom.io/stocks/PYPL/' }] });
  render(<MarketContext kind="attention" onSelect={onSelect} />);
  expect(await screen.findByText('No baseline')).toBeTruthy();
  expect(screen.getByText(/X is not connected/)).toBeTruthy();
  expect(screen.queryByText(/Infinity/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'PYPL' }));
  expect(onSelect).toHaveBeenCalledWith('PYPL');
});

test('prediction context uses percentage points and preserves unavailable liquidity', async () => {
  vi.spyOn(stockApi, 'fetchMarketContext').mockResolvedValue({ status: 'ready', fetched_at: '2026-10-05T12:00:00Z',
    rows: [{ id: '1', question: 'Fed cut?', yes_pct: 40, change_pp: -3, volume_24h: 2000, liquidity: null,
      end_at: '2026-10-29T00:00:00Z', updated_at: null, warnings: ['Liquidity unavailable'], url: 'https://polymarket.com/event/fed' }] });
  render(<MarketContext kind="predictions" />);
  expect(await screen.findByText('Yes 40%')).toBeTruthy();
  expect(screen.getByText('-3 pp')).toBeTruthy();
  expect(screen.getByText('Liquidity unavailable')).toBeTruthy();
  expect(screen.getByText(/Provider updated Unavailable/)).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Market and resolution rules' }).getAttribute('href')).toBe('https://polymarket.com/event/fed');
});

test('context ignores an old response after switching feeds and retries a network outage', async () => {
  let resolveOld;
  const fetch = vi.spyOn(stockApi, 'fetchMarketContext').mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }))
    .mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ status: 'ready', rows: [] });
  const view = render(<MarketContext kind="attention" />);
  view.rerender(<MarketContext kind="predictions" />);
  await screen.findByText(/Market context is unavailable/);
  await act(async () => resolveOld({ status: 'ready', rows: [{ ticker: 'OLD' }] }));
  expect(screen.queryByText('OLD')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  await screen.findByText('No qualifying records in the provider sample.');
  expect(fetch).toHaveBeenLastCalledWith('predictions');
});

test('wheel checkbox switches scans, ignores late results, and resets the capital plan', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: null });
  const snapshot = { rows: [], status: 'ready', target_delta: .15, screened: 500, quality_pool: 10 };
  let resolveStandard;
  const ideas = vi.spyOn(stockApi, 'fetchWheelIdeas')
    .mockReturnValueOnce(new Promise(resolve => { resolveStandard = resolve; }))
    .mockResolvedValue({ ...snapshot, screened: 200 });
  const plan = vi.spyOn(stockApi, 'fetchWheelPlan').mockResolvedValue({ picks: [], capital: 50000, cash_left: 50000,
    skipped_expensive: [], blocked: ['Short window plan'] });
  render(<WheelIdeas onSelect={() => {}} />);
  const toggle = screen.getByRole('checkbox', { name: 'Short-dated: 7–20 days' });
  expect(toggle.checked).toBe(false);
  expect(ideas).toHaveBeenCalledWith(false);
  fireEvent.click(toggle);
  await waitFor(() => expect(ideas).toHaveBeenCalledWith(true));
  await screen.findByText(/10 of 200 pass/);
  expect(screen.getByRole('checkbox', { name: 'Skip trades that hold through earnings' }).checked).toBe(true);
  expect(screen.getByText(/higher near-expiry gamma risk/)).toBeTruthy();
  await act(async () => resolveStandard(snapshot));
  expect(screen.queryByText(/10 of 500 pass/)).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Build plan' }));
  await screen.findByText('Short window plan');
  expect(plan).toHaveBeenCalledWith(50000, 25, 2, true);
  fireEvent.click(toggle);
  expect(screen.queryByText('Short window plan')).toBeNull();
  expect(screen.queryByText(/higher near-expiry gamma risk/)).toBeNull();
  await waitFor(() => expect(ideas).toHaveBeenLastCalledWith(false));
  fireEvent.click(screen.getByRole('button', { name: 'Build plan' }));
  await waitFor(() => expect(plan).toHaveBeenLastCalledWith(50000, 25, 2, false));
});

test('account ledger preserves idempotency on retry and displays missing TWR honestly', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  const submissions = [];
  vi.spyOn(stockApi, 'authFetch').mockImplementation(async (url, options) => {
    if (url.endsWith('/entries')) {
      submissions.push(JSON.parse(options.body));
      return new Response(JSON.stringify(submissions.length === 1 ? { detail: 'Temporary failure' } : { id: 1 }), { status: submissions.length === 1 ? 503 : 200 });
    }
    return new Response(JSON.stringify(url.endsWith('/report') ? { fees: 0, external_cash_flow: 0, dividends: 0,
      twr: { pct: null, reason: 'Opening and ending account valuations are required' }, manual_entries: [], tax_lots: [], cycles: [], notes: [] } : { events: [] }));
  });
  render(<Accounting />);
  expect(await screen.findByText('Unavailable')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Occurred at'), { target: { value: '2026-01-01T12:00' } });
  fireEvent.change(screen.getByLabelText('Amount ($)'), { target: { value: '3.25' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record entry' }));
  expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Temporary failure');
  fireEvent.click(screen.getByRole('button', { name: 'Record entry' }));
  await waitFor(() => expect(submissions).toHaveLength(2));
  expect(submissions[0]).toEqual(submissions[1]);
  expect(submissions[0].amount).toBe('3.25');
});

test.each(['response', 'body', 'error'])('watchlist ignores an old account %s after switching accounts', async phase => {
  const session = vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'first' });
  let resolveOld, rejectOld;
  const oldResponse = new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject; });
  vi.spyOn(stockApi, 'authFetch').mockReturnValueOnce(phase === 'body' ? Promise.resolve({ ok: true, json: () => oldResponse }) : oldResponse).mockResolvedValue(
    new Response(JSON.stringify({ stocks: [{ ticker: 'MSFT', name: 'New account', price: 100 }] })));
  const view = render(<Watchlist />);
  await act(async () => {});
  session.mockReturnValue({ user: { id: 2 }, token: 'second' });
  view.rerender(<Watchlist />);
  await screen.findByText('MSFT', { exact: true });
  await act(async () => {
    const data = { stocks: [{ ticker: 'AAPL', name: 'Old account', price: 100 }] };
    if (phase === 'error') rejectOld(new Error('Old account request failed'));
    else resolveOld(phase === 'body' ? data : new Response(JSON.stringify(data)));
  });
  expect(screen.queryByText('AAPL', { exact: true })).toBeNull();
  expect(screen.getByText('MSFT', { exact: true })).toBeTruthy();
  expect(sessionStorage.getItem('screener_cache:1')).toBeNull();
  expect(screen.queryByText('Old account request failed')).toBeNull();
});

test('guest metrics cannot overwrite an authenticated watchlist', async () => {
  localStorage.setItem('guest_watchlist', JSON.stringify(['AAPL']));
  const session = vi.spyOn(auth, 'useAuth').mockReturnValue({ user: null, token: null });
  let resolveGuest;
  vi.stubGlobal('fetch', vi.fn(() => new Promise(resolve => { resolveGuest = resolve; })));
  vi.spyOn(stockApi, 'authFetch').mockResolvedValue(new Response(JSON.stringify({ stocks: [{ ticker: 'MSFT', price: 100 }] })));
  const view = render(<Watchlist />);
  session.mockReturnValue({ user: { id: 2 }, token: 'second' });
  view.rerender(<Watchlist />);
  await screen.findByText('MSFT', { exact: true });
  await act(async () => { resolveGuest(new Response(JSON.stringify({ name: 'Guest stock', price: 100 }))); });
  expect(screen.queryByText('AAPL', { exact: true })).toBeNull();
  expect(screen.getByText('MSFT', { exact: true })).toBeTruthy();
});

test('old watchlist mutation does not trigger a refresh for the new account', async () => {
  const session = vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'first' });
  let resolveAdd;
  const addResponse = new Promise(resolve => { resolveAdd = resolve; });
  const request = vi.spyOn(stockApi, 'authFetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ stocks: [{ ticker: 'AAPL', price: 100 }] })))
    .mockReturnValueOnce(addResponse)
    .mockResolvedValueOnce(new Response(JSON.stringify({ stocks: [{ ticker: 'MSFT', price: 100 }] })));
  const view = render(<Watchlist />);
  await screen.findByText('AAPL', { exact: true });
  fireEvent.change(screen.getByPlaceholderText('Add ticker (e.g. AAPL)'), { target: { value: 'NVDA' } });
  fireEvent.click(screen.getByRole('button', { name: '+ Add' }));
  session.mockReturnValue({ user: { id: 2 }, token: 'second' });
  view.rerender(<Watchlist />);
  await screen.findByText('MSFT', { exact: true });
  await act(async () => { resolveAdd(new Response('{}')); });
  expect(request).toHaveBeenCalledTimes(3);
  expect(screen.getByText('MSFT', { exact: true })).toBeTruthy();
});

test('logout immediately clears watchlist rows and ignores pending requests', async () => {
  const session = vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'first' });
  sessionStorage.setItem('screener_cache:1', JSON.stringify({ ts: 0, stocks: [{ ticker: 'AAPL', price: 100 }] }));
  let resolveOld;
  vi.spyOn(stockApi, 'authFetch').mockReturnValue(new Promise(resolve => { resolveOld = resolve; }));
  const view = render(<Watchlist />);
  await screen.findByText('AAPL', { exact: true });
  sessionStorage.clear();
  session.mockReturnValue({ user: null, token: null });
  view.rerender(<Watchlist />);
  expect(screen.queryByText('AAPL', { exact: true })).toBeNull();
  await act(async () => { resolveOld(new Response(JSON.stringify({ stocks: [{ ticker: 'AAPL', price: 100 }] }))); });
  expect(screen.queryByText('AAPL', { exact: true })).toBeNull();
  expect(sessionStorage.getItem('screener_cache:1')).toBeNull();
});

test('directional no-trade reason does not suggest taking more risk', async () => {
  vi.spyOn(stockApi, 'fetchStructures').mockResolvedValue({ spot: 100, expiry: '2027-01-15', dte: 30,
    ideas: [], no_trade_reason: 'Earnings date is unavailable. Event risk is not cleared.' });
  render(<Structures ticker="AAPL" />);
  fireEvent.click(screen.getByRole('button', { name: 'Find trades' }));
  expect(await screen.findByRole('status')).toHaveProperty('textContent', 'Earnings date is unavailable. Event risk is not cleared.');
  expect(screen.queryByText(/higher-risk/)).toBeNull();
});

test('expired access token refreshes once for concurrent requests', async () => {
  localStorage.setItem('token', 'old'); localStorage.setItem('refresh_token', 'refresh');
  const fetch = vi.fn(async (url, options) => {
    if (url.endsWith('/auth/refresh')) return new Response(JSON.stringify({ token: 'new', refresh_token: 'next' }));
    return new Response('{}', { status: options.headers.Authorization === 'Bearer new' ? 200 : 401 });
  });
  vi.stubGlobal('fetch', fetch);
  const responses = await Promise.all([authFetch('/private'), authFetch('/private')]);
  expect(responses.map(response => response.status)).toEqual([200, 200]);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
  expect(localStorage.getItem('token')).toBe('new');
});

test('a late 401 reuses the same session token rotation', async () => {
  localStorage.setItem('token', 'late-old'); localStorage.setItem('refresh_token', 'late-refresh');
  let resolveLate;
  const delayed = new Promise(resolve => { resolveLate = resolve; });
  const fetch = vi.fn(async (url, options) => {
    if (url.endsWith('/auth/refresh')) return new Response(JSON.stringify({ token: 'late-new', refresh_token: 'late-next' }));
    if (options.headers.Authorization === 'Bearer late-new') return new Response('{}');
    return url === '/late' ? delayed : new Response('{}', { status: 401 });
  });
  vi.stubGlobal('fetch', fetch);
  const first = authFetch('/first');
  const late = authFetch('/late');
  expect((await first).ok).toBe(true);
  resolveLate(new Response('{}', { status: 401 }));
  expect((await late).ok).toBe(true);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(1);
});

test('temporary refresh failure preserves credentials', async () => {
  localStorage.setItem('token', 'old'); localStorage.setItem('refresh_token', 'refresh');
  vi.stubGlobal('fetch', vi.fn(async url => new Response('{}', { status: url.endsWith('/auth/refresh') ? 503 : 401 })));
  await expect(authFetch('/private')).rejects.toThrow('unavailable');
  expect(localStorage.getItem('refresh_token')).toBe('refresh');
});

test.each([200, 401])('old token refresh (%s) cannot replace or clear a new session', async status => {
  localStorage.setItem('token', 'old-access'); localStorage.setItem('refresh_token', 'old-refresh');
  let resolveRefresh;
  const delayed = new Promise(resolve => { resolveRefresh = resolve; });
  const fetch = vi.fn(async url => url.endsWith('/auth/refresh') ? delayed : new Response('{}', { status: 401 }));
  vi.stubGlobal('fetch', fetch);
  const request = authFetch('/watchlist', { method: 'POST' });
  const rejection = expect(request).rejects.toThrow();
  await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  localStorage.setItem('token', 'new-access'); localStorage.setItem('refresh_token', 'new-refresh');
  sessionStorage.setItem('new-account-cache', 'keep');
  resolveRefresh(new Response(JSON.stringify({ token: 'old-rotated', refresh_token: 'old-rotated-refresh' }), { status }));
  await rejection;
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(localStorage.getItem('token')).toBe('new-access');
  expect(localStorage.getItem('refresh_token')).toBe('new-refresh');
  expect(sessionStorage.getItem('new-account-cache')).toBe('keep');
});

test('delayed unauthorized mutation is not retried as a different account', async () => {
  localStorage.setItem('token', 'old-access'); localStorage.setItem('refresh_token', 'old-refresh');
  let resolveRequest;
  const fetch = vi.fn(() => new Promise(resolve => { resolveRequest = resolve; }));
  vi.stubGlobal('fetch', fetch);
  const request = authFetch('/watchlist', { method: 'POST' });
  const rejection = expect(request).rejects.toThrow(/session changed/i);
  localStorage.setItem('token', 'new-access'); localStorage.setItem('refresh_token', 'new-refresh');
  resolveRequest(new Response('{}', { status: 401 }));
  await rejection;
  expect(fetch).toHaveBeenCalledTimes(1);
});

const allocation = { portfolio: '10000', cashAvailable: '0', allocPct: '5', stockPrice: 100, stopLoss: '', targetPrice: '' };
test('zero cash is not the whole portfolio', () => {
  expect(calculatePosition(allocation).actualShares).toBe(0);
  expect(calculatePosition({ ...allocation, cashAvailable: '' }).actualShares).toBe(5);
});
test('invalid long stop and target are rejected', () => {
  expect(calculatePosition({ ...allocation, stopLoss: '110' })).toBeNull();
  expect(calculatePosition({ ...allocation, targetPrice: '90' })).toBeNull();
});
test('0DTE baseline retains market time value', () => {
  const option = { id: 1, ticker: 'AAPL', current_price: 100, strike: 100, type: 'put', position: 'short',
    premium: 2, market_price: 1, quoted: true, contracts: 1, dte: 0, iv: 30, time_to_expiry_years: 1 / (365 * 24) };
  expect(pnlAt([option], [], 0, 0, 0, false).total).toBe(100);
  expect(pnlAt([option], [], 0, 0, 1, false).total).toBe(200);
  expect(pnlAt([{ ...option, quoted: false }], [], 0, 0, 0, false).total).toBeNull();
});

test('income ideas never offer zero contracts or unknown earnings', () => {
  const ideas = [{ capital_required: 10000, liquidity: 'good', bid: 1, ask: 1.05 }];
  const settings = { mode: 'csp', cash: '0', earnings: '2027-02-01', expiry: '2027-01-15' };
  expect(eligibleIncomeIdeas(ideas, settings)).toHaveLength(0);
  expect(eligibleIncomeIdeas(ideas, { ...settings, cash: '10000' })).toHaveLength(1);
  expect(eligibleIncomeIdeas(ideas, { ...settings, cash: '10000', earnings: null })).toHaveLength(0);
});

const pyplPut = { label: 'Conservative', strike: 50, bid: .32, ask: .4, mid: .36, premium: 36,
  delta: .19, open_interest: 6708, spread_pct: 22.2, liquidity: 'thin', capital_required: 5000,
  safety: 'safer', checks: [], return_pct: .72, annualized_pct: 21.9, prob_assigned_pct: 20,
  effective_buy_price: 49.64, discount_pct: 6 };

test.each(['cc', 'pcs', 'ic'])('income %s permits thin valid quotes but retains sizing blockers', mode => {
  const idea = { ...pyplPut, credit: .5, natural_credit: .3, width: 5, max_loss: 450 };
  const settings = { mode, shares: 100, risk: '450', earnings: '2026-10-27', expiry: '2026-10-16' };
  expect(eligibleIncomeIdeas([idea], settings)).toHaveLength(1);
  expect(eligibleIncomeIdeas([idea], { ...settings, shares: 99, risk: '449' })).toHaveLength(0);
  expect(eligibleIncomeIdeas([idea], { ...settings, earnings: settings.expiry })).toHaveLength(0);
  expect(eligibleIncomeIdeas([{ ...idea, bid: null, natural_credit: null }], settings)).toHaveLength(0);
  expect(eligibleIncomeIdeas([{ ...idea, bid: .5, natural_credit: .6 }], settings)).toHaveLength(0);
});

test('wide-spread PYPL put stays visible with an execution warning and affordable size', async () => {
  vi.spyOn(stockApi, 'fetchIncomeIdeas').mockResolvedValue({ spot: 52.8, expiry: '2026-10-16', dte: 12,
    earnings_date: '2026-10-27', expirations: [{ date: '2026-10-16', dte: 12 }], cash_secured_puts: [pyplPut] });
  render(<IncomeIdeas ticker="PYPL" />);
  await screen.findByText(/Stock \$52.8/);
  fireEvent.click(screen.getByRole('button', { name: 'Cash-Secured Puts' }));
  fireEvent.change(screen.getByLabelText('Cash available ($)'), { target: { value: '5500' } });
  expect(screen.getByText(/SELL 1/)).toBeTruthy();
  expect(screen.getByText(/Wide spread: 22.2% exceeds the 20% guideline/)).toBeTruthy();
  expect(screen.getByText('Cash sufficient; execution caution.')).toBeTruthy();
  expect(screen.queryByText(/Passes checks/)).toBeNull();
  expect(screen.queryByText(/No eligible trade/)).toBeNull();
});

test('income low open interest warning does not falsely claim a wide spread', async () => {
  vi.spyOn(stockApi, 'fetchIncomeIdeas').mockResolvedValue({ spot: 52.8, expiry: '2026-10-16', dte: 12,
    earnings_date: '2026-10-27', expirations: [{ date: '2026-10-16', dte: 12 }],
    covered_calls: [{ ...pyplPut, bid: .39, open_interest: 50 }] });
  render(<IncomeIdeas ticker="PYPL" />);
  expect(await screen.findByText(/Low open interest: 50/)).toBeTruthy();
  expect(screen.getByText(/SELL 1/)).toBeTruthy();
  expect(screen.queryByText(/Wide spread:/)).toBeNull();
  expect(screen.queryByText(/Passes checks/)).toBeNull();
});

test.each([
  ['insufficient cash', { cash: '4500' }, /Cash needed: \$5,000/],
  ['missing bid', { bid: null }, /Valid two-sided quote unavailable/],
  ['crossed quote', { bid: .5 }, /Valid two-sided quote unavailable/],
  ['unknown earnings', { earnings: null }, /Earnings date unavailable/],
  ['earnings before expiry', { earnings: '2026-10-10' }, /Earnings occur on or before expiry/],
])('income candidate remains visible without actionable size for %s', async (_, override, reason) => {
  vi.spyOn(stockApi, 'fetchIncomeIdeas').mockResolvedValue({ spot: 52.8, expiry: '2026-10-16', dte: 12,
    earnings_date: Object.hasOwn(override, 'earnings') ? override.earnings : '2026-10-27',
    expirations: [{ date: '2026-10-16', dte: 12 }], cash_secured_puts: [{ ...pyplPut, ...override }] });
  render(<IncomeIdeas ticker="PYPL" />);
  await screen.findByText(/Stock \$52.8/);
  fireEvent.click(screen.getByRole('button', { name: 'Cash-Secured Puts' }));
  fireEvent.change(screen.getByLabelText('Cash available ($)'), { target: { value: override.cash ?? '5500' } });
  expect(screen.getByText(reason)).toBeTruthy();
  expect(screen.getByText(/Cash needed \/ contract/)).toBeTruthy();
  expect(screen.queryByText(/SELL \d/)).toBeNull();
  expect(screen.queryByText(/Passes checks/)).toBeNull();
});

test('correlation aligns dates and rejects insufficient shared observations', () => {
  const prices = Array.from({ length: 10 }, (_, index) => ({ date: `2026-01-${String(index + 1).padStart(2, '0')}`, close: 100 + index * index }));
  expect(alignedCorrelation(prices, prices.slice(3))).toBeCloseTo(1);
  expect(alignedCorrelation(prices.slice(0, 5), prices.slice(5))).toBeNull();
});

test('strategy results render without undefined components', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  vi.spyOn(stockApi, 'fetchBacktestStrategies').mockResolvedValue({ timeframes: ['5m'], strategies: {
    ema_cross: { label: 'EMA cross', params: { fast: 9, slow: 21 }, help: '' },
  } });
  vi.spyOn(stockApi, 'runBacktest').mockResolvedValue({ label: 'EMA cross', ticker: 'SPY', timeframe: '5m',
    from: '2026-01-01', to: '2026-03-01', sessions: 40, stats: { trades: 2, profit_factor: null, avg_net_pct: 1 },
    equity: [], recent_trades: [], baseline: { label: 'Buy and hold', total_pct: 0 }, notes: [] });
  render(<StrategyTester />);
  fireEvent.click(await screen.findByRole('button', { name: /Run backtest/ }));
  expect(await screen.findByText('EMA cross · SPY · 5m')).toBeTruthy();
  expect(screen.getByText('Latest trades')).toBeTruthy();
});

test('portfolio renders unavailable stock values without crashing', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'test' });
  vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ total_invested: 1000, total_current: null,
    total_pnl: null, total_pnl_pct: null, incomplete: true,
    holdings: [{ id: 1, ticker: 'AAPL', shares: 10, buy_price: 100, current_price: null, pnl: null, pnl_pct: null }] });
  vi.spyOn(stockApi, 'fetchOptionsSummary').mockResolvedValue({ options: [] });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [], total_realized_pnl: 0 });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [], total_realized_pnl: 0 });
  render(<Portfolio />);
  expect(await screen.findByText('AAPL')).toBeTruthy();
  expect(screen.getAllByText('Unavailable').length).toBeGreaterThanOrEqual(3);
});