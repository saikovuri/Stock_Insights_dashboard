// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { authFetch } from './api/stockApi';
import { calculatePosition } from './components/PositionCalculator';
import { pnlAt } from './components/OptionsDesk';
import IncomeIdeas, { eligibleIncomeIdeas } from './components/IncomeIdeas';
import { alignedCorrelation } from './components/CorrelationHeatmap';
import { render, screen, fireEvent, cleanup, act, waitFor, within } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import * as auth from './AuthContext';
import StrategyTester from './components/StrategyTester';
import Portfolio from './components/Portfolio';
import Watchlist from './components/Watchlist';
import Structures from './components/Structures';
import Accounting from './components/Accounting';
import WheelIdeas, { wheelFreshness } from './components/WheelIdeas';
import { AssignmentShare, isPostEarnings, limitLadder } from './components/TradeSizing';
import PreTradeChecklist from './components/PreTradeChecklist';
import Journal, { recordedTradeMetrics, recordedOptionStats, groupedOptionStats, edgeHighlights, howClosed } from './components/Journal';
import SearchBar from './components/SearchBar';
import { NavHistory, CorporateActions } from './components/Accounts';
import { ImportCsv } from './components/PortfolioInsights';
import WheelManager from './components/WheelManager';
import RollRepair from './components/RollRepair';
import WheelCycles from './components/WheelCycles';
import AccountTransfer from './components/AccountTransfer';
import PnlCalendar, { dailyPnl, compactMoney } from './components/PnlCalendar';
import ExpiryLadder from './components/ExpiryLadder';
import { TradingRules, TrimPlanner } from './components/RiskTools';
import { BuyZones, EventWeek } from './components/WatchlistExtras';
import CommandPalette, { matchCommands } from './components/CommandPalette';
import { lastLookChanges } from './components/SinceLastLook';

beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true; } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('account transfer previews before confirmation and retries the identical file', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 2, display_name: 'Destination' } });
  const bundle = { payload: '{"source_user_id":1,"shares":1.0}', signature: 'signed' };
  const preview = vi.spyOn(stockApi, 'previewAccountImport').mockResolvedValue({ source_name: 'Source', source_user_id: 1,
    counts: { holdings: 2, journal: 3 }, destination_counts: { holdings: 1 }, ledger_events: 12, already_imported: false });
  const save = vi.spyOn(stockApi, 'importAccountData').mockRejectedValueOnce(new Error('Import response unavailable')).mockResolvedValue({ already_imported: false });
  const refresh = vi.fn();
  render(<AccountTransfer onImported={refresh} />);
  fireEvent.click(screen.getByRole('button', { name: 'Import data from another login' }));
  expect(screen.queryByRole('button', { name: 'Confirm import' })).toBeNull();
  fireEvent.change(screen.getByLabelText('Transfer file (.json)'), { target: { files: [{ size: 100, text: async () => JSON.stringify(bundle) }] } });
  const confirm = await screen.findByRole('button', { name: 'Confirm import' });
  expect(preview).toHaveBeenCalledWith(bundle);
  expect(confirm.disabled).toBe(true);
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('checkbox', { name: /I confirm adding these records to Destination/ }));
  fireEvent.click(confirm);
  await screen.findByText('Import response unavailable');
  expect(refresh).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Confirm import' }));
  await screen.findByText(/Portfolio and Journal imported into Destination/);
  expect(save.mock.calls[0][0]).toEqual(bundle);
  expect(save.mock.calls[1][0]).toEqual(bundle);
  expect(refresh).toHaveBeenCalledTimes(1);
});

test('account transfer blocks invalid files and duplicate imports and clears drafts on account switch', async () => {
  const user = vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 2, display_name: 'Destination' } });
  const preview = vi.spyOn(stockApi, 'previewAccountImport').mockResolvedValue({ source_name: 'Source', source_user_id: 1,
    counts: {}, destination_counts: {}, ledger_events: 1, already_imported: true });
  const save = vi.spyOn(stockApi, 'importAccountData');
  const view = render(<AccountTransfer />);
  fireEvent.click(screen.getByRole('button', { name: 'Import data from another login' }));
  const input = screen.getByLabelText('Transfer file (.json)');
  fireEvent.change(input, { target: { files: [{ size: 11 * 1024 * 1024 }] } });
  await screen.findByText('Transfer file exceeds 10 MB.');
  fireEvent.change(input, { target: { files: [{ size: 2, text: async () => 'no' }] } });
  await screen.findByText('Choose a valid StockPilot transfer JSON file.');
  expect(preview).not.toHaveBeenCalled();
  fireEvent.change(input, { target: { files: [{ size: 2, text: async () => '{}' }] } });
  await screen.findByText('This export was already imported. No duplicate records will be added.');
  expect(screen.queryByRole('button', { name: 'Confirm import' })).toBeNull();
  expect(save).not.toHaveBeenCalled();
  user.mockReturnValue({ user: { id: 3, display_name: 'Other' } });
  view.rerender(<AccountTransfer />);
  expect(screen.queryByRole('dialog')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Import data from another login' }));
  expect(screen.queryByText('Source')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Confirm import' })).toBeNull();
  user.mockReturnValue({ user: null });
  view.rerender(<AccountTransfer />);
  expect(screen.queryByRole('button', { name: 'Export data to another login' })).toBeNull();
});

test('journal capture and holding metrics respect direction, losses and missing history', () => {
  const trade = { position: 'short', option_type: 'put', open_premium: 2, close_premium: 0.5,
    opened_at: '2026-03-07', closed_at: '2026-03-09T15:00:00Z', expiry: '2026-03-13' };
  expect(recordedTradeMetrics(trade)).toMatchObject({ capture: 75, daysHeld: 2, dteAtClose: 4, label: 'Captured' });
  expect(recordedTradeMetrics({ ...trade, close_premium: 3 }).capture).toBe(-50);
  expect(recordedTradeMetrics({ ...trade, close_premium: 0 }).capture).toBe(100);
  expect(recordedTradeMetrics({ ...trade, position: 'long', close_premium: 3 })).toMatchObject({ capture: 50, label: 'Return' });
  for (const open_premium of [null, '', 0, undefined]) expect(recordedTradeMetrics({ ...trade, open_premium }).capture).toBeNull();
  expect(recordedTradeMetrics({ ...trade, opened_at: '2026-02-30' }).daysHeld).toBeNull();
  expect(recordedTradeMetrics({ ...trade, opened_at: '2026-03-10' }).daysHeld).toBeNull();
  expect(recordedTradeMetrics({ ...trade, opened_at: '2026-03-09' }).daysHeld).toBe(0);
  expect(recordedTradeMetrics({ ...trade, review: { target_capture_pct: 50 } })).toMatchObject({ target: 50, targetGap: 25 });
  expect(recordedTradeMetrics({ ...trade, review: { target_capture_pct: 0 } })).toMatchObject({ target: 0, targetGap: 75 });
  expect(recordedTradeMetrics({ ...trade, position: 'long', review: { target_capture_pct: 50 } }).target).toBeNull();
  expect(recordedTradeMetrics({ ...trade, close_premium: null, review: { target_capture_pct: 50 } }).targetGap).toBeNull();
});

