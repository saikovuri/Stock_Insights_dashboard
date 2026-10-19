// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import * as auth from './AuthContext';
import Portfolio from './components/Portfolio';
import Journal, { planChecks, tradesCsv, recordedTradeMetrics } from './components/Journal';
import { ClosedOptions } from './components/ClosedHistory';
import { spreadLegs, spreadPreview } from './spreads';

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true; } });
  vi.spyOn(stockApi, 'fetchTradePlans').mockResolvedValue({ items: [] });
  vi.spyOn(stockApi, 'fetchTickerProfiles').mockResolvedValue({ profiles: {} });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

// A closed bull put spread as the API returns it: legs merged into one credit (short) trade with net premiums
const closedSpread = { id: 11, spread_id: 'abc', ledger_event_id: 21, ticker: 'SPY', position: 'short', option_type: 'put', strike: 100,
  expiry: '2026-03-20', contracts: 2, open_premium: 1.5, close_premium: 0.5, pnl: 200, pnl_pct: 66.67, fees: 2.6, net_pnl: 197.4, is_manual: true,
  opened_at: '2026-03-02', closed_at: '2026-03-10',
  spread: { kind: 'bull_put', label: 'Bull put', style: 'credit', long_strike: 95, short_strike: 100, width: 5, leg_ids: [11, 12] } };

test('spread preview gives net, payoff limits, breakeven and plain errors', () => {
  expect(spreadPreview({ kind: 'bull_put', lower: 95, upper: 100, longPremium: 1, shortPremium: 2.5, contracts: 2 }))
    .toMatchObject({ net: 1.5, maxProfit: 300, maxLoss: 700, breakeven: 98.5, collateral: 1000 });
  expect(spreadPreview({ kind: 'bear_put', lower: 100, upper: 105, longPremium: 3, shortPremium: 1 }))
    .toMatchObject({ net: 2, maxProfit: 300, maxLoss: 200, breakeven: 103, collateral: 0 });
  expect(spreadPreview({ kind: 'bull_call', lower: 100, upper: 95, longPremium: 3, shortPremium: 1 }).error).toMatch(/lower strike/);
  expect(spreadPreview({ kind: 'bear_call', lower: 100, upper: 105, longPremium: 2, shortPremium: 1 }).error).toMatch(/credit spread/);
  expect(spreadPreview({ kind: 'bull_call', lower: 100, upper: 102, longPremium: 3, shortPremium: 0.5 }).error).toMatch(/strike width/);
  expect(spreadPreview({ kind: 'bull_call', lower: '', upper: 102, longPremium: 3, shortPremium: 0.5 })).toBeNull();
  expect(spreadLegs('bear_call', 100, 105)).toEqual({ long_strike: 105, short_strike: 100 });
});

test('closed spreads count as one credit trade and compare against a spread plan', () => {
  expect(recordedTradeMetrics(closedSpread).capture).toBeCloseTo(66.67, 1);
  const plan = { max_loss: 500, horizon: '1–4 weeks', structure: 'Debit spread' };
  expect(planChecks(plan, closedSpread).at(-1)).toEqual({ ok: false, text: 'Planned a debit spread; this trade was a credit spread' });
  expect(planChecks({ ...plan, structure: 'Credit spread' }, closedSpread).every(check => check.ok)).toBe(true);
  const [, row] = tradesCsv([{ ...closedSpread, quantity: 2 }]).split('\r\n');
  expect(row).toContain('"Option spread","SPY","Bull put spread","95/100","2026-03-20",2');
});

