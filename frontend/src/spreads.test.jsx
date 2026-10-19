// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import * as auth from './AuthContext';
import Portfolio from './components/Portfolio';
import Journal, { planChecks, tradesCsv, recordedTradeMetrics } from './components/Journal';
import { ClosedOptions } from './components/ClosedHistory';
import { classify, describe, previewStructure } from './spreads';

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true; } });
  vi.spyOn(stockApi, 'fetchTradePlans').mockResolvedValue({ items: [] });
  vi.spyOn(stockApi, 'fetchTickerProfiles').mockResolvedValue({ profiles: {} });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const E = '2099-01-15';
const L = (position, option_type, strike, premium, extra = {}) => ({ position, option_type, strike, premium, expiry: E, ratio: 1, ...extra });
const legInfo = (id, position, option_type, strike, premium, extra = {}) => ({ id, position, option_type, strike, premium, expiry: E, ratio: 1, ...extra });

// A closed bull put spread as the API returns it: legs merged into one credit (short) trade with net premiums
const closedSpread = { id: 11, spread_id: 'abc', ledger_event_id: 21, ticker: 'SPY', position: 'short', option_type: 'put', strike: 100,
  expiry: '2026-03-20', contracts: 2, open_premium: 1.5, close_premium: 0.5, pnl: 200, pnl_pct: 66.67, fees: 2.6, net_pnl: 197.4, is_manual: true,
  opened_at: '2026-03-02', closed_at: '2026-03-10',
  spread: { kind: 'bull_put', label: 'Bull put', family: 'vertical', style: 'credit', strikes: '$95/$100', multi_expiry: false, leg_ids: [11, 12],
    legs: [{ id: 11, position: 'short', option_type: 'put', strike: 100, expiry: '2026-03-20', ratio: 1, premium: 2.5, close_premium: 0.75 },
      { id: 12, position: 'long', option_type: 'put', strike: 95, expiry: '2026-03-20', ratio: 1, premium: 1, close_premium: 0.25 }] } };

test('the payoff engine matches the backend for verticals, condors, butterflies and calendars', () => {
  expect(describe([L('long', 'put', 95, 1), L('short', 'put', 100, 2.5)], 2))
    .toMatchObject({ kind: 'bull_put', style: 'credit', net: 1.5, maxProfit: 300, maxLoss: 700, breakevens: [98.5], collateral: 1000, strikes: '$95/$100' });
  const condor = [L('long', 'put', 90, 0.5), L('short', 'put', 95, 1.5), L('short', 'call', 105, 1.4), L('long', 'call', 110, 0.4)];
  expect(describe(condor)).toMatchObject({ kind: 'iron_condor', maxProfit: 200, maxLoss: 300, breakevens: [93, 107], collateral: 500 });
  expect(describe([L('long', 'call', 100, 6), L('short', 'call', 105, 3, { ratio: 2 }), L('long', 'call', 110, 1.2)]))
    .toMatchObject({ kind: 'call_butterfly', style: 'debit', maxLoss: 120, maxProfit: 380, breakevens: [101.2, 108.8] });
  expect(describe([L('short', 'call', 100, 2), L('long', 'call', 100, 4.5, { expiry: '2099-03-19' })]))
    .toMatchObject({ kind: 'call_calendar', maxLoss: 250, maxProfit: null, multi: true });
  expect(() => classify([L('long', 'call', 100, 4.5), L('short', 'call', 100, 2, { expiry: '2099-03-19' })])).toThrow(/nearer expiry/);
  expect(previewStructure([{ ...L('long', 'put', 95, 1), strike: '95' }, { ...L('short', 'put', 100, 2.5), strike: '100' }], 1, 'bear_put').error)
    .toMatch(/bull put, not a bear put/);
  expect(previewStructure([L('long', 'put', 95, 2.5), L('short', 'put', 100, 1)], 1).error).toMatch(/opened for a credit/);
  expect(previewStructure([{ ...L('long', 'put', 95, 1), strike: '' }, L('short', 'put', 100, 2.5)], 1)).toBeNull();
});

test('closed spreads count as one credit trade and compare against a spread plan', () => {
  expect(recordedTradeMetrics(closedSpread).capture).toBeCloseTo(66.67, 1);
  const plan = { max_loss: 500, horizon: '1–4 weeks', structure: 'Debit spread' };
  expect(planChecks(plan, closedSpread).at(-1)).toEqual({ ok: false, text: 'Planned a debit spread; this trade was a credit spread' });
  const [, row] = tradesCsv([{ ...closedSpread, quantity: 2 }]).split('\r\n');
  expect(row).toContain('"Option spread","SPY","Bull put spread","95/100","2026-03-20",2');
});

function mockPortfolio(summary) {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'fixture' });
  vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchOptionsSummary').mockResolvedValue(summary);
}