test('journal review saves retrospective targets without changing fills and retries the same request', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  const trade = { id: 12, ledger_event_id: 42, ticker: 'AAPL', position: 'short', option_type: 'put',
    open_premium: 2, close_premium: .5, contracts: 1, strike: 100, pnl: 150, net_pnl: 148, fees: 2,
    opened_at: '2025-09-01', closed_at: '2025-09-10', expiry: '2025-09-19' };
  const fetch = vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [trade] });
  const save = vi.spyOn(stockApi, 'recordAccountingEntry').mockRejectedValueOnce(new Error('Review temporarily unavailable')).mockResolvedValue({ id: 51 });
  const fills = vi.spyOn(stockApi, 'updateClosedOption');
  render(<Journal />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review AAPL trade 12' }));
  const dialog = screen.getByRole('dialog', { name: 'Review AAPL closed trade' });
  expect(within(dialog).getByText(/not verified pre-trade plans/)).toBeTruthy();
  fireEvent.change(within(dialog).getByLabelText('Exit reason'), { target: { value: 'profit_target' } });
  fireEvent.change(within(dialog).getByLabelText('Target capture (%)'), { target: { value: '101' } });
  expect(within(dialog).getByRole('button', { name: 'Save review' }).disabled).toBe(true);
  fireEvent.change(within(dialog).getByLabelText('Target capture (%)'), { target: { value: '50' } });
  fireEvent.change(within(dialog).getByLabelText('Review notes'), { target: { value: 'Closed early' } });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save review' }));
  await screen.findByText('Review temporarily unavailable');
  const first = save.mock.calls[0][0];
  expect(first).toMatchObject({ kind: 'review', event_id: 42, target_capture_pct: 50, exit_reason: 'profit_target', note: 'Closed early' });
  fetch.mockResolvedValue({ trades: [{ ...trade, review: { review_id: 51, target_capture_pct: 50, exit_reason: 'profit_target', review_note: 'Closed early' } }] });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save review' }));
  await screen.findByText('+25.0 pp');
  expect(save.mock.calls[1][0]).toEqual(first);
  expect(fills).not.toHaveBeenCalled();
  const table = screen.getByRole('table', { name: 'Recorded trades' });
  expect(within(table).getByText('75.0%')).toBeTruthy();
  expect(within(table).getByText('Target 50.0% ·', { exact: false })).toBeTruthy();
  expect(within(table).getByRole('cell', { name: 'Profit target' })).toBeTruthy();
  expect(within(table).getByText('Sep 1, 2025 → Sep 10, 2025', { exact: false })).toBeTruthy();
  expect(within(table).getByText('9d held · 9 DTE left')).toBeTruthy();
  expect(within(table).getByText('Gross $150 · fees $2')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Review AAPL trade 12' }));
  expect(screen.getByLabelText('Target capture (%)').value).toBe('50');
  expect(screen.getByLabelText('Review notes').value).toBe('Closed early');
});

test('journal long option review has no capture target and can clear exit reason', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [{ id: 1, ledger_event_id: 7, ticker: 'AAPL',
    position: 'long', option_type: 'call', open_premium: 2, close_premium: 3, review: { exit_reason: 'stop' } }] });
  const save = vi.spyOn(stockApi, 'recordAccountingEntry').mockResolvedValue({ id: 8 });
  render(<Journal />);
  fireEvent.click(await screen.findByRole('button', { name: 'Review AAPL trade 1' }));
  expect(screen.queryByLabelText('Target capture (%)')).toBeNull();
  fireEvent.change(screen.getByLabelText('Exit reason'), { target: { value: '' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save review' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({ kind: 'review', event_id: 7, exit_reason: null, target_capture_pct: null })));
  await screen.findByText('AAPL review saved.');
});

test('journal cycle view links remaining whole contracts and reverses allocations with retry safety', async () => {
  const report = { tax_lots: [{ opening_event_id: 42, source_id: 12, ticker: 'AAPL', source: 'closed_options', position: 'short', option_type: 'put', quantity: 2, closed_at: '2025-09-10' }],
    manual_entries: [{ kind: 'link', event_id: 42, quantity: '1' }], cycles: [{ name: 'AAPL wheel', put_pnl: 150, call_pnl: 300,
      stock_pnl: -1000, fees: 13, realized_pnl: -563, open_links: 1, unresolved_links: 1,
      links: [{ link_id: 51, event_id: 42, source: 'closed_options', ticker: 'AAPL', quantity: '1', status: 'realized' }] }] };
  const fetch = vi.spyOn(stockApi, 'fetchAccountingReport').mockResolvedValue(report);
  const save = vi.spyOn(stockApi, 'recordAccountingEntry').mockRejectedValueOnce(new Error('Allocation temporarily unavailable')).mockResolvedValue({ id: 52 });
  render(<WheelCycles />);
  await screen.findByRole('option', { name: /1 available/ });
  expect(screen.getByText('-$563.00').className).toBe('negative');
  expect(screen.getByText(/unresolved allocations are excluded/)).toBeTruthy();
  expect(screen.getByText(/open lot allocations are excluded/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Closed trade'), { target: { value: '42' } });
  fireEvent.change(screen.getByLabelText('Cycle name'), { target: { value: 'AAPL wheel' } });
  for (const quantity of ['1.5', '2']) {
    fireEvent.change(screen.getByLabelText('Contracts to link'), { target: { value: quantity } });
    expect(screen.getByRole('button', { name: 'Link to cycle' }).disabled).toBe(true);
  }
  fireEvent.change(screen.getByLabelText('Contracts to link'), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Link to cycle' }));
  await screen.findByText('Allocation temporarily unavailable');
  const first = save.mock.calls[0][0];
  expect(first).toMatchObject({ kind: 'link', event_id: 42, cycle: 'AAPL wheel', quantity: '1' });
  fetch.mockResolvedValue({ ...report, manual_entries: [...report.manual_entries, { kind: 'link', event_id: 42, quantity: '1' }] });
  fireEvent.click(screen.getByRole('button', { name: 'Link to cycle' }));
  await screen.findByText('No unallocated closed trades available.');
  expect(save.mock.calls[1][0]).toEqual(first);
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  fireEvent.click(screen.getByRole('button', { name: 'Remove allocation 51' }));
  expect(save).toHaveBeenCalledTimes(2);
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: 'Remove allocation 51' }));
  await screen.findByText('Allocation reversed; audit history retained.');
  expect(save).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'reverse', event_id: 51 }));
});

test('journal option expectancy and profit factor exclude missing results and stocks', () => {
  const option = { position: 'short', option_type: 'put' };
  const stats = recordedOptionStats([{ ...option, net_pnl: 75 }, { ...option, net_pnl: -25 }, { ...option, net_pnl: 0 },
    { ...option, net_pnl: null }, { net_pnl: 1000 }]);
  expect(stats).toMatchObject({ count: 3, net: 50, expectancy: 50 / 3, profitFactor: '3.00' });
  expect(stats.winRate).toBeCloseTo(100 / 3);
  expect(recordedOptionStats([]).expectancy).toBeNull();
  expect(recordedOptionStats([{ ...option, net_pnl: 75 }]).profitFactor).toBe('No losses');
});

