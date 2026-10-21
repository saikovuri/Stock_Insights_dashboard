// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import * as stockApi from './api/stockApi';
import * as auth from './AuthContext';
import Journal from './components/Journal';
import { ModeToggle } from './components/ModeToggle';
import { hiddenInSimple, getUiMode, setUiMode } from './uiMode';

// setUiMode also resets the in-memory fallback, which outlives localStorage.clear()
beforeEach(() => { setUiMode('simple'); localStorage.clear(); sessionStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

test('the header toggle defaults to Simple and remembers Advanced on this device', () => {
  render(<ModeToggle />);
  const group = screen.getByRole('group', { name: 'Interface mode' });
  expect(within(group).getByRole('button', { name: 'Simple' }).getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(within(group).getByRole('button', { name: 'Advanced' }));
  expect(within(group).getByRole('button', { name: 'Advanced' }).getAttribute('aria-pressed')).toBe('true');
  expect(localStorage.getItem('ui_mode')).toBe('advanced');
  expect(getUiMode()).toBe('advanced');
});

test('command palette destinations hidden in Simple are recognised', () => {
  expect(hiddenInSimple({ tab: 'ideas', ideasTab: 'flow' })).toBe(true);
  expect(hiddenInSimple({ tab: 'ideas', ideasTab: 'wheel', anchor: 'wheel-manager' })).toBe(false);
  expect(hiddenInSimple({ tab: 'portfolio', section: 'risk', anchor: 'expiry-ladder' })).toBe(true);
  expect(hiddenInSimple({ tab: 'portfolio', section: 'risk', anchor: 'trading-rules' })).toBe(false);
  expect(hiddenInSimple({ tab: 'journal' })).toBe(false);
});

test('Simple hides wheel cycles in the Journal, says so, and one click shows everything', async () => {
  vi.spyOn(auth, 'useAuth').mockReturnValue({ user: { id: 1 } });
  vi.spyOn(stockApi, 'fetchJournal').mockResolvedValue({ trades: [], stats: null });
  vi.spyOn(stockApi, 'fetchClosedTrades').mockResolvedValue({ trades: [] });
  vi.spyOn(stockApi, 'fetchClosedOptions').mockResolvedValue({ trades: [] });
  render(<Journal />);
  const views = screen.getByRole('navigation', { name: 'Journal views' });
  expect(within(views).queryByRole('button', { name: 'Wheel cycles' })).toBeNull();
  expect(within(views).getByRole('button', { name: 'vs S&P 500' })).toBeTruthy();
  expect(within(views).getByRole('button', { name: 'Manual journal' })).toBeTruthy();
  expect(screen.getByText(/Simple mode hides 1 more: Wheel cycles/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Show advanced' }));
  expect(within(views).getByRole('button', { name: 'Wheel cycles' })).toBeTruthy();
  expect(screen.queryByText(/Simple mode hides/)).toBeNull();
});

test('Advanced still works for this page when the browser cannot save the choice', () => {
  const save = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('QuotaExceededError'); });
  setUiMode('advanced');
  expect(getUiMode()).toBe('advanced');
  save.mockRestore();
  setUiMode('simple');
  expect(getUiMode()).toBe('simple');
});