const row = { ticker: 'SPY', type: 'put', expiry: E, dte: 30, contracts: 2, current_price: 101, quoted: true, account: 'Default', spread_id: 'abc' };
const summary = {
  total_cost: 700, total_value: 400, total_pnl: 100, total_pnl_pct: 14,
  options: [{ ...row, id: 1, position: 'short', strike: 100, premium: 2.5, market_price: 1.5, pnl: 200 },
    { ...row, id: 2, position: 'long', strike: 95, premium: 1, market_price: 0.5, pnl: -100 },
    { ...row, id: 3, ticker: 'KO', type: 'call', position: 'long', strike: 70, premium: 1, market_price: 1, pnl: 0, spread_id: 'old', broken_spread: 'Bull call' },
    { ...row, id: 4, ticker: 'KO', type: 'call', position: 'short', strike: 75, premium: 0.5, market_price: 0.4, pnl: 10, spread_id: null }],
  spreads: [{ spread_id: 'abc', kind: 'bull_put', label: 'Bull put', family: 'vertical', style: 'credit', strikes: '$95/$100', multi_expiry: false,
    ticker: 'SPY', type: 'put', expiry: E, dte: 30, contracts: 2, net_open: 1.5, net_mark: 1, max_profit: 300, max_loss: 700, breakevens: [98.5],
    collateral: 1000, current_price: 101, zone: 'max_profit', account: 'Default', expired: false, pnl: 100, pnl_pct_of_risk: 14.3, leg_ids: [1, 2],
    legs: [legInfo(1, 'short', 'put', 100, 2.5), legInfo(2, 'long', 'put', 95, 1)] }],
  link_suggestions: [{ option_ids: [3, 4], ticker: 'KO', kind: 'bull_call', label: 'Bull call', strikes: '$70/$75', contracts: 2 }],
};

test('portfolio opens an iron condor from the builder, groups legs, edits, links and closes every leg', async () => {
  mockPortfolio(summary);
  const open = vi.spyOn(stockApi, 'openSpread').mockResolvedValue({ label: 'Iron condor', family: 'iron', style: 'credit', strikes: '$90/$95/$105/$110', net_open: 2 });
  const edit = vi.spyOn(stockApi, 'editSpread').mockResolvedValue({ label: 'Bull put', family: 'vertical', style: 'credit', strikes: '$95/$100', net_open: 1.6 });
  const link = vi.spyOn(stockApi, 'linkSpread').mockResolvedValue({ label: 'Bull call', family: 'vertical' });
  const close = vi.spyOn(stockApi, 'closeSpread').mockResolvedValue({ pnl: 50 });
  render(<Portfolio />);
  fireEvent.click(screen.getByRole('button', { name: /Options/ }));
  const table = await screen.findByRole('table');
  expect(within(table).getByText('BULL PUT SPREAD')).toBeTruthy();
  expect(within(table).getByText('Max profit')).toBeTruthy();
  expect(within(table).getByText('left from bull call')).toBeTruthy();
  fireEvent.click(within(table).getByTitle('Show the legs'));
  expect(within(table).getAllByText('spread leg')).toHaveLength(2);

  fireEvent.click(screen.getByRole('button', { name: 'Link as spread' }));
  await waitFor(() => expect(link).toHaveBeenCalledWith([3, 4]));

  fireEvent.change(screen.getByLabelText('Action', { selector: 'select' }), { target: { value: 'spread' } });
  fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'spy' } });
  fireEvent.change(screen.getByLabelText('Structure'), { target: { value: 'iron_condor' } });
  fireEvent.change(screen.getByLabelText('Expiry Date'), { target: { value: E } });
  [[90, 0.5], [95, 1.5], [105, 1.4], [110, 0.4]].forEach(([strike, fill], i) => {
    fireEvent.change(screen.getByLabelText(`Leg ${i + 1} strike`), { target: { value: String(strike) } });
    fireEvent.change(screen.getByLabelText(`Leg ${i + 1} fill`), { target: { value: String(fill) } });
  });
  expect(screen.getByText(/breakevens \$93\.00 and \$107\.00/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Open spread' }));
  await waitFor(() => expect(open).toHaveBeenCalledWith({ ticker: 'SPY', kind: 'iron_condor', contracts: 1, legs: [
    { position: 'long', option_type: 'put', strike: 90, expiry: E, premium: 0.5, ratio: 1 },
    { position: 'short', option_type: 'put', strike: 95, expiry: E, premium: 1.5, ratio: 1 },
    { position: 'short', option_type: 'call', strike: 105, expiry: E, premium: 1.4, ratio: 1 },
    { position: 'long', option_type: 'call', strike: 110, expiry: E, premium: 0.4, ratio: 1 }] }));

  fireEvent.click(screen.getByRole('button', { name: 'Edit SPY spread' }));
  const editor = screen.getByRole('form', { name: 'Edit spread' });
  fireEvent.change(within(editor).getByLabelText('Leg 2 fill'), { target: { value: '2.6' } });
  fireEvent.click(within(editor).getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(edit).toHaveBeenCalledWith('abc', { ticker: 'SPY', contracts: 2, legs: [
    { position: 'long', option_type: 'put', strike: 95, expiry: E, premium: 1, ratio: 1, id: 2 },
    { position: 'short', option_type: 'put', strike: 100, expiry: E, premium: 2.6, ratio: 1, id: 1 }] }));

  fireEvent.click(screen.getByRole('button', { name: 'Close SPY spread' }));
  const panel = screen.getByRole('form', { name: 'Close spread' });
  fireEvent.change(within(panel).getByLabelText('Buy back $100 put at ($/share)'), { target: { value: '0.75' } });
  fireEvent.change(within(panel).getByLabelText('Sell $95 put at ($/share)'), { target: { value: '0.25' } });
  fireEvent.change(within(panel).getByLabelText('Contracts (of 2)'), { target: { value: '1' } });
  expect(within(panel).getByText('$100.00')).toBeTruthy();
  fireEvent.click(within(panel).getByRole('button', { name: 'Close spread' }));
  await waitFor(() => expect(close).toHaveBeenCalledWith('abc', { prices: [{ id: 1, premium: 0.75 }, { id: 2, premium: 0.25 }], contracts: 1 }));
});