test('put repair only submits a live listed expiry', async () => {
  vi.spyOn(stockApi, 'fetchOptionExpirations').mockResolvedValue({ expirations: [{ date: '2026-10-09', dte: 4 }] });
  const roll = vi.spyOn(stockApi, 'fetchRollIdeas').mockResolvedValue({ rules: [] });
  render(<RollRepair ticker="NVDA" mode="csp" standalone />);
  await screen.findByRole('option', { name: /Oct 9/ });
  expect(screen.queryByRole('option', { name: /Oct 7/ })).toBeNull();
  fireEvent.change(screen.getByLabelText('Short put strike'), { target: { value: '240' } });
  expect(screen.getByRole('button', { name: 'Find rolls' }).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Expiry'), { target: { value: '2026-10-09' } });
  fireEvent.click(screen.getByRole('button', { name: 'Find rolls' }));
  await waitFor(() => expect(roll).toHaveBeenCalledWith('NVDA', expect.objectContaining({ expiry: '2026-10-09' })));
});

test('put repair can retry unavailable expiry data', async () => {
  vi.spyOn(stockApi, 'fetchOptionExpirations').mockRejectedValueOnce(new Error('Expiry service unavailable'))
    .mockResolvedValue({ expirations: [{ date: '2026-10-09', dte: 4 }] });
  render(<RollRepair ticker="NVDA" mode="csp" standalone />);
  await screen.findByText('Expiry service unavailable');
  fireEvent.click(screen.getByRole('button', { name: 'Retry expiries' }));
  await screen.findByRole('option', { name: /Oct 9/ });
  expect(screen.queryByRole('alert')).toBeNull();
});

test('put repair preserves but blocks an unavailable saved expiry', async () => {
  vi.spyOn(stockApi, 'fetchOptionExpirations').mockResolvedValue({ expirations: [{ date: '2026-10-09', dte: 4 }] });
  const roll = vi.spyOn(stockApi, 'fetchRollIdeas').mockResolvedValue({ rules: [] });
  render(<RollRepair ticker="NVDA" mode="csp" standalone initial={{ expiry: '2026-10-07', shortStrike: 240 }} />);
  await screen.findByText(/Its date has not been changed/);
  expect(screen.getByLabelText('Expiry').value).toBe('2026-10-07');
  expect(screen.getByRole('button', { name: 'Find rolls' }).disabled).toBe(true);
  expect(roll).not.toHaveBeenCalled();
});

test('covered calls switch to weekly and show projected share cost without recording a trade', async () => {
  const fetch = vi.spyOn(stockApi, 'fetchAssignedCalls').mockResolvedValue({ ticker: 'NVDA', spot: 238.9, cost_basis: 226.34,
    shares: 100, contracts: 1, expiry: '2026-10-09', dte: 4, cadence: 'weekly', unrealized_pct: 5.5, note: '',
    ideas: [{ label: 'Balanced', strike: 250, expiry: '2026-10-09', dte: 4, delta: 0.25, mid: 4.05, total_premium: 405,
      premium_adjusted_cost: 222.29, open_interest: 500, liquidity: 'good', return_pct: 1.79, annualized_pct: 163,
      otm_pct: 4.6, if_called_pct: 12.24, prob_called_pct: 22 }] });
  render(<WheelManager />);
  fireEvent.click(screen.getByRole('button', { name: /Assigned/ }));
  fireEvent.change(screen.getByLabelText('Ticker'), { target: { value: 'NVDA' } });
  fireEvent.change(screen.getByLabelText('Cost per share ($)'), { target: { value: '226.34' } });
  fireEvent.change(screen.getByLabelText('Expiry horizon'), { target: { value: 'weekly' } });
  fireEvent.click(screen.getByRole('button', { name: 'Suggest covered calls' }));
  expect(await screen.findByText('$222.29')).toBeTruthy();
  expect(fetch).toHaveBeenLastCalledWith('NVDA', 226.34, 100, 'weekly');
  expect(screen.getByText(/does not change recorded holdings or tax basis/)).toBeTruthy();
  expect(screen.getByLabelText('Cost per share ($)').value).toBe('226.34');
  fireEvent.change(screen.getByLabelText('Expiry horizon'), { target: { value: 'all' } });
  expect(screen.queryByText('$222.29')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Suggest covered calls' }));
  await screen.findByText('$222.29');
  expect(fetch).toHaveBeenLastCalledWith('NVDA', 226.34, 100, 'all');
});

test('covered calls on a large gain show value-based yield, realized gain and the upside-protection call', async () => {
  vi.spyOn(stockApi, 'fetchAssignedCalls').mockResolvedValue({ ticker: 'AMD', spot: 640, cost_basis: 60, shares: 100, contracts: 1,
    expiry: '2027-06-17', dte: 253, cadence: 'leaps', unrealized_pct: 966.7, note: '',
    ideas: [{ label: 'Balanced', strike: 700, expiry: '2027-06-17', dte: 253, delta: 0.25, mid: 40, total_premium: 4000,
      premium_adjusted_cost: 20, open_interest: 150, liquidity: 'good', return_pct: 66.67, annualized_pct: 96.2, yield_pct: 6.25,
      yield_annualized_pct: 9, otm_pct: 9.4, if_called_pct: 1133, if_called_from_today_pct: 15.63, gain_realized_if_called: 64000,
      prob_called_pct: 22, upside_cap: { strike: 770, mid: 25, net_credit: 15, total_net: 1500 } }] });
  render(<WheelManager preset={{ mode: 'assigned', ticker: 'AMD', costBasis: 60 }} />);
  expect(await screen.findByText(/Shares are 966.7% above your cost/)).toBeTruthy();
  expect(screen.getByText('Yield on stock value')).toBeTruthy();
  expect(screen.queryByText('Return on cost')).toBeNull();
  expect(screen.getByText('15.63%')).toBeTruthy();
  expect(screen.getByText(/also buy the \$770 call @ \$25/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Expiry horizon'), { target: { value: 'leaps' } });
  expect(screen.getByText(/gives the stock months or years to rise through the strike/)).toBeTruthy();
});

test('covered calls list all qualifying dates and every strike on the selected date', async () => {
  const ideas = Array.from({ length: 5 }, (_, index) => ({ label: 'Balanced', strike: 250 + index, expiry: '2026-10-09',
    dte: 4, delta: 0.25, mid: 4, total_premium: 400, premium_adjusted_cost: 222.34, open_interest: 500, liquidity: 'good' }));
  vi.spyOn(stockApi, 'fetchAssignedCalls').mockResolvedValue({ ticker: 'NVDA', spot: 238.9, cost_basis: 226.34, shares: 100,
    contracts: 1, expiry: '2026-10-09', ideas, expirations: [
      { date: '2026-10-09', dte: 4, ideas },
      { date: '2026-11-06', dte: 32, earnings_before_expiry: true, ideas: [{ ...ideas[0], expiry: '2026-11-06', premium_adjusted_cost: 220.34 }] },
    ], earnings_date: '2026-10-15', checked_expirations: 4, skipped_expirations: 1, unavailable_expirations: ['2026-10-23'] });
  render(<WheelManager preset={{ mode: 'assigned', ticker: 'NVDA', costBasis: 226.34 }} />);
  await screen.findByLabelText('Eligible expiry');
  expect(screen.getAllByText('$222.34')).toHaveLength(5);
  expect(screen.getByLabelText('Eligible expiry').options).toHaveLength(2);
  expect(screen.getByText(/Results are incomplete/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Eligible expiry'), { target: { value: '2026-11-06' } });
  expect(screen.getByText('$220.34')).toBeTruthy();
  expect(screen.queryByText('$222.34')).toBeNull();
  expect(screen.getByText(/Earnings.*before expiry/)).toBeTruthy();
});

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
  const cell = await within(await screen.findByRole('table', { name: 'Recorded trades' })).findByText(formatted, { exact: true, selector: '.trade-pnl strong' });
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
    await waitFor(() => expect(close).toHaveBeenCalledWith('WDC', 'put', 65, '2027-01-15', Number(price), 1, position, 42, ''));
  });

test('closing links a wheel cycle and expired options record worthless expiry in the selected account', async () => {
  localStorage.setItem('portfolio_account', 'IRA');
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'fixture' });
  const summary = vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchAccounts').mockResolvedValue({ accounts: [
    { name: 'Default', cash: 1000, put_collateral: 0, free_cash: 1000 },
    { name: 'IRA', cash: 9000, put_collateral: 6500, free_cash: 2500, cash_updated_at: '2026-10-06T12:00:00+00:00' }] });
  vi.spyOn(stockApi, 'fetchCorporateActions').mockResolvedValue({ splits: [] });
  vi.spyOn(stockApi, 'fetchOptionsSummary').mockResolvedValue({ total_cost: 240, total_value: null, total_pnl: null, options: [
    { id: 7, ticker: 'WDC', type: 'put', position: 'short', strike: 65, expiry: '2026-10-02', dte: 0, contracts: 1,
      premium: 1.2, market_price: null, current_price: null, pnl: null, expired: true, account: 'IRA' },
    { id: 8, ticker: 'WDC', type: 'put', position: 'short', strike: 60, expiry: '2027-01-15', dte: 100, contracts: 1,
      premium: 1.2, market_price: 0.6, current_price: 64, pnl: 60, expired: false, account: 'IRA' }] });
  const close = vi.spyOn(stockApi, 'closeOption').mockResolvedValue({ cycle: 'WDC wheel' });
  const expire = vi.spyOn(stockApi, 'expireOption').mockResolvedValue({ cycle: 'WDC wheel' });
  vi.spyOn(window, 'prompt').mockReturnValue('WDC wheel');
  render(<Portfolio />);
  await waitFor(() => expect(summary).toHaveBeenCalledWith('IRA'));
  expect(await screen.findByText('$2,500')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /Options/ }));
  fireEvent.click(await screen.findByRole('button', { name: 'Expired worthless WDC 65 put' }));
  await waitFor(() => expect(expire).toHaveBeenCalledWith(7, 'WDC wheel'));
  expect(screen.queryByRole('button', { name: 'Expired worthless WDC 60 put' })).toBeNull();
  screen.getByLabelText('Premium ($)').scrollIntoView = vi.fn();
  fireEvent.click(screen.getAllByTitle('Close this option lot')[1]);
  fireEvent.change(screen.getByLabelText('Buy-back price ($/share)'), { target: { value: '0.3' } });
  fireEvent.change(screen.getByLabelText('Wheel cycle (optional)'), { target: { value: ' WDC wheel ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Buy to Close', exact: true }));
  await waitFor(() => expect(close).toHaveBeenCalledWith('WDC', 'put', 60, '2027-01-15', 0.3, 1, 'short', 8, 'WDC wheel'));
  expect(await screen.findByText(/linked to WDC wheel/)).toBeTruthy();
  localStorage.removeItem('portfolio_account');
});

