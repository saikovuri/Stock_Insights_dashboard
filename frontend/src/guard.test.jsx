// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within, act } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import { RiskGuard, RiskCheck } from './components/RiskGuard';
import LongTermPlan from './components/LongTermPlan';
import Scorecard from './components/Scorecard';
import Portfolio from './components/Portfolio';
import * as auth from './AuthContext';

beforeEach(() => { vi.spyOn(window, 'confirm').mockReturnValue(true); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

const heat = {
  total_risk: 1300, trading_value: 10000, pct: 13, limit_pct: 8, over_limit: true, unlimited: 0, no_stop: 1, roles_set: false, cash_missing: false,
  note: 'Risk note.', positions: [
    { kind: 'stock', account: 'Default', ticker: 'AAPL', label: '5 shares', risk: 1000, basis: 'no stop: the whole position', flags: ['no_stop'], stop: null },
    { kind: 'structure', account: 'Default', ticker: 'SPY', label: 'Bull put $580/$590 × 1', risk: 300, basis: 'its max loss', flags: [] }],
  circuit: { active: true, until: '2026-11-01', reasons: ['Down 6% of trading capital this month (your limit 5%)'], month_net: -600,
    monthly_limit_pct: 5, streak: 2, streak_limit: 3 },
};

test('risk guard shows open risk, the circuit breaker and saves a stop', async () => {
  vi.spyOn(stockApi, 'fetchRiskHeat').mockResolvedValue(heat);
  const stop = vi.spyOn(stockApi, 'setRiskStop').mockResolvedValue({});
  render(<RiskGuard version="1" />);
  expect(await screen.findByText(/Circuit breaker on until 2026-11-01/)).toBeTruthy();
  expect(screen.getByText('$1,300 · 13%').className).toBe('negative');
  expect(screen.getByText(/1 stock position has no stop/)).toBeTruthy();
  const table = screen.getByRole('table', { name: 'Open risk by position' });
  expect(within(table).getByText('10.0%')).toBeTruthy();
  fireEvent.change(within(table).getByLabelText('Stop price for AAPL'), { target: { value: '190' } });
  fireEvent.click(within(table).getByRole('button', { name: 'Set' }));
  await waitFor(() => expect(stop).toHaveBeenCalledWith('AAPL', 190, 'Default'));
  await waitFor(() => expect(stockApi.fetchRiskHeat).toHaveBeenCalledTimes(2));
});

test('risk check debounces, then shows risk, open risk after and warnings', async () => {
  vi.useFakeTimers();
  const check = vi.spyOn(stockApi, 'checkTradeRisk').mockResolvedValue({ risk: 500, basis: 'down to a $190 stop', risk_pct: 2.5,
    heat_pct_before: 3, heat_pct_after: 5.5, warnings: [{ code: 'trade_risk', text: 'Risks 2.5% of trading capital; your limit is 1%.' }], notes: [] });
  const onResult = vi.fn();
  const proposal = { kind: 'stock', ticker: 'AAPL', shares: 50, price: 200, stop: 190 };
  const { rerender } = render(<RiskCheck proposal={proposal} onResult={onResult} />);
  rerender(<RiskCheck proposal={{ ...proposal }} onResult={onResult} />);
  await act(async () => { await vi.advanceTimersByTimeAsync(450); });
  expect(check).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('status', { name: 'Risk check' }).textContent).toMatch(/\$500.*2.5%.*3% → 5.5%/);
  expect(screen.getByText(/your limit is 1%/)).toBeTruthy();
  expect(onResult).toHaveBeenLastCalledWith(expect.objectContaining({ risk: 500 }));
  rerender(<RiskCheck proposal={null} onResult={onResult} />);
  expect(screen.queryByRole('status', { name: 'Risk check' })).toBeNull();
});

const overview = {
  split: { total: 10000, by_role: { long_term: 5000, trading: 5000 }, trading_pct: 50, target_trading_pct: 20, drift_pct: 30,
    rebalance: { from: 'trading', to: 'long_term', amount: 3000 }, realized_this_year: { trading: -200, long_term: 400 }, roles_set: true, note: 'Split note.',
    accounts: [{ account: 'Default', role: 'trading', role_set: false, value: 5000, cash: 1000 }, { account: 'Roth', role: 'long_term', role_set: true, value: 5000, cash: null }] },
  plan: null, sweep: { month: '2026-09', trading_net: 800, pct: 25, amount: 200, done: false },
};

test('long-term plan sets roles, saves a plan that adds to 100% and records a profit sweep', async () => {
  const load = vi.spyOn(stockApi, 'fetchInvestOverview').mockResolvedValue(overview);
  const role = vi.spyOn(stockApi, 'setAccountRole').mockResolvedValue({});
  const save = vi.spyOn(stockApi, 'saveInvestPlan').mockResolvedValue({});
  const sweep = vi.spyOn(stockApi, 'recordSweep').mockResolvedValue({ cash_updated: ['Default'] });
  render(<LongTermPlan version="1" />);
  expect(await screen.findByText(/moving about/)).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Role for Default'), { target: { value: 'long_term' } });
  await waitFor(() => expect(role).toHaveBeenCalledWith('Default', 'long_term'));
  const form = await screen.findByRole('form', { name: 'Monthly investing plan' });
  expect(within(form).getByLabelText('Account').value).toBe('Roth');
  fireEvent.click(within(form).getByText('+ Add holding'));
  fireEvent.change(within(form).getByLabelText('Target 1 percent'), { target: { value: '60' } });
  fireEvent.change(within(form).getByLabelText('Target 2 ticker'), { target: { value: 'qqq' } });
  fireEvent.change(within(form).getByLabelText('Target 2 percent'), { target: { value: '30' } });
  expect(within(form).getByRole('button', { name: 'Save plan' }).disabled).toBe(true);
  fireEvent.change(within(form).getByLabelText('Target 2 percent'), { target: { value: '40' } });
  fireEvent.click(within(form).getByRole('button', { name: 'Save plan' }));
  await waitFor(() => expect(save).toHaveBeenCalledWith({ account: 'Roth', monthly: 500, day: 1, goal: null, assumed_return_pct: 7,
    targets: [{ ticker: 'VOO', pct: 60 }, { ticker: 'QQQ', pct: 40 }] }));
  fireEvent.click(await screen.findByRole('button', { name: 'Record the move' }));
  await waitFor(() => expect(sweep).toHaveBeenCalledWith({ from_account: 'Default', to_account: 'Roth', amount: 200 }));
  expect(load.mock.calls.length).toBeGreaterThan(1);
});

test('plan status shows this month and projections', async () => {
  vi.spyOn(stockApi, 'fetchInvestOverview').mockResolvedValue({ ...overview, sweep: null, plan: {
    plan: { monthly: 500, day: 1, goal: 100000, assumed_return_pct: 7, targets: [{ ticker: 'VOO', pct: 100 }] }, account: 'Roth', role: 'long_term',
    month: '2026-10', invested_this_month: 300, remaining: 200, due: true, start_value: 5000, outside_plan: {}, note: 'Plan note.',
    buys: [{ ticker: 'VOO', target_pct: 100, value: 5000, current_pct: 100, buy: 200, price: 500, shares: 0.4 }],
    projection: [{ rate_pct: 4, years: { 5: 40000, 10: 80000, 20: 190000 }, years_to_goal: 12.5 },
      { rate_pct: 7, years: { 5: 42000, 10: 93000, 20: 260000 }, years_to_goal: 10.2 }] } });
  render(<LongTermPlan version="1" />);
  expect(await screen.findByText(/to go/)).toBeTruthy();
  expect(screen.getByText(/≈ 0.4 sh at \$500/)).toBeTruthy();
  expect(within(screen.getByRole('table', { name: 'Projection' })).getByText('10.2')).toBeTruthy();
  expect(screen.getByText(/Set "Each month, move this %/)).toBeTruthy();
});

test('scorecard compares with SPY and switches account scope', async () => {
  const load = vi.spyOn(stockApi, 'fetchScorecard').mockResolvedValue({ scope: 'trading', trades: 12, skipped: 1, note: 'Scorecard note.',
    totals: { trades: 12, net: 400, spy: 900, edge: -500, win_rate: 58, capital: 20000, edge_pct_of_capital: -2.5 },
    groups: [{ strategy: 'Long options', trades: 5, net: -300, spy: 100, edge: -400, win_rate: 20, avg_days: 9 }],
    months: [{ month: '2026-09', trades: 12, net: 400, spy: 900, edge: -500, win_rate: 58 }] });
  render(<Scorecard />);
  expect(await screen.findByText(/would have made/)).toBeTruthy();
  expect(screen.getByText(/too few to tell skill from luck/)).toBeTruthy();
  expect(within(screen.getByRole('table', { name: 'By strategy' })).getByText('-$400')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'All accounts' }));
  await waitFor(() => expect(load).toHaveBeenLastCalledWith('all'));
});

test('a buy that succeeds is not reported as failed when only the stop fails to save', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 }, token: 'fixture' });
  const summary = vi.spyOn(stockApi, 'fetchPortfolioSummary').mockResolvedValue({ holdings: [], total_invested: 0, total_current: 0, total_pnl: 0, total_pnl_pct: 0 });
  vi.spyOn(stockApi, 'checkTradeRisk').mockResolvedValue({ risk: 100, basis: 'down to a $190 stop', warnings: [], notes: [] });
  const buy = vi.spyOn(stockApi, 'buyStock').mockResolvedValue({ id: 1 });
  vi.spyOn(stockApi, 'setRiskStop').mockRejectedValue(new Error('Server error'));
  render(<Portfolio />);
  fireEvent.change(await screen.findByLabelText('Ticker'), { target: { value: 'AAPL' } });
  fireEvent.change(screen.getByLabelText('Shares'), { target: { value: '10' } });
  fireEvent.change(screen.getByLabelText('Price ($)'), { target: { value: '200' } });
  fireEvent.change(screen.getByLabelText('Stop ($, optional)'), { target: { value: '190' } });
  const calls = summary.mock.calls.length;
  fireEvent.click(screen.getByRole('button', { name: 'Buy' }));
  expect(await screen.findByText(/Bought 10 shares of AAPL, but the stop wasn't saved \(Server error\)/)).toBeTruthy();
  expect(buy).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText('Ticker').value).toBe('');
  await waitFor(() => expect(summary.mock.calls.length).toBeGreaterThan(calls));
});