test('closed options list shows a spread as one row and deletes that close by its row id', () => {
  const onDelete = vi.fn();
  render(<ClosedOptions data={{ trades: [closedSpread], total_realized_pnl: 200 }} confirmDelete={{ type: 'closed-spread', id: 11 }}
    setConfirmDelete={vi.fn()} onDelete={onDelete} />);
  expect(screen.getByText('BULL PUT SPREAD')).toBeTruthy();
  expect(screen.getByText('$95/$100')).toBeTruthy();
  fireEvent.click(screen.getByTitle('Confirm delete'));
  expect(onDelete).toHaveBeenCalledWith('closed-spread', 11);
});

test('journal logs a butterfly, edits a logged spread and deletes it as one trade', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchJournal').mockResolvedValue({ entries: [], stats: null });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [closedSpread] });
  const log = vi.spyOn(stockApi, 'logClosedSpread').mockResolvedValue({ spread_id: 'new' });
  const update = vi.spyOn(stockApi, 'updateClosedSpread').mockResolvedValue({ spread_id: 'abc' });
  const remove = vi.spyOn(stockApi, 'deleteClosedSpread').mockResolvedValue({ ok: true });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<Journal />);
  fireEvent.click(await screen.findByRole('button', { name: 'Manual journal' }));
  const history = await screen.findByRole('table', { name: 'Recorded trades' });
  expect(within(history).getByText('Bull put spread')).toBeTruthy();
  expect(within(history).getByText(/\$95\/\$100 · exp/)).toBeTruthy();

  fireEvent.click(screen.getByRole('button', { name: 'Log closed option' }));
  fireEvent.click(screen.getByRole('button', { name: 'Spread (2–4 legs)' }));
  const form = screen.getByRole('form', { name: 'Closed spread entry' });
  const set = (label, value) => fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  set('Ticker', 'nvda'); set('Structure', 'call_butterfly'); set('Expiry', '2026-03-20'); set('Contracts', '2');
  set('Opened on', '2026-03-01'); set('Closed on', '2026-03-10');
  [[140, 6, 9], [145, 3, 4], [150, 1.2, 0.5]].forEach(([strike, opened, closed], i) => {
    set(`Leg ${i + 1} strike`, String(strike)); set(`Leg ${i + 1} opening fill`, String(opened)); set(`Leg ${i + 1} closing fill`, String(closed));
  });
  set('Total fees ($, all legs)', '2.6');
  expect(within(form).getByText('$60')).toBeTruthy(); // (+3 - 2×1 - 0.7) × 2 butterflies × 100
  fireEvent.click(within(form).getByRole('button', { name: 'Record closed spread' }));
  await waitFor(() => expect(log).toHaveBeenCalledWith(expect.objectContaining({ ticker: 'NVDA', kind: 'call_butterfly', contracts: 2, fees: 2.6,
    legs: [expect.objectContaining({ strike: 140, ratio: 1, open_premium: 6, close_premium: 9 }),
      expect.objectContaining({ position: 'short', strike: 145, ratio: 2 }), expect.objectContaining({ strike: 150, ratio: 1 })],
    idempotency_key: expect.any(String) })));
  expect(await screen.findByText('NVDA call butterfly recorded.')).toBeTruthy();

  fireEvent.click(within(await screen.findByRole('table', { name: 'Recorded trades' })).getByRole('button', { name: 'Edit SPY option' }));
  const editor = screen.getByRole('form', { name: 'Edit closed spread' });
  fireEvent.change(within(editor).getByLabelText('Leg 1 closing fill'), { target: { value: '0.5' } });
  fireEvent.click(within(editor).getByRole('button', { name: 'Save spread changes' }));
  await waitFor(() => expect(update).toHaveBeenCalledWith(11, expect.objectContaining({ contracts: 2,
    legs: [expect.objectContaining({ id: 11, close_premium: 0.5 }), expect.objectContaining({ id: 12, close_premium: 0.25 })] })));

  fireEvent.click(within(await screen.findByRole('table', { name: 'Recorded trades' })).getByRole('button', { name: 'Delete SPY option' }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith(11));
});