test('P&L calendar totals each close day, shades wins and losses, and pages back to earlier months', () => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 9, 7, 12));
  try {
    const rows = [
      { key: 'option:1', ticker: 'AMD', kind: 'short put', closed_at: '2026-10-05 20:00:00', pnl: 310, net_pnl: 300 },
      { key: 'stock:2', ticker: 'PYPL', kind: 'Stock', closed_at: '2026-10-05', pnl: -100, net_pnl: null },
      { key: 'option:3', ticker: 'TSLA', kind: 'short call', closed_at: '2026-10-01', pnl: -450, net_pnl: -452 },
      { key: 'option:4', ticker: 'WDC', kind: 'short put', closed_at: '2026-09-29', pnl: 1200, net_pnl: 1195 },
      { key: 'option:5', ticker: 'BAD', kind: 'short put', closed_at: null, pnl: 5 },
    ];
    const days = dailyPnl(rows);
    expect(days.get('2026-10-05').pnl).toBe(200);
    expect(days.get('2026-10-05').trades).toHaveLength(2);
    expect(days.size).toBe(3);
    expect(compactMoney(1195)).toBe('+$1.2K');
    expect(compactMoney(-452)).toBe('-$452');
    render(<PnlCalendar rows={rows} />);
    expect(screen.getByText('October 2026')).toBeTruthy();
    expect(screen.getByText('-$252.00')).toBeTruthy();
    expect(screen.getByText(/1 green \/ 1 red day/)).toBeTruthy();
    const win = screen.getByRole('button', { name: 'October 5: $200.00 realized across 2 closed trades' });
    expect(win.style.background).toContain('34, 197, 94');
    expect(screen.getByRole('button', { name: 'October 1: -$452.00 realized across 1 closed trade' }).style.background).toContain('239, 68, 68');
    expect(screen.getByRole('button', { name: 'Next month' }).disabled).toBe(true);
    fireEvent.click(win);
    expect(screen.getByText('PYPL')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Previous month' }));
    expect(screen.getByText('September 2026')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'September 29: $1,195.00 realized across 1 closed trade' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Previous month' }).disabled).toBe(true);
    const grid = screen.getByRole('group', { name: 'Realized P&L calendar, September 2026' });
    fireEvent.touchStart(grid, { touches: [{ clientX: 200 }] });
    fireEvent.touchEnd(grid, { changedTouches: [{ clientX: 100 }] });
    expect(screen.getByText('October 2026')).toBeTruthy();
  } finally {
    vi.useRealTimers();
  }
});