test('portfolio opens a spread from the option form, groups its legs and closes both legs together', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'fixture' });
  vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
  const leg = { ticker: 'SPY', type: 'put', expiry: '2099-01-15', dte: 30, contracts: 2, current_price: 101, quoted: true, account: 'Default', spread_id: 'abc' };
  vi.spyOn(stockApi, 'fetchOptionsSummary').mockResolvedValue({ total_cost: 700, total_value: 400, total_pnl: 100, total_pnl_pct: 14, options: [
    { ...leg, id: 1, position: 'short', strike: 100, premium: 2.5, market_price: 1.5, pnl: 200 },
    { ...leg, id: 2, position: 'long', strike: 95, premium: 1, market_price: 0.5, pnl: -100 },
    { ...leg, id: 3, ticker: 'KO', type: 'call', position: 'long', strike: 70, premium: 1, market_price: 1, pnl: 0, spread_id: null }],
  spreads: [{ spread_id: 'abc', kind: 'bull_put', label: 'Bull put', style: 'credit', ticker: 'SPY', type: 'put', expiry: '2099-01-15', dte: 30,
    contracts: 2, long_strike: 95, short_strike: 100, net_open: 1.5, net_mark: 1, width: 5, max_profit: 300, max_loss: 700, breakeven: 98.5,
    collateral: 1000, current_price: 101, account: 'Default', expired: false, pnl: 100, pnl_pct_of_risk: 14.3, leg_ids: [1, 2] }] });
  const open = vi.spyOn(stockApi, 'openSpread').mockResolvedValue({ label: 'Bull put', style: 'credit', net_open: 1.5 });
  const close = vi.spyOn(stockApi, 'closeSpread').mockResolvedValue({ pnl: 50 });
  render(<Portfolio />);
  fireEvent.click(screen.getByRole('button', { name: /Options/ }));
  const table = await screen.findByRole('table');
  expect(within(table).getByText('BULL PUT SPREAD')).toBeTruthy();
  expect(within(table).getByText('$100.00 (14.3% of $700.00 risk)')).toBeTruthy();
  expect(within(table).queryByText('spread leg')).toBeNull();
  expect(within(table).getAllByRole('row')).toHaveLength(3);
  fireEvent.click(within(table).getByTitle('Show the two legs'));
  expect(within(table).getAllByText('spread leg')).toHaveLength(2);

  fireEvent.change(screen.getByLabelText('Action'), { target: { value: 'spread' } });
  fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'spy' } });
  fireEvent.change(screen.getByLabelText('Expiry Date'), { target: { value: '2099-02-19' } });
  fireEvent.change(screen.getByLabelText('Spread'), { target: { value: 'bear_call' } });
  fireEvent.change(screen.getByLabelText('Lower strike ($)'), { target: { value: '110' } });
  fireEvent.change(screen.getByLabelText('Upper strike ($)'), { target: { value: '115' } });
  fireEvent.change(screen.getByLabelText('Sell lower call ($/share)'), { target: { value: '2' } });
  fireEvent.change(screen.getByLabelText('Buy upper call ($/share)'), { target: { value: '0.8' } });
  expect(screen.getByText(/breakeven \$111\.20/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Open spread' }));
  await waitFor(() => expect(open).toHaveBeenCalledWith({ ticker: 'SPY', kind: 'bear_call', expiry: '2099-02-19', long_strike: 115, short_strike: 110,
    long_premium: 0.8, short_premium: 2, contracts: 1 }));

  fireEvent.click(screen.getByRole('button', { name: 'Close SPY spread' }));
  const panel = screen.getByRole('form', { name: 'Close spread' });
  fireEvent.change(within(panel).getByLabelText('Buy back $100 put at ($/share)'), { target: { value: '0.75' } });
  fireEvent.change(within(panel).getByLabelText('Sell $95 put at ($/share)'), { target: { value: '0.25' } });
  fireEvent.change(within(panel).getByLabelText('Contracts (of 2)'), { target: { value: '1' } });
  expect(within(panel).getByText('$100.00')).toBeTruthy();
  fireEvent.click(within(panel).getByRole('button', { name: 'Close spread' }));
  await waitFor(() => expect(close).toHaveBeenCalledWith('abc', { long_premium: 0.25, short_premium: 0.75, contracts: 1 }));
});

test('closed options list shows a spread as one row and deletes that close by its row id', () => {
  const onDelete = vi.fn();
  const setConfirm = vi.fn();
  const { rerender } = render(<ClosedOptions data={{ trades: [closedSpread], total_realized_pnl: 200, total_fees: 2.6, total_net_pnl: 197.4 }}
    confirmDelete={null} setConfirmDelete={setConfirm} onDelete={onDelete} />);
  expect(screen.getByText('BULL PUT SPREAD')).toBeTruthy();
  expect(screen.getByText('$95/$100')).toBeTruthy();
  rerender(<ClosedOptions data={{ trades: [closedSpread], total_realized_pnl: 200 }} confirmDelete={{ type: 'closed-spread', id: 11 }}
    setConfirmDelete={setConfirm} onDelete={onDelete} />);
  fireEvent.click(screen.getByTitle('Confirm delete'));
  expect(onDelete).toHaveBeenCalledWith('closed-spread', 11);
});

test('journal logs a completed spread with leg fills mapped to long and short, and deletes it as one trade', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchJournal').mockResolvedValue({ entries: [], stats: null });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [closedSpread] });
  const log = vi.spyOn(stockApi, 'logClosedSpread').mockResolvedValue({ spread_id: 'new' });
  const remove = vi.spyOn(stockApi, 'deleteClosedSpread').mockResolvedValue({ ok: true });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<Journal />);
  fireEvent.click(await screen.findByRole('button', { name: 'Manual journal' }));
  const history = await screen.findByRole('table', { name: 'Recorded trades' });
  expect(within(history).getByText('Bull put spread')).toBeTruthy();
  expect(within(history).getByText(/\$95\/\$100 · exp/)).toBeTruthy();
  expect(within(history).queryByRole('button', { name: 'Edit SPY option' })).toBeNull();

  fireEvent.click(screen.getByRole('button', { name: 'Log closed option' }));
  fireEvent.click(screen.getByRole('button', { name: 'Spread (2 legs)' }));
  const form = screen.getByRole('form', { name: 'Closed spread entry' });
  const set = (label, value) => fireEvent.change(within(form).getByLabelText(label), { target: { value } });
  set('Ticker', 'nvda'); set('Spread', 'bull_call'); set('Expiry', '2026-03-20'); set('Contracts', '2');
  set('Lower strike ($)', '140'); set('Upper strike ($)', '150'); set('Opened on', '2026-03-01'); set('Closed on', '2026-03-10');
  set('Opened: bought lower call ($/share)', '4'); set('Opened: sold upper call ($/share)', '1');
  set('Closed: sold lower call ($/share)', '7'); set('Closed: bought back upper call ($/share)', '2'); set('Total fees ($, all legs)', '2.6');
  expect(within(form).getByText('$400')).toBeTruthy();
  fireEvent.click(within(form).getByRole('button', { name: 'Record closed spread' }));
  await waitFor(() => expect(log).toHaveBeenCalledWith(expect.objectContaining({ ticker: 'NVDA', kind: 'bull_call', long_strike: 140, short_strike: 150,
    long_open: 4, short_open: 1, long_close: 7, short_close: 2, contracts: 2, fees: 2.6, idempotency_key: expect.any(String) })));
  expect(await screen.findByText('NVDA bull call spread recorded.')).toBeTruthy();

  fireEvent.click(within(await screen.findByRole('table', { name: 'Recorded trades' })).getByRole('button', { name: 'Delete SPY option' }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith(11));
});
