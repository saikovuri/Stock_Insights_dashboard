// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import * as auth from './AuthContext';
import IncomeIdeas from './components/IncomeIdeas';
import Structures from './components/Structures';
import PaperTrades from './components/PaperTrades';
import { PastResults, payoffPoints, resetTrackRecordCache } from './components/IdeaTrust';
import { industryExposure } from './components/OptionsDesk';

const track = { groups: [
  { kind: 'pcs', label: 'Balanced', ideas: 23, win_rate: 78, avg_return_on_risk_pct: -2.1, worst_pct: -100 },
  { kind: 'spread', label: 'medium · bull', ideas: 4, win_rate: 50, avg_return_on_risk_pct: 10, worst_pct: -100 },
] };

beforeEach(() => {
  resetTrackRecordCache();
  vi.spyOn(stockApi, 'fetchTrackRecord').mockResolvedValue(track);
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

test('payoff points follow the structure at expiry', () => {
  const legs = [{ position: 'short', option_type: 'put', strike: 100, ratio: 1 }, { position: 'long', option_type: 'put', strike: 95, ratio: 1 }];
  const points = payoffPoints(legs, -1.4, 2, 101);
  const at = price => points.find(p => p.price === price).pnl;
  expect(at(100)).toBe(280);
  expect(at(95)).toBe(-720);
  expect(Math.min(...points.map(p => p.pnl))).toBe(-720);
  const covered = payoffPoints([{ position: 'long', option_type: 'stock', ratio: 1 }, { position: 'short', option_type: 'call', strike: 110, ratio: 1 }], 100 - 2, 1, 100);
  expect(covered.find(p => p.price === 110).pnl).toBe(1200);
});

test('past results show settled stats, or say when there are too few to judge', async () => {
  const { rerender } = render(<PastResults kind="pcs" label="Balanced" />);
  expect(await screen.findByText(/23 settled/)).toBeTruthy();
  expect(screen.getByText('78% won')).toBeTruthy();
  rerender(<PastResults kind="spread" label="medium · bull" />);
  expect(await screen.findByText(/Only 4 ideas like this have settled so far/)).toBeTruthy();
  rerender(<PastResults kind="ic" label="Balanced" />);
  expect(await screen.findByText(/No settled ideas like this yet/)).toBeTruthy();
  expect(stockApi.fetchTrackRecord).toHaveBeenCalledTimes(1);
});

test('income spread cards show the expected fill, past results, hidden count and record a paper trade', async () => {
  vi.spyOn(auth, 'useOptionalAuth').mockReturnValue({ user: { id: 1 } });
  const spread = { label: 'Balanced', short_strike: 50, long_strike: 48, width: 2, credit: 0.4, mid_credit: 0.45, natural_credit: 0.35,
    premium: 40, max_loss: 160, return_on_risk_pct: 25, breakeven: 49.6, breakeven_pct: 6, prob_profit_pct: 80, prob_max_profit_pct: 75,
    delta: 0.16, open_interest: 900, liquidity: 'good', safety: 'safer', checks: [] };
  vi.spyOn(stockApi, 'fetchIncomeIdeas').mockResolvedValue({ spot: 52.8, expiry: '2026-11-20', dte: 32, earnings_date: '2026-12-01',
    expirations: [{ date: '2026-11-20', dte: 32 }], put_credit_spreads: [spread], skipped_low_credit: { put_credit_spreads: 2 },
    pricing: 'Premiums use a realistic fill.' });
  const paper = vi.spyOn(stockApi, 'openPaperTrade').mockResolvedValue({ style: 'credit', entry: -0.41 });
  render(<IncomeIdeas ticker="PYPL" />);
  await screen.findByText(/Stock \$52.8/);
  fireEvent.click(screen.getByRole('button', { name: 'Put Credit Spreads' }));
  expect(screen.getByText(/Expected fill \$0.4 net credit \(midpoint \$0.45/)).toBeTruthy();
  expect(screen.getByText('2 hidden for this expiry.')).toBeTruthy();
  expect(await screen.findByText(/23 settled/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: /Paper trade/ }));
  await waitFor(() => expect(paper).toHaveBeenCalledWith({ ticker: 'PYPL', contracts: 1, source: 'income', label: 'Put Credit Spreads · Balanced',
    legs: [{ position: 'short', option_type: 'put', strike: 50, expiry: '2026-11-20', ratio: 1 },
      { position: 'long', option_type: 'put', strike: 48, expiry: '2026-11-20', ratio: 1 }] }));
  expect(await screen.findByText(/Paper trade recorded: credit of \$0.41/)).toBeTruthy();
});

test('directional cards hide paper trading for guests and open the payoff chart on demand', async () => {
  vi.spyOn(auth, 'useOptionalAuth').mockReturnValue(null);
  vi.spyOn(stockApi, 'fetchStructures').mockResolvedValue({ ticker: 'NVDA', spot: 217.85, expiry: '2027-01-15', dte: 88, risk: 'medium',
    direction: 'bull', timeframe: '2–6 months out', ideas: [{ kind: 'spread', title: 'Bull call debit spread', best: true, qty: 1, unit: 'spread',
      cost: 435, max_loss: 435, max_profit: 565, breakeven: 224.35, move_needed_pct: 3.1, liquidity: 'good', open_interest: 40000, notes: 'n',
      legs: [{ action: 'BUY', type: 'call', strike: 220, mid: 15.07 }, { action: 'SELL', type: 'call', strike: 230, mid: 10.73 }] }] });
  render(<Structures ticker="NVDA" />);
  fireEvent.click(screen.getByRole('button', { name: 'Find trades' }));
  expect(await screen.findByText(/Only 4 ideas like this have settled/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Paper trade/ })).toBeNull();
  const toggle = screen.getByText('📈 Profit/loss at expiry').closest('details');
  expect(toggle.querySelector('.payoff-chart')).toBeNull();
  toggle.open = true;
  fireEvent(toggle, new Event('toggle'));
  await waitFor(() => expect(toggle.querySelector('.payoff-chart')).not.toBeNull());
});

test('paper trades list results and close or delete a trade', async () => {
  const open = { id: 7, ticker: 'SPY', structure: 'Bull put', strikes: '$95/$100', contracts: 2, entry: -1.4, style: 'credit', opened_at: '2026-10-19T15:00:00Z',
    expiry: '2099-01-15', status: 'open', mark: -1.0, unrealized: 80, label: 'Put Credit Spreads · Balanced' };
  const done = { ...open, id: 8, status: 'expired', settle_price: 98.5, pnl: -45, exit_value: -1.5, mark: undefined, unrealized: undefined };
  vi.spyOn(stockApi, 'fetchPaperTrades').mockResolvedValue({ trades: [open, done], note: 'Practice positions.',
    stats: { open: 1, closed: 1, wins: 0, win_rate: 0, realized: -45, unrealized: 80 } });
  const close = vi.spyOn(stockApi, 'closePaperTrade').mockResolvedValue({ pnl: 60 });
  const remove = vi.spyOn(stockApi, 'deletePaperTrade').mockResolvedValue({ ok: true });
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  render(<PaperTrades />);
  const table = await screen.findByRole('table', { name: 'Paper trades' });
  expect(within(table).getByText('Settled at $98.5')).toBeTruthy();
  expect(within(table).getByText('$80.00')).toBeTruthy();
  fireEvent.click(within(table).getByRole('button', { name: 'Close SPY paper trade' }));
  await waitFor(() => expect(close).toHaveBeenCalledWith(7));
  expect(await screen.findByText(/Closed SPY Bull put at a realistic fill: \$60.00/)).toBeTruthy();
  fireEvent.click(within(await screen.findByRole('table', { name: 'Paper trades' })).getAllByRole('button', { name: 'Delete SPY paper trade' })[1]);
  await waitFor(() => expect(remove).toHaveBeenCalledWith(8));
});

test('industry exposure counts a spread once at its collateral', () => {
  const profiles = { SPY: { industry: 'Funds' } };
  const options = [{ id: 1, ticker: 'SPY', type: 'put', position: 'short', strike: 100, contracts: 2 },
    { id: 2, ticker: 'SPY', type: 'put', position: 'long', strike: 95, contracts: 2 },
    { id: 3, ticker: 'SPY', type: 'put', position: 'short', strike: 90, contracts: 1 }];
  const [row] = industryExposure(options, [], profiles, [{ ticker: 'SPY', collateral: 1000, leg_ids: [1, 2] }]);
  expect(row.puts).toBe(1000 + 9000);
});