test('expiration ladder shows assignment cash, risk-aware moneyness and the lower-gain lot plan', async () => {
  const plan = (gain, basis, longTerm) => ({ gain, short_term_gain: longTerm ? 0 : gain, long_term_gain: longTerm ? gain : 0, uncovered_shares: 0,
    lots: [{ lot_id: basis, acquired: '2019-01-02', shares: 100, basis, gain, long_term: longTerm }] });
  vi.spyOn(stockApi, 'fetchExpiryLadder').mockResolvedValue({ note: 'Model note.', free_cash: { Default: 5000, E: 1000 }, expiries: [{
    expiry: '2026-12-18', dte: 72, contracts: 3, cash_if_all_puts_assigned: 14000, cash_if_itm_puts_assigned: 14000,
    shares_if_itm_calls_assigned: 100, gain_if_itm_calls_assigned: 52000, positions: [
      { id: 1, ticker: 'AMD', account: 'E', type: 'call', position: 'short', strike: 580, contracts: 1, spot: 640, itm: true, distance_pct: -9.4,
        chance_itm_pct: 70, shares_if_assigned: 100, proceeds_if_assigned: 58000, gain_difference: 44000,
        oldest_first: plan(52000, 60, true), highest_cost_first: plan(8000, 500, false) },
      { id: 2, ticker: 'KO', account: 'Default', type: 'put', position: 'short', strike: 70, contracts: 2, spot: 65, itm: true, cash_if_assigned: 14000 },
      { id: 3, ticker: 'QQQ', account: 'E', type: 'put', position: 'long', strike: 550, contracts: 1, spot: 700, itm: false, intrinsic_now: 0 }] }] });
  render(<ExpiryLadder version="1" />);
  expect(await screen.findByText(/in-the-money puts need \$14,000/)).toBeTruthy();
  expect(screen.getByText(/\$44,000 less gain with highest-cost lots/)).toBeTruthy();
  expect(screen.getByText(/Highest-cost lots first: \$8,000 \(short-term \$8,000/)).toBeTruthy();
  const inTheMoney = screen.getAllByText('in the money');
  expect(inTheMoney.every(element => element.className === 'negative')).toBe(true);
  expect(screen.getByText('out of the money').className).toBe('market-sub');
  expect(screen.getByText(/\(free cash \$5,000\)/)).toBeTruthy();
});

test('trading rules save blanks as off, and the trim planner shows the sale steps', async () => {
  vi.spyOn(stockApi, 'fetchTradingRules').mockResolvedValue({ max_position_pct: 30, min_free_cash_pct: null, take_profit_pct: null,
    no_calls_below_cost: false, no_short_through_earnings: false });
  const save = vi.spyOn(stockApi, 'saveTradingRules').mockResolvedValue({});
  const saved = vi.fn();
  render(<TradingRules onSaved={saved} />);
  const limit = await screen.findByLabelText('Max % of stock value in one stock');
  expect(limit.value).toBe('30');
  fireEvent.change(screen.getByLabelText('Take profit on short options at % of premium captured'), { target: { value: '60' } });
  fireEvent.change(screen.getByLabelText(/Close short options when the loss reaches/), { target: { value: '2' } });
  fireEvent.click(screen.getByLabelText('Never sell a call below my average cost'));
  fireEvent.click(screen.getByRole('button', { name: 'Save rules' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith({ max_position_pct: 30, min_free_cash_pct: null, take_profit_pct: 60,
    stop_loss_multiple: 2, no_calls_below_cost: true, no_short_through_earnings: false }));
  expect(saved).toHaveBeenCalled();
  cleanup();
  const plan = vi.spyOn(stockApi, 'fetchTrimPlan').mockResolvedValue({ ticker: 'AMD', price: 640, shares_held: 600, current_pct: 74,
    target_pct: 30, shares_to_sell: 380.5, total_proceeds: 260000, total_short_term_gain: 220000, total_long_term_gain: 0, note: 'Plan note.',
    tranches: [{ step: 1, price: 640, shares: 190.25, proceeds: 121760, covered_call_contracts: 1, short_term_gain: 110000, long_term_gain: 0, weight_after_pct: 61 },
      { step: 2, price: 672, shares: 190.25, proceeds: 127848, covered_call_contracts: 1, short_term_gain: 110000, long_term_gain: 0, weight_after_pct: 30 }] });
  render(<TrimPlanner tickers={['AMD', 'KO']} initialTicker="AMD" />);
  fireEvent.click(screen.getByRole('button', { name: 'Plan trim' }));
  const table = await screen.findByRole('table', { name: 'Trim steps' });
  expect(plan).toHaveBeenCalledWith('AMD', 30, 4, 5);
  expect(within(table).getByText('1 × $672 call')).toBeTruthy();
  expect(screen.getByText('380.5')).toBeTruthy();
});

test('buy zones save a target and show the put that pays you to wait; event week groups dates', async () => {
  const zones = vi.spyOn(stockApi, 'fetchBuyZones')
    .mockResolvedValueOnce({ items: [], note: '' })
    .mockResolvedValueOnce({ note: 'Note.', items: [{ ticker: 'NVDA', target: 200, price: 237.47, distance_pct: 15.8, in_zone: false,
      put: { strike: 200, expiry: '2026-11-13', premium: 79, effective_entry: 199.21, cash_needed: 20000, annualized_pct: 3.9, chance_assigned_pct: 8 } }] });
  const save = vi.spyOn(stockApi, 'saveBuyZone').mockResolvedValue({});
  render(<BuyZones />);
  expect(await screen.findByText('No buy zones yet.')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Buy zone ticker'), { target: { value: 'nvda' } });
  fireEvent.change(screen.getByLabelText('Buy price'), { target: { value: '200' } });
  fireEvent.click(screen.getByRole('button', { name: 'Set buy zone' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('NVDA', 200));
  expect(await screen.findByText(/Sell \$200 put 2026-11-13/)).toBeTruthy();
  expect(screen.getByText(/Buy-in \$199\.21 if assigned/)).toBeTruthy();
  expect(zones).toHaveBeenCalledTimes(2);
  cleanup();
  vi.spyOn(stockApi, 'fetchWatchlistEvents').mockResolvedValue({ checked: 3, events: [
    { date: '2026-10-08', ticker: 'ORCL', kind: 'ex_dividend', held: true },
    { date: '2026-10-20', ticker: 'NFLX', kind: 'earnings', timing: 'after close', confirmed: false, held: true }] });
  const onSelect = vi.fn();
  render(<EventWeek onSelect={onSelect} />);
  expect(await screen.findByText(/earnings \(after close\)\*/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'ORCL' }));
  expect(onSelect).toHaveBeenCalledWith('ORCL');
});

test('command palette matches tools before tickers and runs the highlighted item from the keyboard', () => {
  expect(matchCommands('trim', true).map(c => c.label)).toEqual(['Portfolio Risk: Trim planner', 'Open TRIM stock page']);
  expect(matchCommands('amd', true).map(c => c.label)).toEqual(['Open AMD stock page']);
  expect(matchCommands('status', false).some(c => c.label === 'System status')).toBe(false);
  expect(matchCommands('risk ladder', true)[0].go).toEqual({ tab: 'portfolio', section: 'risk', anchor: 'expiry-ladder' });
  const run = vi.fn();
  const close = vi.fn();
  render(<CommandPalette signedIn onClose={close} onRun={run} />);
  const input = screen.getByRole('combobox', { name: 'Jump to' });
  fireEvent.change(input, { target: { value: 'journal' } });
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  expect(screen.getAllByRole('option')[1].getAttribute('aria-selected')).toBe('true');
  fireEvent.keyDown(input, { key: 'Enter' });
  expect(close).toHaveBeenCalled();
  expect(run).toHaveBeenCalledWith({ tab: 'journal', anchor: 'edge-report' });
});

test('last-look changes report price move, new headlines and earnings changes', () => {
  const previous = { at: 1, price: 100, earnings: '2026-10-20', headlines: ['https://a'] };
  const changes = lastLookChanges(previous, { price: 110, earnings: '2026-10-27', lastEarnings: null,
    articles: [{ url: 'https://a', title: 'Old' }, { url: 'https://b', title: 'New one' }] });
  expect(changes.priceChangePct).toBeCloseTo(10);
  expect(changes.headlines).toEqual([{ title: 'New one', url: 'https://b' }]);
  expect(changes.earningsMoved).toEqual({ from: '2026-10-20', to: '2026-10-27' });
  expect(changes.any).toBe(true);
  expect(lastLookChanges(null, { price: 1, articles: [] })).toBeNull();
  const reported = lastLookChanges(previous, { price: 100, earnings: '2027-01-20', lastEarnings: '2026-10-20', articles: [] });
  expect(reported.reported).toBe('2026-10-20');
  expect(lastLookChanges({ ...previous, earnings: null }, { price: 100, articles: [{ url: 'https://a' }] }).any).toBe(false);
});

test('editing a stock lot can correct its purchase date', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'fixture' });
  vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ total_invested: 5938, total_current: 64000, total_pnl: 58062, total_pnl_pct: 977,
    holdings: [{ id: 15, ticker: 'AMD', shares: 100, buy_price: 59.38, current_price: 640, current_value: 64000, cost_value: 5938,
      pnl: 58062, pnl_pct: 977, date_added: '2026-10-07 14:00:00', account: 'Default' }] });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchAccounts').mockResolvedValue({ accounts: [{ name: 'Default', cash: null, put_collateral: 0, free_cash: null }] });
  vi.spyOn(stockApi, 'fetchCorporateActions').mockResolvedValue({ splits: [] });
  vi.spyOn(stockApi, 'fetchOptionsSummary').mockResolvedValue({ options: [] });
  const edit = vi.spyOn(stockApi, 'editHolding').mockResolvedValue({});
  render(<Portfolio />);
  fireEvent.click(await screen.findByTitle('Edit'));
  expect(screen.getByLabelText('Purchase date').value).toBe('2026-10-07');
  fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2019-03-15' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(edit).toHaveBeenCalledWith(15, 'AMD', 100, 59.38, '2019-03-15'));
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
  expect(within(screen.getByRole('table', { name: 'Recorded trades' })).getByText('$83.7', { exact: true })).toBeTruthy();
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
  await within(await screen.findByRole('table', { name: 'Recorded trades' })).findByText('$92.5', { exact: true });
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

test('limit ladder, post-earnings window and assignment share', () => {
  expect(limitLadder(1.2, 1.4)).toEqual({ steps: [1.3, 1.29, 1.28], floor: 1.2, tick: 0.01 });
  expect(limitLadder(14.4, 14.7, 'buy')).toEqual({ steps: [14.55, 14.6, 14.65], floor: 14.7, tick: 0.05 });
  expect(limitLadder(0.05, 0.06).steps).toEqual([0.06, 0.05]);  // never below the bid
  expect(limitLadder(0, 1)).toBeNull();
  expect([1, 4, 5].map(d => isPostEarnings(d))).toEqual([true, true, false]);
  expect(isPostEarnings(0, 'before open')).toBe(true);
  expect(isPostEarnings(0, 'after close')).toBe(false);
  render(<AssignmentShare amount={37500} account={{ value: 120000, cash_entered: true }} />);
  expect(screen.getByText(/of your account/).textContent).toMatch(/If assigned: 31% of your account \(\$37,500 of \$120,000\) — one stock would dominate/);
});

test('wheel freshness shows quote age and refresh cadence', () => {
  const now = Date.parse('2026-10-08T16:38:00Z');
  const base = { updated_at: '2026-10-08T16:00:00Z', status: 'ready', refresh_minutes: 15 };
  expect(wheelFreshness({ ...base, market_open: true }, now)).toMatch(/\(38 min ago\) · refreshes every 15 min while the market is open$/);
  expect(wheelFreshness({ ...base, market_open: false }, now)).toMatch(/market closed: last-session premiums$/);
  expect(wheelFreshness({ ...base, status: 'running' }, now)).toMatch(/refreshing…$/);
  expect(wheelFreshness(base, Date.parse('2026-10-09T16:00:00Z'))).not.toMatch(/ago/);
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

test('account ledger assigns deposits and withdrawals to a brokerage account', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchAccounts').mockResolvedValue({ accounts: [{ name: 'Default' }, { name: 'IRA' }] });
  const submissions = [];
  vi.spyOn(stockApi, 'authFetch').mockImplementation(async (url, options) => {
    if (url.endsWith('/entries')) { submissions.push(JSON.parse(options.body)); return new Response(JSON.stringify({ id: 2 })); }
    return new Response(JSON.stringify(url.endsWith('/report') ? { fees: 0, external_cash_flow: 0, dividends: 0, twr: { pct: null },
      manual_entries: [{ id: 2, kind: 'deposit', amount: 500, account: 'IRA', occurred_at: '2026-01-01T12:00:00Z' }], tax_lots: [], cycles: [], notes: [] } : { events: [] }));
  });
  const { container } = render(<Accounting />);
  expect(await screen.findByText('IRA')).toBeTruthy();
  expect(screen.queryByLabelText('Brokerage account')).toBeNull();
  fireEvent.change(screen.getByLabelText('Entry'), { target: { value: 'deposit' } });
  fireEvent.change(screen.getByLabelText('Occurred at'), { target: { value: '2026-01-01T12:00' } });
  fireEvent.change(screen.getByLabelText('Amount ($)'), { target: { value: '500' } });
  fireEvent.change(screen.getByLabelText('Brokerage account'), { target: { value: 'IRA' } });
  await waitFor(() => expect(container.querySelectorAll('#ledger-accounts option')).toHaveLength(2));
  fireEvent.click(screen.getByRole('button', { name: 'Record entry' }));
  await waitFor(() => expect(submissions).toHaveLength(1));
  expect(submissions[0]).toMatchObject({ kind: 'deposit', amount: '500', account: 'IRA' });
  fireEvent.change(screen.getByLabelText('Entry'), { target: { value: 'fee' } });
  fireEvent.change(screen.getByLabelText('Amount ($)'), { target: { value: '1' } });
  fireEvent.click(screen.getByRole('button', { name: 'Record entry' }));
  await waitFor(() => expect(submissions).toHaveLength(2));
  expect(submissions[1].account).toBeUndefined();
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

const jwt = (sub) => `h.${btoa(JSON.stringify({ sub: String(sub) })).replace(/=+$/, '')}.s`;

test('a tab adopts a same-account rotation made by another tab instead of reusing the consumed token', async () => {
  const [oldAccess, rotatedAccess] = [jwt(7), `${jwt(7)}x`];
  localStorage.setItem('token', oldAccess); localStorage.setItem('refresh_token', 'consumed');
  let resolveRequest;
  const fetch = vi.fn((url, options) => {
    if (url.endsWith('/auth/refresh')) return Promise.resolve(new Response('{}', { status: 401 }));
    if (options.headers.Authorization === `Bearer ${rotatedAccess}`) return Promise.resolve(new Response('{}'));
    return new Promise(resolve => { resolveRequest = resolve; });
  });
  vi.stubGlobal('fetch', fetch);
  const request = authFetch('/private');
  localStorage.setItem('token', rotatedAccess); localStorage.setItem('refresh_token', 'rotated');
  resolveRequest(new Response('{}', { status: 401 }));
  expect((await request).ok).toBe(true);
  expect(fetch.mock.calls.filter(([url]) => url.endsWith('/auth/refresh'))).toHaveLength(0);
  expect(localStorage.getItem('refresh_token')).toBe('rotated');
});

test('cross-tab refreshes take turns through the shared lock', async () => {
  const order = [];
  let tail = Promise.resolve();
  vi.stubGlobal('navigator', { ...navigator, locks: { request: (name, callback) => {
    order.push(name);
    const run = tail.then(callback);
    tail = run.catch(() => {});
    return run;
  } } });
  localStorage.setItem('token', jwt(3)); localStorage.setItem('refresh_token', 'r1');
  vi.stubGlobal('fetch', vi.fn(async (url, options) => url.endsWith('/auth/refresh')
    ? new Response(JSON.stringify({ token: `${jwt(3)}n`, refresh_token: 'r2' }))
    : new Response('{}', { status: options.headers.Authorization === `Bearer ${jwt(3)}n` ? 200 : 401 })));
  expect((await authFetch('/private')).ok).toBe(true);
  expect(order).toEqual(['stockpilot-auth-refresh']);
  expect(localStorage.getItem('refresh_token')).toBe('r2');
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
  expect(eligibleIncomeIdeas(ideas, { ...settings, cash: '10000', earnings: null, noEarnings: true })).toHaveLength(1);
  expect(eligibleIncomeIdeas(ideas, { ...settings, cash: '10000', earnings: '2027-01-10', noEarnings: true })).toHaveLength(0);
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

test('income safety badge ignores cash not yet entered and explains a caution', async () => {
  const safe = { ...pyplPut, bid: .35, ask: .37, liquidity: 'good', checks: [{ ok: true, text: 'Liquid (OI 6,708)' }] };
  const tested = { ...safe, label: 'Balanced', strike: 52, safety: 'caution',
    checks: [{ ok: true, text: 'Liquid' }, { ok: false, text: 'Inside the expected move — a normal move can test it' }] };
  vi.spyOn(stockApi, 'fetchIncomeIdeas').mockResolvedValue({ spot: 52.8, expiry: '2026-10-16', dte: 12, earnings_date: '2026-10-27',
    expected_move: { move: 3.1, low: 49.7, high: 55.9 }, expirations: [{ date: '2026-10-16', dte: 12 }], cash_secured_puts: [safe, tested] });
  render(<IncomeIdeas ticker="PYPL" />);
  await screen.findByText(/Stock \$52.8/);
  fireEvent.click(screen.getByRole('button', { name: 'Cash-Secured Puts' }));
  expect(screen.getByText(/expected move ±\$3.1/)).toBeTruthy();
  expect(screen.getByText(/Passes checks/)).toBeTruthy();
  expect(screen.getAllByText(/Cash needed: \$5,000 per contract/).length).toBe(2);
  expect(screen.getByText('Caution', { selector: '.safety-badge' }).getAttribute('title')).toBe('Failed: Inside the expected move — a normal move can test it');
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

test('journal groups option results by strategy, month, exit reason and account', () => {
  const close = (overrides) => ({ position: 'short', option_type: 'put', open_premium: 1, close_premium: 0.5, ticker: 'AAPL',
    closed_at: '2026-03-10', net_pnl: 50, ...overrides });
  const rows = [close({}), close({ net_pnl: -30, closed_at: '2026-04-02', review: { exit_reason: 'stop' } }),
    close({ option_type: 'call', ticker: 'MSFT', net_pnl: 25, account: 'IRA' }), { ticker: 'SPY', shares: 1, net_pnl: 999 }];
  expect(groupedOptionStats(rows, 'strategy').map(g => [g.key, g.count, g.net])).toEqual([['Short call', 1, 25], ['Short put', 2, 20]]);
  expect(groupedOptionStats(rows, 'month').map(g => g.key)).toEqual(['2026-04', '2026-03']);
  expect(groupedOptionStats(rows, 'exit').find(g => g.key === 'Stop / risk limit').net).toBe(-30);
  expect(groupedOptionStats(rows, 'account').map(g => g.key).sort()).toEqual(['Default', 'IRA']);
});

test('edge report buckets by entry DTE, days held and how closed, and ranks patterns with enough closes', () => {
  const close = (overrides) => ({ position: 'short', option_type: 'put', ticker: 'AMD', open_premium: 2, close_premium: 0.8,
    opened_at: '2026-03-01', closed_at: '2026-03-06', expiry: '2026-03-13', net_pnl: 120, ...overrides });
  expect(howClosed(close({}))).toBe('Closed early, 50%+ captured');
  expect(howClosed(close({ close_premium: 1.5 }))).toBe('Closed early, under 50% captured');
  expect(howClosed(close({ close_premium: 3 }))).toBe('Closed early at a loss');
  expect(howClosed(close({ closed_at: '2026-03-13', close_premium: 0 }))).toBe('Held to expiry');
  expect(howClosed(close({ position: 'long' }))).toBe('Closed before expiry');
  const weekly = Array.from({ length: 5 }, () => close({}));
  const leaps = Array.from({ length: 5 }, () => close({ ticker: 'TSLA', option_type: 'call', opened_at: '2025-01-02', expiry: '2026-06-18',
    close_premium: 4, net_pnl: -200 }));
  const rows = [...weekly, ...leaps, close({ ticker: 'ONE', net_pnl: 5000 })];
  expect(groupedOptionStats(rows, 'dte').map(g => g.key)).toEqual(['8-21 days', '91+ days']);
  expect(groupedOptionStats(rows, 'held').map(g => g.key)).toEqual(['4-14 days', '31+ days']);
  const edge = edgeHighlights(rows);
  expect(edge.best.map(g => g.key)).not.toContain('ONE');
  expect(edge.best.length).toBeLessThanOrEqual(3);
  expect(edge.best.every(g => g.count >= 5 && g.expectancy > 0)).toBe(true);
  expect(edge.worst.map(g => g.expectancy)).toEqual([-200, -200, -200]);
  expect(edge.worst.map(g => g.key)).not.toContain('Unknown');
});

test('ticker search suggests companies and supports keyboard selection', async () => {
  const search = vi.spyOn(stockApi, 'searchSymbols').mockResolvedValue({ results: [
    { symbol: 'AAPL', name: 'Apple Inc.' }, { symbol: 'APP', name: 'AppLovin', exchange: 'NASDAQ' }] });
  const onSearch = vi.fn();
  render(<SearchBar onSearch={onSearch} loading={false} activeTicker="NVDA" />);
  const input = screen.getByRole('combobox', { name: 'Ticker or company name' });
  fireEvent.change(input, { target: { value: 'apple' } });
  expect(await screen.findByRole('option', { name: /AppLovin/ })).toBeTruthy();
  expect(search).toHaveBeenCalledWith('apple', expect.any(AbortSignal));
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  fireEvent.keyDown(input, { key: 'ArrowDown' });
  expect(screen.getByRole('option', { name: /AppLovin/ }).getAttribute('aria-selected')).toBe('true');
  fireEvent.submit(input.closest('form'));
  expect(onSearch).toHaveBeenCalledWith('APP');
  fireEvent.change(input, { target: { value: 'apple' } });
  await screen.findByRole('option', { name: /Apple Inc/ });
  fireEvent.submit(input.closest('form'));
  expect(onSearch).toHaveBeenLastCalledWith('AAPL');
});

test('signed-in watchlist filters lists, saves notes and shows next earnings', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 9 }, token: 'fixture' });
  localStorage.removeItem('watchlist_tab:9');
  vi.spyOn(stockApi, 'authFetch').mockResolvedValue(new Response(JSON.stringify({ stocks: [
    { ticker: 'AAPL', name: 'Apple', price: 200 }, { ticker: 'KO', name: 'Coca-Cola', price: 60 }] })));
  const overview = (koLists, note = '') => ({ lists: ['Main', 'Growth', 'Income'], items: [
    { ticker: 'AAPL', lists: ['Growth', 'Income'], note: 'Buy under 180' }, { ticker: 'KO', lists: koLists, note }] });
  vi.spyOn(stockApi, 'fetchWatchlistItems').mockResolvedValue(overview(['Income']));
  const ahead = new Date(Date.now() + 5 * 86400000);
  const soon = `${ahead.getFullYear()}-${String(ahead.getMonth() + 1).padStart(2, '0')}-${String(ahead.getDate()).padStart(2, '0')}`;
  vi.spyOn(stockApi, 'fetchWatchlistEarnings').mockResolvedValue({ items: [
    { ticker: 'AAPL', next: soon, timing: 'after close', confirmed: true }, { ticker: 'KO', next: null }] });
  const save = vi.spyOn(stockApi, 'updateWatchlistItem')
    .mockResolvedValueOnce(overview(['Income', 'Growth']))
    .mockResolvedValueOnce(overview(['Income', 'Growth'], 'Dividend raise in Feb'));
  render(<Watchlist />);
  expect(await screen.findByText('Buy under 180')).toBeTruthy();
  expect(await screen.findByText(/\(5d\)/)).toBeTruthy();
  const tabs = screen.getByRole('tablist', { name: 'Watchlist lists' });
  expect(within(tabs).getAllByRole('tab').map(tab => tab.textContent)).toEqual(['All2', 'Main0', 'Growth1', 'Income2']);
  fireEvent.click(within(tabs).getByRole('tab', { name: /Growth/ }));
  expect(screen.queryByText('Coca-Cola')).toBeNull();
  expect(localStorage.getItem('watchlist_tab:9')).toBe('Growth');
  fireEvent.keyDown(tabs, { key: 'ArrowRight' });
  expect(within(tabs).getByRole('tab', { name: /Income/ }).getAttribute('aria-selected')).toBe('true');
  expect(screen.getByText('Coca-Cola')).toBeTruthy();
  fireEvent.click(within(tabs).getByRole('tab', { name: /Main/ }));
  expect(screen.getByText(/No symbols in Main yet/)).toBeTruthy();
  fireEvent.click(within(tabs).getByRole('tab', { name: /All/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Lists for KO' }));
  const picker = screen.getByRole('group', { name: 'Lists for KO' });
  expect(within(picker).getByRole('checkbox', { name: 'Income' }).disabled).toBe(true);
  fireEvent.click(within(picker).getByRole('checkbox', { name: 'Growth' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('KO', ['Income', 'Growth'], ''));
  await waitFor(() => expect(within(picker).getByRole('checkbox', { name: 'Income' }).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Note for KO' }));
  fireEvent.change(screen.getByLabelText('Note'), { target: { value: 'Dividend raise in Feb' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(save).toHaveBeenLastCalledWith('KO', ['Income', 'Growth'], 'Dividend raise in Feb'));
  expect(await screen.findByText('Dividend raise in Feb')).toBeTruthy();
});

test('watchlist lists can be created, renamed, reordered and deleted', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 10 }, token: 'fixture' });
  localStorage.removeItem('watchlist_tab:10');
  vi.spyOn(stockApi, 'authFetch').mockResolvedValue(new Response(JSON.stringify({ stocks: [{ ticker: 'AAPL', name: 'Apple', price: 200 }] })));
  const item = [{ ticker: 'AAPL', lists: ['Main'], note: '' }];
  vi.spyOn(stockApi, 'fetchWatchlistItems').mockResolvedValue({ lists: ['Main'], items: item });
  vi.spyOn(stockApi, 'fetchWatchlistEarnings').mockResolvedValue({ items: [] });
  const create = vi.spyOn(stockApi, 'createWatchlistList').mockResolvedValue({ lists: ['Main', 'Earnings plays'], items: item });
  const rename = vi.spyOn(stockApi, 'renameWatchlistList').mockResolvedValue({ lists: ['Main', 'Earnings'], items: item });
  const reorder = vi.spyOn(stockApi, 'reorderWatchlistLists').mockResolvedValue({ lists: ['Earnings', 'Main'], items: item });
  const remove = vi.spyOn(stockApi, 'deleteWatchlistList').mockResolvedValue({ lists: ['Main'], items: item });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
  render(<Watchlist />);
  fireEvent.click(await screen.findByRole('button', { name: '+ New list' }));
  fireEvent.change(screen.getByLabelText('New list name'), { target: { value: '  Earnings   plays ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create' }));
  await waitFor(() => expect(create).toHaveBeenCalledWith('Earnings plays'));
  const tab = await screen.findByRole('tab', { name: /Earnings plays/ });
  expect(tab.getAttribute('aria-selected')).toBe('true');
  expect(screen.getByText(/No symbols in Earnings plays yet/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
  fireEvent.change(screen.getByLabelText('Rename "Earnings plays" to'), { target: { value: 'Earnings' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save name' }));
  await waitFor(() => expect(rename).toHaveBeenCalledWith('Earnings plays', 'Earnings'));
  expect((await screen.findByRole('tab', { name: /^Earnings/ })).getAttribute('aria-selected')).toBe('true');
  expect(screen.getByRole('button', { name: 'Move list right' }).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Move list left' }));
  await waitFor(() => expect(reorder).toHaveBeenCalledWith(['Earnings', 'Main']));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Delete list' }).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Delete list' }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Delete list' }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith('Earnings'));
  expect(confirm).toHaveBeenCalledTimes(2);
  await waitFor(() => expect(screen.getByRole('tab', { name: /All/ }).getAttribute('aria-selected')).toBe('true'));
  fireEvent.click(screen.getByRole('tab', { name: /Main/ }));
  expect(screen.queryByRole('button', { name: 'Delete list' })).toBeNull();
});

test('account value history shows flow-adjusted return and drawdown and records on demand', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const history = vi.spyOn(stockApi, 'fetchNavHistory').mockResolvedValue({ series: [
    { day: '2026-10-01', nav: 100000 }, { day: '2026-10-02', nav: 95000 }, { day: '2026-10-03', nav: null }],
    return_pct: -5, max_drawdown_pct: -5, flow_adjusted: true, note: 'Deposits and withdrawals from the Account ledger are removed from returns.' });
  vi.spyOn(stockApi, 'recordNavSnapshot').mockResolvedValue({ snapshots: [{ account: 'IRA', complete: false }] });
  render(<NavHistory account="" />);
  expect(await screen.findByText('Time-weighted return')).toBeTruthy();
  expect(screen.getByText('$95,000')).toBeTruthy();
  expect(screen.getAllByText('-5%').length).toBe(2);
  fireEvent.click(screen.getByRole('button', { name: 'Record value now' }));
  expect(await screen.findByText(/Incomplete \(missing quotes or cash\): IRA/)).toBeTruthy();
  expect(history).toHaveBeenCalledTimes(2);
});

test('split notice applies a pending split only after confirmation', async () => {
  vi.spyOn(stockApi, 'fetchCorporateActions').mockResolvedValue({ splits: [
    { ticker: 'NVDA', split_date: '2024-06-10', ratio: 10, label: '10-for-1', lots: 2, options: 1, options_adjustable: true }] });
  const apply = vi.spyOn(stockApi, 'applySplit').mockResolvedValue({ ticker: 'NVDA', lots: 2, options: 1, options_skipped: 0 });
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
  const onApplied = vi.fn();
  render(<CorporateActions version={0} onApplied={onApplied} />);
  const button = await screen.findByRole('button', { name: 'Apply adjustment' });
  fireEvent.click(button);
  expect(apply).not.toHaveBeenCalled();
  fireEvent.click(button);
  await screen.findByText(/NVDA: adjusted 2 lot\(s\) and 1 option/);
  expect(apply).toHaveBeenCalledWith('NVDA', '2024-06-10');
  expect(confirm).toHaveBeenCalledTimes(2);
  expect(onApplied).toHaveBeenCalled();
});

test('corporate actions record a spin-off and prefill a merger for a stale holding', async () => {
  vi.spyOn(stockApi, 'fetchCorporateActions').mockResolvedValue({ splits: [], stale: [{ ticker: 'ATVI', last_quote: '2023-10-12' }],
    applied: [{ kind: 'spinoff', ticker: 'GE', action_date: '2024-04-02', details: { ratio: 0.25, new_ticker: 'GEV', basis_pct: 20 } }] });
  const spinoff = vi.spyOn(stockApi, 'recordSpinoff').mockResolvedValue({ ticker: 'MMM', new_ticker: 'SOLV', lots: 1, basis_moved: 150, options_unadjusted: 1 });
  const merger = vi.spyOn(stockApi, 'recordMerger').mockResolvedValue({ ticker: 'ATVI', new_ticker: null, lots: 2, realized_pnl: 900, options_unadjusted: 0 });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  const onApplied = vi.fn();
  const { container } = render(<CorporateActions version={0} onApplied={onApplied} />);
  expect(await screen.findByText(/no quotes since 2023-10-12/)).toBeTruthy();
  expect(screen.getByRole('table', { name: 'Recorded corporate actions' }).textContent).toContain('0.25 GEV per share, 20% of basis');
  const form = screen.getByRole('form', { name: 'Record corporate action' });
  fireEvent.change(screen.getByLabelText('Ticker you hold'), { target: { value: 'mmm' } });
  fireEvent.change(screen.getByLabelText('Ex-date'), { target: { value: '2024-04-01' } });
  fireEvent.change(screen.getByLabelText('New company ticker'), { target: { value: 'solv' } });
  fireEvent.change(screen.getByLabelText('New shares per share held'), { target: { value: '0.25' } });
  fireEvent.change(screen.getByLabelText('% of cost basis to new company'), { target: { value: '7.5' } });
  fireEvent.submit(form);
  await waitFor(() => expect(spinoff).toHaveBeenCalledWith({ ticker: 'MMM', new_ticker: 'SOLV', action_date: '2024-04-01', ratio: 0.25, basis_pct: 7.5 }));
  expect(await screen.findByText(/MMM: moved \$150 of cost basis to SOLV across 1 lot\(s\)\. 1 open MMM option/)).toBeTruthy();
  expect(onApplied).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Record merger' }));
  expect(container.querySelector('details').open).toBe(true);
  expect(screen.getByLabelText('Ticker you hold').value).toBe('ATVI');
  fireEvent.change(screen.getByLabelText('Closing date'), { target: { value: '2023-10-13' } });
  fireEvent.change(screen.getByLabelText('Cash per share ($)'), { target: { value: '95' } });
  fireEvent.submit(form);
  await waitFor(() => expect(merger).toHaveBeenCalledWith({ ticker: 'ATVI', action_date: '2023-10-13', ratio: 0, cash_per_share: 95 }));
  expect(await screen.findByText(/ATVI: closed 2 lot\(s\) for cash, realized \$900/)).toBeTruthy();
});

test('broker import previews closed trade history into the selected account', async () => {
  const run = vi.spyOn(stockApi, 'importPortfolioCsv')
    .mockResolvedValueOnce({ columns: { symbol: 'Symbol' }, skipped: [], rows: [
      { kind: 'option', ticker: 'MSFT', option_type: 'put', position: 'short', contracts: 1, strike: 380, expiry: '2025-03-21',
        open_premium: 2.5, close_premium: 0.4, opened_at: '2025-02-03', closed_at: '2025-03-03' }] })
    .mockResolvedValueOnce({ columns: {}, skipped: [], rows: [], result: { imported: 1, duplicates: 0, failed: [] } });
  const refresh = vi.fn();
  render(<ImportCsv account="Roth" onImported={refresh} />);
  fireEvent.click(screen.getByRole('button', { name: 'Closed trade history' }));
  fireEvent.change(screen.getByLabelText('Broker CSV file'), { target: { files: [{ size: 100, text: async () => 'Symbol,Quantity\nX,1' }] } });
  fireEvent.click(await screen.findByRole('button', { name: 'Preview' }));
  expect(await screen.findByText('short 1 × $380 put 2025-03-21')).toBeTruthy();
  expect(run).toHaveBeenCalledWith('Symbol,Quantity\nX,1', false, 'history', 'Roth', '', 'append');
  fireEvent.click(screen.getByRole('button', { name: /Import 1 rows/ }));
  expect(await screen.findByText(/Imported 1 closed trade\(s\); 0 already recorded/)).toBeTruthy();
  expect(refresh).toHaveBeenCalled();
});

test('transaction history import summarizes the replay and filters to one broker account', async () => {
  const stock = { kind: 'stock', ticker: 'AAPL', shares: 95, price: 180, acquired: '2026-01-05' };
  const run = vi.spyOn(stockApi, 'importPortfolioCsv')
    .mockResolvedValueOnce({ columns: {}, skipped: [], rows: [stock, { ...stock, ticker: 'MSFT' }], trades: 6, first_date: '2026-01-02',
      last_date: '2026-03-10', ignored: { CDIV: 2 }, source_accounts: ['Individual · Z1', 'Roth · Z2'] })
    .mockResolvedValueOnce({ columns: {}, skipped: [], rows: [stock], trades: 3, ignored: {}, source_accounts: ['Individual · Z1', 'Roth · Z2'] });
  render(<ImportCsv account="Robinhood" />);
  fireEvent.click(screen.getByRole('button', { name: 'Transaction history' }));
  fireEvent.change(screen.getByLabelText('Broker CSV file'), { target: { files: [{ size: 100, text: async () => 'csv' }] } });
  fireEvent.click(await screen.findByRole('button', { name: 'Preview' }));
  expect(await screen.findByText(/6 trade\(s\) from 2026-01-02 to 2026-03-10 rebuild 2 open position\(s\)\. Not trades \(ignored\): CDIV ×2/)).toBeTruthy();
  expect(screen.getAllByText('2026-01-05', { selector: 'td' })).toHaveLength(2);
  fireEvent.change(screen.getByLabelText('Broker account in file'), { target: { value: 'Roth · Z2' } });
  await waitFor(() => expect(run).toHaveBeenLastCalledWith('csv', false, 'activity', 'Robinhood', 'Roth · Z2', 'append'));
  expect(await screen.findByRole('button', { name: /Import 1 rows/ })).toBeTruthy();
});

test('sync import previews differences and applies them to the selected account', async () => {
  const reconcile = { changes: 2, counts: { match: 1, changed: 1, missing: 1 }, stocks: [
    { ticker: 'AMD', recorded: 100, file: 100, status: 'match' }, { ticker: 'MSFT', recorded: 50, file: 60, status: 'changed' }],
    options: [{ label: 'AMD short $580 call 2027-06-17', recorded: 1, file: 0, status: 'missing' }] };
  const run = vi.spyOn(stockApi, 'importPortfolioCsv')
    .mockResolvedValueOnce({ columns: {}, skipped: [], rows: [], reconcile, money_market: [{ ticker: 'VUSXX', amount: 500 }], money_market_total: 500 })
    .mockResolvedValueOnce({ columns: {}, skipped: [], rows: [], reconcile, sync: { kept: 1, removed_records: 2, added_records: 1, cash: { cash: 500 } }, cash: { cash: 500 } });
  const refresh = vi.fn();
  render(<ImportCsv account="Etrade" onImported={refresh} />);
  fireEvent.click(screen.getByRole('button', { name: 'Sync account to this file' }));
  expect(screen.getByText(/removed without recording a sale/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Broker CSV file'), { target: { files: [{ size: 100, text: async () => 'csv' }] } });
  fireEvent.click(await screen.findByRole('button', { name: 'Preview' }));
  const table = await screen.findByRole('table', { name: 'Differences' });
  expect(within(table).queryByText('AMD')).toBeNull();
  expect(within(table).getByText('Replace lots')).toBeTruthy();
  expect(within(table).getByText('Remove')).toBeTruthy();
  expect(screen.getByText(/Syncing sets \$500 as the/)).toBeTruthy();
  expect(run).toHaveBeenLastCalledWith('csv', false, 'positions', 'Etrade', '', 'sync');
  fireEvent.click(screen.getByRole('button', { name: 'Apply 2 change(s)' }));
  expect(await screen.findByText(/Synced Etrade: 1 unchanged, 2 record\(s\) removed, 1 added; cash set to \$500\./)).toBeTruthy();
  expect(refresh).toHaveBeenCalled();
});

test('next steps list suggestions and open covered calls inline', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchNextSteps').mockResolvedValue({ note: 'Rule-based.', items: [
    { level: 'act', code: 'options_act', title: '1 option position(s) need action', points: ['KO $50 put: Take profit.'],
      detail: 'Details in Position alerts below.', link: { kind: 'alerts' } },
    { level: 'idea', code: 'covered_call', ticker: 'AMD', account: 'A', title: 'AMD: 2 uncovered 100-share block(s) in A',
      detail: 'Average cost $100.00.', link: { kind: 'covered_calls', ticker: 'AMD', cost_basis: 100, shares: 200 } }] });
  const calls = vi.spyOn(stockApi, 'fetchAssignedCalls').mockResolvedValue({ ticker: 'AMD', spot: 150, cost_basis: 100, shares: 200,
    contracts: 2, ideas: [], expirations: [], note: '' });
  const { default: NextSteps } = await import('./components/NextSteps');
  render(<NextSteps version="1" onShowAlerts={vi.fn()} onShowTax={vi.fn()} />);
  expect(await screen.findByText('KO $50 put: Take profit.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Show covered calls' }));
  await waitFor(() => expect(calls).toHaveBeenCalledWith('AMD', 100, 200, 'all'));
});