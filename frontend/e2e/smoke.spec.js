import { test, expect } from '@playwright/test';

const errors = new WeakMap();
const stats = { trades: 40, avg_net_pct: 0.1, total_net_pct: 4, profit_factor: 1.2, max_drawdown_pct: -2,
  win_rate: 55, per_session: 1, avg_win_pct: 0.2, avg_loss_pct: -0.1, long_avg_net_pct: 0.1, short_avg_net_pct: 0.1 };
const windowResult = { from: '2026-02-01', to: '2026-03-01', stats, double_cost_stats: { ...stats, avg_net_pct: 0.05 } };
const closed = { total_realized_pnl: 100, trades: [{ id: 1, ticker: 'MSFT', shares: 10, buy_price: 100, sell_price: 110,
  pnl: 100, pnl_pct: 10, closed_at: '2026-01-20' }] };
const fixtures = {
  '/api/auth/me': { id: 1, user_id: 1, username: 'fixture', display_name: 'Test User' },
  '/api/portfolio/summary': { total_invested: 1000, total_current: null, total_pnl: null, total_pnl_pct: null, incomplete: true,
    holdings: [{ id: 1, ticker: 'AAPL', shares: 10, buy_price: 100, current_price: null, pnl: null, pnl_pct: null }] },
  '/api/portfolio/options/summary': { options: [] },
  '/api/portfolio/closed': closed,
  '/api/portfolio/options/closed': { trades: [], total_realized_pnl: 0 },
  '/api/accounting/report': { fees: 0, external_cash_flow: 0, dividends: 0, twr: { pct: null, reason: 'Opening and ending account valuations are required' },
    manual_entries: [], tax_lots: [], cycles: [], has_legacy_snapshots: true,
    notes: ['US informational lot report, not a filing-ready tax return.'] },
  '/api/accounting/events': { events: [] },
  '/api/backtest/strategies': { timeframes: ['5m'], strategies: { ema_cross: { label: 'EMA cross', params: { fast: 9, slow: 21 }, help: '' } } },
  '/api/backtest': { ticker: 'SPY', timeframe: '5m', label: 'EMA cross', from: '2026-01-01', to: '2026-03-01', sessions: 40, stats,
    equity: [{ t: '2026-01-01', equity: 0 }, { t: '2026-03-01', equity: 4 }], recent_trades: [], notes: [],
    walk_forward: { windows: [{ ...windowResult, params: { fast: 7, slow: 21 } }], note: 'Training-only parameter selection fixture.' },
    baseline: { label: 'Buy and hold', total_pct: 0 }, validation: { train: { ...windowResult, from: '2026-01-01', to: '2026-01-31' },
      holdout: windowResult, windows: [windowResult, windowResult, windowResult], note: 'Fixed-parameter holdout fixture.' } },
};

test.beforeEach(async ({ page }) => {
  errors.set(page, []);
  page.on('pageerror', error => errors.get(page).push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && /Content Security Policy/i.test(message.text())) errors.get(page).push(message.text());
  });
  await page.addInitScript(() => {
    localStorage.setItem('token', 'synthetic-test-token');
    localStorage.setItem('stockpilot_tour_v1', 'done');
  });
  await page.route('**/api/**', async route => {
    const data = fixtures[new URL(route.request().url()).pathname];
    await route.fulfill({ status: data ? 200 : 503, json: data || { detail: 'Unavailable in isolated test' } });
  });
});

test.afterEach(async ({ page }) => {
  expect(errors.get(page)).toEqual([]);
});

test('ideas show in play and the macro calendar without removed feeds', async ({ page }) => {
  await page.route('**/api/ideas/in-play*', route => route.fulfill({ json: {
    market_state: 'closed', screened: 100, as_of: '2026-10-05T12:00:00Z', rows: [],
  } }));
  await page.route('**/api/market/calendar?*', route => route.fulfill({ json: { events: [] } }));
  await page.goto('/#ideas');
  const tabs = page.getByRole('navigation', { name: 'Ideas views' });
  await expect(tabs.getByRole('button', { name: /Superinvestors/ })).toHaveCount(0);
  await tabs.getByRole('button', { name: /In play/ }).click();
  await expect(page.getByRole('heading', { name: /Stocks in play/ })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Reddit attention' })).toHaveCount(0);
  await tabs.getByRole('button', { name: /Macro calendar/ }).click();
  await expect(page.getByRole('region', { name: 'Prediction-market context' })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test('weekly covered calls show projected ownership cost', async ({ page }, testInfo) => {
  let cadence;
  await page.route('**/api/stock/NVDA/assigned-calls?*', route => {
    cadence = new URL(route.request().url()).searchParams.get('cadence');
    const expiry = '2026-10-09';
    const dte = 4;
    const ideas = [
        { label: 'Max premium', strike: 250, mid: 4.05, total_premium: 405, premium_adjusted_cost: 222.29, delta: 0.35 },
        { label: 'Balanced', strike: 255, mid: 2.72, total_premium: 272, premium_adjusted_cost: 223.62, delta: 0.25 },
        { label: 'Keep the shares', strike: 260, mid: 1.76, total_premium: 176, premium_adjusted_cost: 224.58, delta: 0.15 },
      ].map(idea => ({ ...idea, expiry, dte, bid: idea.mid - 0.02, ask: idea.mid + 0.02, spread_pct: 2,
        open_interest: 500, liquidity: 'good', return_pct: 1.79, annualized_pct: 163.2,
        otm_pct: 4.6, if_called_pct: 12.24, prob_called_pct: 22 }));
    const expirations = [{ date: expiry, dte, ideas }];
    if (cadence === 'all') expirations.push({ date: '2026-11-06', dte: 32,
      ideas: [{ ...ideas[0], expiry: '2026-11-06', dte: 32, premium_adjusted_cost: 220.29 }] });
    return route.fulfill({ json: { ticker: 'NVDA', spot: 238.9, cost_basis: 226.34, shares: 100, contracts: 1,
      cadence, expiry, dte, unrealized_pct: 5.5, note: 'Synthetic test quotes.', ideas, expirations,
      checked_expirations: expirations.length + 1, skipped_expirations: 1, unavailable_expirations: [] } });
  });
  await page.goto('/#ideas');
  await page.getByRole('button', { name: /Wheel/, exact: false }).click();
  const manager = page.locator('#wheel-manager');
  await manager.getByRole('button', { name: /Assigned/ }).click();
  await manager.getByLabel('Ticker', { exact: true }).fill('NVDA');
  await manager.getByLabel('Cost per share ($)', { exact: true }).fill('226.34');
  await manager.getByRole('button', { name: 'Suggest covered calls' }).click();
  await expect(manager.getByText('$222.29', { exact: true })).toBeVisible();
  expect(cadence).toBe('all');
  await expect(manager.getByLabel('Eligible expiry').locator('option')).toHaveCount(2);
  await manager.getByLabel('Eligible expiry').selectOption('2026-11-06');
  await expect(manager.getByText('$220.29', { exact: true })).toBeVisible();
  await expect(manager.getByText('$222.29', { exact: true })).toHaveCount(0);
  await manager.screenshot({ path: testInfo.outputPath('all-dates-covered-calls.png') });
  await manager.getByLabel('Expiry horizon').selectOption('weekly');
  await expect(manager.getByText('$222.29', { exact: true })).toHaveCount(0);
  await manager.getByRole('button', { name: 'Suggest covered calls' }).click();
  await expect(manager.getByText('$222.29', { exact: true })).toBeVisible();
  expect(cadence).toBe('weekly');
  await expect(manager.getByLabel('Cost per share ($)', { exact: true })).toHaveValue('226.34');
  await expect(manager.getByText(/does not change recorded holdings or tax basis/)).toBeVisible();
  expect(await manager.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  expect(await manager.locator('.structure-stats > div').evaluateAll(rows => rows.every(row => {
    const label = row.querySelector('span').getBoundingClientRect();
    const value = row.querySelector('strong').getBoundingClientRect();
    return label.right <= value.left + 1;
  }))).toBe(true);
  await manager.screenshot({ path: testInfo.outputPath('weekly-covered-calls.png') });
  await page.route('**/api/stock/NVDA/assigned-calls?*', route => route.fulfill({ status: 404,
    json: { detail: 'No listed expirations within 1-7 days' } }));
  await manager.getByRole('button', { name: 'Suggest covered calls' }).click();
  await expect(manager.getByRole('alert')).toHaveText('No listed expirations within 1-7 days');
  await expect(manager.getByText('$222.29', { exact: true })).toHaveCount(0);
});

test('put tested uses listed expiries instead of fabricated dates', async ({ page }, testInfo) => {
  let submittedExpiry;
  await page.route('**/api/stock/NVDA/option-expirations', route => route.fulfill({ json: {
    expirations: [{ date: '2026-10-09', dte: 4 }, { date: '2026-10-16', dte: 11 }],
  } }));
  await page.route('**/api/stock/NVDA/roll?*', route => {
    submittedExpiry = new URL(route.request().url()).searchParams.get('expiry');
    return route.fulfill({ json: { rules: ['Synthetic roll result.'], rolls: [], alternatives: [] } });
  });
  await page.goto('/#ideas');
  await page.getByRole('button', { name: /Wheel/ }).click();
  const manager = page.locator('#wheel-manager');
  await manager.getByLabel('Ticker', { exact: true }).fill('NVDA');
  const expiry = manager.getByRole('combobox', { name: 'Expiry', exact: true });
  await expect(expiry.locator('option')).toHaveCount(3);
  await expect(expiry.getByRole('option', { name: /Oct 7/ })).toHaveCount(0);
  await manager.getByLabel('Short put strike').fill('240');
  await manager.getByLabel('Credit received / share').fill('2');
  await expect(manager.getByRole('button', { name: 'Find rolls' })).toBeDisabled();
  await expiry.selectOption('2026-10-09');
  await manager.getByRole('button', { name: 'Find rolls' }).click();
  await expect(manager.getByText('Synthetic roll result.')).toBeVisible();
  expect(submittedExpiry).toBe('2026-10-09');
  await expect(manager.getByRole('alert')).toHaveCount(0);
  expect(await manager.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await manager.screenshot({ path: testInfo.outputPath('put-tested-expiries.png') });
});

test('holdings stay usable when quotes are missing', async ({ page }, testInfo) => {
  await page.goto('/#portfolio');
  await expect(page.getByText('AAPL', { exact: true })).toBeVisible();
  await expect(page.getByText('Unavailable', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Holdings', exact: true })).toBeVisible();
  const overflow = await page.locator('.lot-group-header').evaluate(element => {
    const parent = element.getBoundingClientRect();
    return [...element.children].some(child => child.getBoundingClientRect().right > parent.right + 1);
  });
  expect(overflow).toBe(false);
  await page.screenshot({ path: testInfo.outputPath('holdings.png'), fullPage: true });
});

test('option close accepts a typed buy-back price', async ({ page }, testInfo) => {
  let submitted = null;
  await page.route('**/api/portfolio/options/summary', route => route.fulfill({ json: {
    total_cost: 120, total_value: null, total_pnl: null,
    options: submitted ? [] : [{ id: 42, ticker: 'WDC', type: 'put', position: 'short', strike: 65,
      expiry: '2027-01-15', dte: 100, contracts: 1, premium: 1.2, market_price: 0.6, current_price: null, pnl: null }],
  } }));
  await page.route('**/api/portfolio/options/close', route => {
    submitted = route.request().postDataJSON();
    return route.fulfill({ json: { pnl: 85 } });
  });
  await page.goto('/#portfolio');
  await page.getByRole('button', { name: /Options/ }).click();
  await page.getByTitle('Close this option lot', { exact: true }).click();
  const price = page.getByLabel('Buy-back price ($/share)', { exact: true });
  const submit = page.getByRole('button', { name: 'Buy to Close', exact: true });
  await expect(price).toBeFocused();
  await expect(price).toHaveValue('');
  await expect(submit).toBeDisabled();
  await price.pressSequentially('0.35');
  await expect(price).toHaveValue('0.35');
  await expect(submit).toBeEnabled();
  await price.fill('');
  await expect(submit).toBeDisabled();
  await price.pressSequentially('0.35');
  await page.locator('.portfolio-form.labeled-form').screenshot({ path: testInfo.outputPath('buy-back-price.png') });
  await submit.click();
  await expect(page.getByText('BTC 1 PUT on WDC', { exact: true })).toBeVisible();
  expect(submitted).toMatchObject({ ticker: 'WDC', option_type: 'put', position: 'short', option_id: 42, premium: 0.35, contracts: 1 });
});

test('account transfer downloads, previews and confirms without duplicate retries', async ({ page }, testInfo) => {
  const bundle = { payload: '{"source_user_id":2,"shares":1.0}', signature: 'synthetic-fixture', exported_at: '2026-10-06T12:00:00Z' };
  const submitted = [];
  let previews = 0;
  let alreadyImported = false;
  await page.route('**/api/account-transfer/export', route => route.fulfill({ json: bundle }));
  await page.route('**/api/account-transfer/preview', route => {
    previews += 1;
    expect(route.request().postDataJSON()).toEqual(bundle);
    return route.fulfill({ json: { source_name: 'Source fixture', source_user_id: 2,
      counts: { holdings: 2, options: 1, closed_options: 3, journal: 4, watchlist: 2, transactions: 5 },
      destination_counts: { holdings: 1, closed_trades: 1 }, ledger_events: 15, already_imported: alreadyImported } });
  });
  await page.route('**/api/account-transfer/import', route => {
    submitted.push(route.request().postDataJSON());
    alreadyImported = true;
    if (submitted.length === 1) return route.fulfill({ status: 503, json: { detail: 'Temporary response failure; retry unchanged' } });
    return route.fulfill({ json: { already_imported: true, counts: {} } });
  });
  await page.goto('/#portfolio');
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export data to another login' }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^stockpilot-account-transfer-.*\.json$/);
  expect(await download.failure()).toBeNull();
  await expect(page.getByText(/Export downloaded/)).toBeVisible();
  await page.getByRole('button', { name: 'Import data from another login' }).click();
  const dialog = page.getByRole('dialog', { name: 'Import data from another login' });
  await dialog.getByLabel('Transfer file (.json)').setInputFiles({ name: 'wrong.json', mimeType: 'application/json', buffer: Buffer.from('not json') });
  await expect(dialog.getByRole('alert')).toHaveText('Choose a valid StockPilot transfer JSON file.');
  expect(previews).toBe(0);
  await dialog.getByLabel('Transfer file (.json)').setInputFiles({ name: 'transfer.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(bundle)) });
  await expect(dialog.getByText('Source fixture', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Confirm import' })).toBeDisabled();
  expect(submitted).toHaveLength(0);
  await dialog.getByRole('checkbox', { name: /I confirm adding these records to Test User/ }).check();
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await dialog.screenshot({ path: testInfo.outputPath('account-transfer-preview.png') });
  await dialog.getByRole('button', { name: 'Confirm import' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Temporary response failure; retry unchanged');
  await dialog.getByRole('button', { name: 'Confirm import' }).click();
  await expect(dialog).toHaveCount(0);
  expect(submitted).toEqual([{ package: bundle, confirm: true }, { package: bundle, confirm: true }]);
  await expect(page.getByText('This export was already imported. No duplicate records were added.')).toBeVisible();
  await page.getByRole('button', { name: 'Import data from another login' }).click();
  await dialog.getByLabel('Transfer file (.json)').setInputFiles({ name: 'transfer.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(bundle)) });
  await expect(dialog.getByText('This export was already imported. No duplicate records will be added.')).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Confirm import' })).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test('journal review and explicit wheel cycles work on desktop and mobile', async ({ page }, testInfo) => {
  const trade = { id: 12, ledger_event_id: 42, ticker: 'AAPL', position: 'short', option_type: 'put', strike: 100,
    contracts: 2, open_premium: 2, close_premium: .5, pnl: 300, net_pnl: 296, fees: 4,
    opened_at: '2025-09-01', closed_at: '2025-09-10', expiry: '2025-09-19' };
  const submissions = [];
  let linked = false;
  await page.route('**/api/portfolio/closed', route => route.fulfill({ json: { trades: [] } }));
  await page.route('**/api/portfolio/options/closed', route => route.fulfill({ json: { trades: [trade] } }));
  await page.route('**/api/accounting/report', route => route.fulfill({ json: {
    tax_lots: [{ opening_event_id: 42, source_id: 12, source: 'closed_options', ticker: 'AAPL', position: 'short', option_type: 'put', quantity: 2, closed_at: '2025-09-10' }],
    manual_entries: linked ? [{ kind: 'link', event_id: 42, quantity: '1' }] : [],
    cycles: [{ name: 'AAPL wheel', put_pnl: linked ? 150 : 0, call_pnl: 300, stock_pnl: -1000,
      fees: linked ? 13 : 11, realized_pnl: linked ? -563 : -711, open_links: 0, unresolved_links: 0,
      links: [{ link_id: 61, source: 'closed_options', ticker: 'AAPL', quantity: '2', status: 'realized' },
        { link_id: 62, source: 'closed_trades', ticker: 'AAPL', quantity: '100', status: 'realized' },
        ...(linked ? [{ link_id: 63, source: 'closed_options', ticker: 'AAPL', quantity: '1', status: 'realized' }] : [])] }],
  } }));
  await page.route('**/api/accounting/entries', route => {
    const payload = route.request().postDataJSON();
    submissions.push(payload);
    if (submissions.length === 1) return route.fulfill({ status: 503, json: { detail: 'Temporary review failure' } });
    if (payload.kind === 'review') trade.review = { ...payload, review_id: 51, review_note: payload.note, review_recorded_at: '2026-10-06T12:00:00Z' };
    if (payload.kind === 'link') linked = true;
    if (payload.kind === 'reverse') linked = false;
    return route.fulfill({ json: { id: 63 } });
  });
  await page.goto('/#journal');
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('75.0%', { exact: true })).toBeAttached();
  await page.getByRole('button', { name: 'Review AAPL trade 12' }).click();
  const dialog = page.getByRole('dialog', { name: 'Review AAPL closed trade' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('combobox', { name: 'Exit reason' }).selectOption('profit_target');
  await dialog.getByLabel('Target capture (%)').fill('50');
  await dialog.getByLabel('Review notes').fill('Synthetic review fixture.');
  await dialog.getByRole('button', { name: 'Save review' }).click();
  await expect(dialog.getByRole('alert')).toHaveText('Temporary review failure');
  expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await dialog.screenshot({ path: testInfo.outputPath('journal-trade-review.png') });
  await dialog.getByRole('button', { name: 'Save review' }).click();
  await expect(dialog).toHaveCount(0);
  expect(submissions[1]).toEqual(submissions[0]);
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('+25.0 pp', { exact: true })).toBeAttached();
  await expect(page.getByRole('cell', { name: 'Profit target' })).toBeAttached();
  await page.getByRole('button', { name: 'Review AAPL trade 12' }).click();
  await expect(dialog.getByLabel('Target capture (%)')).toHaveValue('50');
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  const table = page.locator('.journal-workspace .table-scroll').filter({ has: page.getByRole('table', { name: 'Recorded trades' }) });
  expect(await table.evaluate(element => element.scrollWidth >= element.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('journal-capture-history.png'), fullPage: true });
  const calendar = page.locator('.pnl-calendar');
  await expect(calendar.getByRole('group', { name: /Realized P&L calendar/ })).toBeVisible();
  expect(await calendar.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await calendar.screenshot({ path: testInfo.outputPath('journal-pnl-calendar.png') });
  await page.getByRole('button', { name: 'Wheel cycles', exact: true }).click();
  await page.getByRole('combobox', { name: 'Closed trade' }).selectOption('42');
  await page.getByLabel('Cycle name').fill('AAPL wheel');
  await page.getByLabel('Contracts to link').fill('1');
  await page.getByRole('button', { name: 'Link to cycle' }).click();
  await expect(page.getByText('-$563.00', { exact: true })).toBeVisible();
  await expect(page.getByText('-$1,000.00', { exact: true })).toHaveClass('negative');
  const cycles = page.locator('.wheel-cycles');
  expect(await cycles.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await cycles.screenshot({ path: testInfo.outputPath('journal-wheel-cycle.png') });
  page.once('dialog', prompt => prompt.accept());
  await page.getByRole('button', { name: 'Remove allocation 63' }).click();
  await expect(page.getByText('-$711.00', { exact: true })).toBeVisible();
  expect(submissions.at(-1)).toMatchObject({ kind: 'reverse', event_id: 63 });
});

test('journal keeps planning in one on-demand dialog across review tabs', async ({ page }, testInfo) => {
  await page.goto('/#journal');
  await expect(page.getByRole('button', { name: 'Trade history', exact: true })).toBeVisible();
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('MSFT', { exact: true })).toBeVisible();
  const planner = page.getByRole('dialog', { name: 'Plan a trade', exact: true });
  const launch = page.getByRole('button', { name: 'Plan a trade', exact: true });
  for (const tab of ['Trade history', 'Manual journal', 'Options review', 'Wheel cycles']) {
    await page.getByRole('button', { name: tab, exact: true }).click();
    await expect(launch).toHaveCount(1);
    await expect(planner).not.toBeVisible();
    await expect(page.getByRole('heading', { name: /Pre-Trade Checklist/ })).not.toBeVisible();
    await expect(page.locator('details.plan-trade')).toHaveCount(0);
    await launch.click();
    await expect(planner).toBeVisible();
    if (tab === 'Trade history') await planner.getByLabel('Ticker', { exact: true }).fill('AAPL');
    await expect(planner.getByLabel('Ticker', { exact: true })).toHaveValue('AAPL');
    await page.keyboard.press('Escape');
    await expect(planner).not.toBeVisible();
    await expect(launch).toBeFocused();
  }
  await launch.click();
  expect(await planner.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  const bounds = await planner.boundingBox();
  expect(bounds.x).toBeGreaterThanOrEqual(0);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(page.viewportSize().width);
  await planner.screenshot({ path: testInfo.outputPath('journal-planning.png') });
  await planner.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(planner).not.toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('journal-review.png'), fullPage: true });
});

test('journal records historical options with fees and safe retry', async ({ page }, testInfo) => {
  let recorded = null;
  const submissions = [];
  await page.route('**/api/journal', route => route.fulfill({ json: { entries: [] } }));
  await page.route('**/api/portfolio/options/closed', route => {
    if (route.request().method() === 'POST') {
      const payload = route.request().postDataJSON();
      submissions.push(payload);
      recorded = { ...payload, id: 12, is_manual: true, strike: Number(payload.strike), open_premium: Number(payload.open_premium),
        close_premium: Number(payload.close_premium), pnl: 85, pnl_pct: 70.83, fees: 1.3, net_pnl: 83.7 };
      return route.fulfill({ status: submissions.length === 1 ? 503 : 200,
        json: submissions.length === 1 ? { detail: 'Temporary failure' } : recorded });
    }
    return route.fulfill({ json: { trades: recorded ? [recorded] : [], total_realized_pnl: recorded?.pnl ?? 0,
      total_fees: recorded?.fees ?? 0, total_net_pnl: recorded?.net_pnl ?? 0 } });
  });
  await page.route('**/api/portfolio/options/closed/12', route => {
    if (route.request().method() === 'PUT') {
      const payload = route.request().postDataJSON();
      recorded = { ...recorded, ...payload, strike: Number(payload.strike), open_premium: Number(payload.open_premium),
        close_premium: Number(payload.close_premium), fees: Number(payload.fees), pnl: 95, net_pnl: 92.5 };
      return route.fulfill({ json: recorded });
    }
    if (route.request().method() === 'DELETE') { recorded = null; return route.fulfill({ json: { ok: true } }); }
    return route.fulfill({ status: 405 });
  });
  await page.route('**/api/portfolio/options/review', route => route.fulfill({ json: {
    stats: { trades: 1, win_rate: 100, total_pnl: 83.7, avg_win: 83.7, avg_loss: null, profit_factor: null }, breakdowns: {},
  } }));
  await page.goto('/#journal');
  await page.getByRole('button', { name: 'Manual journal', exact: true }).click();
  await page.getByRole('button', { name: 'Log closed option', exact: true }).click();
  const form = page.getByRole('form', { name: 'Closed option entry' });
  for (const [label, value] of Object.entries({ 'Option ticker': 'WDC', 'Strike ($)': '65', Expiry: '2025-09-19',
    'Opened on': '2025-09-01', 'Closed on': '2025-09-10', 'Opening premium ($/share)': '1.20',
    'Closing premium ($/share)': '0.35', 'Total fees ($, both sides)': '1.30', 'Option notes': 'Closed early' })) {
    await form.getByLabel(label, { exact: true }).fill(value);
  }
  await expect(form.getByText('$85', { exact: true })).toBeVisible();
  await expect(form.getByText('$83.7', { exact: true })).toBeVisible();
  for (const label of ['Expiry', 'Opened on', 'Closed on']) {
    const input = form.getByLabel(label, { exact: true });
    await input.evaluate(element => {
      const open = element.showPicker;
      element.showPicker = function () { open.call(this); this.dataset.pickerOpened = 'true'; };
    });
    await form.getByRole('button', { name: `Open ${label.toLowerCase()} calendar`, exact: true }).click();
    await expect(input).toHaveAttribute('data-picker-opened', 'true');
    await page.keyboard.press('Escape');
  }
  await expect(form.getByLabel('Expiry', { exact: true })).toHaveCSS('color-scheme', 'dark');
  expect(await form.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await form.screenshot({ path: testInfo.outputPath('closed-option-form.png') });
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'light'));
  await expect(form.getByLabel('Expiry', { exact: true })).toHaveCSS('color-scheme', 'light');
  await form.screenshot({ path: testInfo.outputPath('closed-option-form-light.png') });
  await page.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark'));
  await form.getByRole('button', { name: 'Record closed option' }).click();
  await expect(page.getByRole('alert')).toHaveText('Temporary failure');
  await form.getByRole('button', { name: 'Record closed option' }).click();
  await expect(page.getByRole('status')).toHaveText('WDC closed option recorded.');
  expect(submissions).toHaveLength(2);
  expect(submissions[1]).toEqual(submissions[0]);
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('WDC', { exact: true })).toHaveCount(1);
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('$83.7', { exact: true })).toBeAttached();
  await page.getByRole('button', { name: 'Trade history', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('WDC', { exact: true })).toHaveCount(1);
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText(/→ Sep 10, 2025/)).toBeAttached();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('closed-option-history.png'), fullPage: true });
  await page.getByRole('button', { name: 'Options review', exact: true }).click();
  await expect(page.getByText('Net P&L (recorded fees)', { exact: true })).toBeVisible();
  await page.goto('/#portfolio');
  await page.getByRole('button', { name: /Options/, exact: false }).first().click();
  await page.getByRole('button', { name: /Closed/, exact: false }).first().click();
  await expect(page.getByText('Net Realized P/L', { exact: true })).toBeVisible();
  await expect(page.getByText('$83.70', { exact: true }).first()).toBeVisible();
  await page.goto('/#journal');
  await page.getByRole('button', { name: 'Manual journal', exact: true }).click();
  await page.getByRole('button', { name: 'Edit WDC option', exact: true }).click();
  await expect(form.getByLabel('Closed on', { exact: true })).toHaveValue('2025-09-10');
  await expect(form.getByLabel('Option notes', { exact: true })).toHaveValue('Closed early');
  await form.getByLabel('Closing premium ($/share)', { exact: true }).fill('0.25');
  await form.getByLabel('Total fees ($, both sides)', { exact: true }).fill('2.50');
  await form.getByLabel('Closed on', { exact: true }).fill('2025-09-11');
  await form.getByRole('button', { name: 'Save option changes', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('WDC closed option updated.');
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('WDC', { exact: true })).toHaveCount(1);
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('$92.5', { exact: true })).toBeAttached();
  await page.locator('.closed-option-journal').screenshot({ path: testInfo.outputPath('option-edit-actions.png') });
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Delete WDC option', exact: true }).click();
  expect(recorded).not.toBeNull();
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Delete WDC option', exact: true }).click();
  await expect(page.getByRole('status')).toHaveText('WDC closed option deleted.');
  await expect(page.getByText('No closed options recorded.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Trade history', exact: true }).click();
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('MSFT', { exact: true })).toBeVisible();
  await expect(page.getByRole('table', { name: 'Recorded trades' }).getByText('WDC', { exact: true })).toHaveCount(0);
});

test('guest journal can open the planner without signing in', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('token'));
  await page.goto('/#journal');
  const launch = page.getByRole('button', { name: 'Plan a trade', exact: true });
  await expect(launch).toHaveCount(1);
  await launch.click();
  const planner = page.getByRole('dialog', { name: 'Plan a trade', exact: true });
  await expect(planner).toBeVisible();
  await planner.getByRole('button', { name: 'Review checklist' }).click();
  await expect(planner.getByText('Checklist incomplete.')).toBeVisible();
  await expect(planner.getByText('Cleared.')).toHaveCount(0);
});

test('income candidate stays visible with liquidity warnings and blocked sizing', async ({ page }, testInfo) => {
  await page.addInitScript(() => localStorage.setItem('trader_profile', 'long'));
  await page.route('**/api/stock/PYPL/metrics', route => route.fulfill({ json: { ticker: 'PYPL', name: 'PayPal', price: 52.8 } }));
  await page.route('**/api/stock/PYPL/history?*', route => route.fulfill({ json: [] }));
  await page.route('**/api/stock/PYPL/income*', route => route.fulfill({ json: {
    ticker: 'PYPL', spot: 52.8, expiry: '2026-10-16', dte: 12, earnings_date: '2026-10-27',
    expirations: [{ date: '2026-10-16', dte: 12, monthly: true }],
    cash_secured_puts: [{ label: 'Conservative', strike: 50, bid: .32, ask: .4, mid: .36, premium: 36,
      delta: .19, open_interest: 6708, spread_pct: 22.2, liquidity: 'thin', capital_required: 5000,
      safety: 'risky', checks: [], return_pct: .72, annualized_pct: 21.9, prob_assigned_pct: 20,
      effective_buy_price: 49.64, discount_pct: 6 }],
  } }));
  await page.goto('/#dashboard');
  await page.getByRole('combobox', { name: 'Ticker or company name' }).fill('PYPL');
  await page.getByRole('button', { name: 'Analyze', exact: true }).click();
  await page.getByRole('button', { name: /Analysis/, exact: false }).click();
  const income = page.locator('.income-ideas');
  await income.getByRole('button', { name: 'Cash-Secured Puts', exact: true }).click();
  await income.getByLabel('Cash available ($)').fill('5500');
  await expect(income.getByText(/SELL 1/)).toBeVisible();
  await expect(income.getByText('Wide spread: 22.2% exceeds the 20% guideline.')).toBeVisible();
  await expect(income.getByText('Cash sufficient; execution caution.')).toBeVisible();
  await expect(income.getByText(/Passes checks|No eligible trade/)).toHaveCount(0);
  expect(await income.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await income.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('income-warning.png'), fullPage: true });
  await income.getByLabel('Cash available ($)').fill('4500');
  await expect(income.getByText(/Cash needed: \$5,000/)).toBeVisible();
  await expect(income.getByText(/SELL \d/)).toHaveCount(0);
  await expect(income.getByText('Wide spread: 22.2% exceeds the 20% guideline.')).toBeVisible();
});

test('wheel short-dated checkbox selects matching scan and plan windows', async ({ page }, testInfo) => {
  const scanModes = [];
  const planModes = [];
  await page.route('**/api/ideas/wheel?*', route => {
    const shortDated = new URL(route.request().url()).searchParams.get('short_dated') === 'true';
    scanModes.push(shortDated);
    const candidate = { ticker: 'PYPL', name: 'PayPal', sector: 'Financials', price: 52.8, strike: 50,
      expiry: shortDated ? '2026-10-19' : '2026-11-09', dte: shortDated ? 14 : 35,
      bid: .5, ask: .54, open_interest: 6000, premium: 52, annualized_pct: 15, cushion_pct: 5,
      prob_assigned_pct: 15, breakeven: 49.48, capital: 5000, rs_rating: 75, liquidity: 'good',
      pct_from_high: -5, atr_pct: 2, earnings_date: '2026-11-20', earnings_before_expiry: false,
      flags: shortDated ? ['Short-dated'] : [] };
    return route.fulfill({ json: { status: 'ready', updated_at: '2026-10-05T15:00:00Z',
      quality_pool: 2, screened: 500, target_delta: .15, rows: [candidate,
        { ...candidate, ticker: 'TEST', earnings_date: '2026-10-10', earnings_before_expiry: true }] } });
  });
  await page.route('**/api/ideas/wheel/plan?*', route => {
    planModes.push(new URL(route.request().url()).searchParams.get('short_dated'));
    return route.fulfill({ json: { capital: 50000, cash_left: 50000, picks: [], skipped_expensive: [], blocked: [] } });
  });
  await page.goto('/#ideas');
  await page.getByRole('button', { name: /Wheel/, exact: false }).click();
  const toggle = page.getByRole('checkbox', { name: 'Short-dated: 7–20 days' });
  const earnings = page.getByRole('checkbox', { name: 'Skip trades that hold through earnings' });
  await expect(toggle).not.toBeChecked();
  await expect(page.getByText(/35d @/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'TEST', exact: true })).toHaveCount(0);
  await toggle.check();
  await expect(page.getByText(/14d @/)).toBeVisible();
  await expect(page.getByText(/35d @/)).toHaveCount(0);
  await expect(page.getByText(/higher near-expiry gamma risk/)).toBeVisible();
  await expect(earnings).toBeChecked();
  await earnings.uncheck();
  await expect(page.getByRole('button', { name: 'TEST', exact: true })).toBeVisible();
  await earnings.check();
  await page.getByRole('button', { name: 'Build plan', exact: true }).click();
  await expect.poll(() => planModes).toEqual(['true']);
  const controls = toggle.locator('..').locator('..');
  expect(await controls.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await toggle.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('wheel-short-dated.png'), fullPage: true });
  await toggle.uncheck();
  await expect(page.getByText(/35d @/)).toBeVisible();
  await expect(page.getByText(/higher near-expiry gamma risk/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Build plan', exact: true }).click();
  await expect.poll(() => planModes).toEqual(['true', 'false']);
  expect(scanModes).toEqual([false, true, false]);
});

test('strategy results and holdout render in the built app', async ({ page }, testInfo) => {
  await page.goto('/#ideas');
  await page.getByRole('button', { name: /Strategy tester/ }).click();
  await page.getByRole('button', { name: /Run backtest/ }).click();
  await expect(page.getByRole('heading', { name: 'Chronological validation' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Walk-forward parameter selection' })).toBeVisible();
  await expect(page.getByRole('cell', { name: /^Holdout/ })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('strategy.png'), fullPage: true });
});

test('expired access token refreshes during startup', async ({ page }) => {
  let refreshes = 0;
  await page.addInitScript(() => localStorage.setItem('refresh_token', 'synthetic-refresh-token'));
  await page.route('**/api/auth/me', route => route.fulfill({
    status: route.request().headers().authorization === 'Bearer renewed-test-token' ? 200 : 401,
    json: fixtures['/api/auth/me'],
  }));
  await page.route('**/api/auth/refresh', route => {
    refreshes++;
    return route.fulfill({ json: { token: 'renewed-test-token', refresh_token: 'renewed-refresh-token' } });
  });
  await page.goto('/#portfolio');
  await expect(page.getByText('AAPL', { exact: true })).toBeVisible();
  expect(refreshes).toBe(1);
});

test('account ledger records and reverses fees without page overflow', async ({ page }, testInfo) => {
  let entries = [];
  await page.route('**/api/accounting/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/entries')) {
      const body = route.request().postDataJSON();
      entries = body.kind === 'reverse' ? [] : [{ ...body, id: 1 }];
      return route.fulfill({ json: { id: 1 } });
    }
    if (path.endsWith('/report')) return route.fulfill({ json: { ...fixtures[path], fees: entries.length ? 3.25 : 0, manual_entries: entries } });
    return route.fulfill({ json: fixtures[path] });
  });
  await page.goto('/#portfolio');
  await page.getByRole('button', { name: 'Income & Performance', exact: true }).click();
  await page.getByRole('button', { name: 'Account ledger', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Account ledger', exact: true })).toBeVisible();
  await page.getByLabel('Occurred at', { exact: true }).fill('2026-01-01T12:00');
  await page.getByLabel('Amount ($)', { exact: true }).fill('3.25');
  await page.getByRole('button', { name: 'Record entry', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'fee', exact: true })).toBeVisible();
  await expect(page.getByLabel('Amount ($)', { exact: true })).toHaveValue('');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('accounting.png'), fullPage: true });
  await page.getByRole('button', { name: 'Reverse #1', exact: true }).click();
  await expect(page.getByRole('cell', { name: 'fee', exact: true })).toHaveCount(0);
});

test('slash focuses company search and the account bar fits the viewport', async ({ page }, testInfo) => {
  await page.route('**/api/search?*', route => route.fulfill({ json: { results: [
    { symbol: 'AAPL', name: 'Apple Inc.', exchange: 'NASDAQ' }, { symbol: 'APLE', name: 'Apple Hospitality REIT', exchange: 'NYSE' }] } }));
  await page.route('**/api/portfolio/accounts', route => route.fulfill({ json: { default: 'Default', accounts: [
    { name: 'Default', cash: 25000, put_collateral: 6500, free_cash: 18500, cash_updated_at: '2026-10-06T14:00:00Z' },
    { name: 'Roth IRA', cash: null, put_collateral: 0, free_cash: null }] } }));
  await page.route('**/api/portfolio/corporate-actions', route => route.fulfill({ json: { splits: [] } }));
  await page.goto('/#watchlist');
  await page.locator('body').press('/');
  const search = page.getByRole('combobox', { name: 'Ticker or company name' });
  await expect(search).toBeFocused();
  await expect(page).toHaveURL(/#dashboard/);
  await search.fill('apple');
  await expect(page.getByRole('option', { name: /Apple Hospitality REIT/ })).toBeVisible();
  const list = page.getByRole('listbox');
  expect(await list.evaluate(element => element.getBoundingClientRect().right <= window.innerWidth + 1)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('company-search.png') });
  await page.goto('/#portfolio');
  const bar = page.getByRole('region', { name: 'Brokerage accounts' });
  await expect(bar.getByRole('cell', { name: '$18,500' })).toBeVisible();
  await expect(bar.getByRole('cell', { name: 'Enter cash' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await bar.screenshot({ path: testInfo.outputPath('account-bar.png') });
});

test('corporate actions flag a stale holding and record a spin-off without overflow', async ({ page }, testInfo) => {
  let posted = null;
  await page.route('**/api/portfolio/corporate-actions', route => route.fulfill({ json: {
    splits: [], stale: [{ ticker: 'ATVI', last_quote: '2023-10-12' }], applied: [] } }));
  await page.route('**/api/portfolio/corporate-actions/spinoff', route => {
    posted = route.request().postDataJSON();
    return route.fulfill({ json: { ticker: 'MMM', new_ticker: 'SOLV', lots: 1, basis_moved: 150, options_unadjusted: 0 } });
  });
  page.on('dialog', dialog => dialog.accept());
  await page.goto('/#portfolio');
  await expect(page.getByText(/ATVI.*no quotes since 2023-10-12/)).toBeVisible();
  await page.getByText('Record a spin-off or merger', { exact: true }).click();
  const form = page.getByRole('form', { name: 'Record corporate action' });
  await form.getByLabel('Ticker you hold').fill('MMM');
  await form.getByLabel('Ex-date').fill('2024-04-01');
  await form.getByLabel('New company ticker').fill('SOLV');
  await form.getByLabel('New shares per share held').fill('0.25');
  await form.getByLabel('% of cost basis to new company').fill('7.5');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await form.screenshot({ path: testInfo.outputPath('corporate-actions.png') });
  await form.getByRole('button', { name: 'Record', exact: true }).click();
  await expect(page.getByText(/MMM: moved \$150 of cost basis to SOLV/)).toBeVisible();
  expect(posted).toEqual({ ticker: 'MMM', new_ticker: 'SOLV', action_date: '2024-04-01', ratio: 0.25, basis_pct: 7.5 });
});

test('watchlist list tabs, list picker and new-list form fit the viewport', async ({ page }, testInfo) => {
  let lists = ['Main', 'Growth', 'Dividend income', 'Semiconductors'];
  const memberships = { AAPL: ['Growth'], KO: ['Dividend income'], NVDA: ['Growth', 'Semiconductors'] };
  const overview = () => ({ lists, tickers: Object.keys(memberships),
    items: Object.entries(memberships).map(([ticker, names]) => ({ ticker, lists: names, list_name: names[0], note: '' })) });
  await page.route('**/api/screener', route => route.fulfill({ json: { stocks: [
    { ticker: 'AAPL', name: 'Apple Inc.', price: 200, change_pct: 1 }, { ticker: 'KO', name: 'Coca-Cola', price: 60, change_pct: -0.5 },
    { ticker: 'NVDA', name: 'NVIDIA', price: 120, change_pct: 2 }] } }));
  await page.route('**/api/watchlist', route => route.fulfill({ json: overview() }));
  await page.route('**/api/watchlist/earnings', route => route.fulfill({ json: { items: [] } }));
  await page.route('**/api/watchlist/lists', route => {
    lists = [...lists, route.request().postDataJSON().name];
    return route.fulfill({ json: overview() });
  });
  await page.route('**/api/watchlist/KO', route => {
    memberships.KO = route.request().postDataJSON().lists;
    return route.fulfill({ json: overview() });
  });
  await page.goto('/#watchlist');
  const tabs = page.getByRole('tablist', { name: 'Watchlist lists' });
  await expect(tabs.getByRole('tab')).toHaveText(['All3', 'Main0', 'Growth2', 'Dividend income1', 'Semiconductors1']);
  await tabs.getByRole('tab', { name: /Growth/ }).click();
  const table = page.locator('.watchlist-table');
  await expect(table.getByRole('button', { name: 'NVDA', exact: true })).toBeVisible();
  await expect(table.getByRole('button', { name: 'KO', exact: true })).toHaveCount(0);
  await tabs.getByRole('tab', { name: /All/ }).click();
  await page.getByRole('button', { name: 'Lists for KO' }).click();
  const picker = page.getByRole('group', { name: 'Lists for KO' });
  await expect(picker).toBeInViewport();
  await page.screenshot({ path: testInfo.outputPath('watchlist-list-picker.png') });
  await picker.getByRole('checkbox', { name: 'Growth' }).check();
  await expect(tabs.getByRole('tab', { name: /Growth/ })).toHaveText('Growth3');
  await page.getByRole('button', { name: '+ New list' }).click();
  await page.getByLabel('New list name').fill('Earnings this week');
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(tabs.getByRole('tab', { name: /Earnings this week/ })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText(/No symbols in Earnings this week yet/)).toBeVisible();
  await expect(tabs.getByRole('tab', { name: /Earnings this week/ })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.locator('.watchlist-tabs-bar').screenshot({ path: testInfo.outputPath('watchlist-tabs.png') });
});

test('header controls and main tabs fit the viewport with a consistent layout', async ({ page }, testInfo) => {
  await page.goto('/#ideas');
  const signOut = page.getByRole('button', { name: 'Sign Out' });
  await expect(signOut).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole('combobox', { name: 'Trading style' })).toBeInViewport({ ratio: 1 });
  await expect(page.getByRole('button', { name: 'Jump to (Ctrl+K)' })).toBeInViewport({ ratio: 1 });
  const tabs = page.locator('.main-tab');
  await expect(tabs).toHaveCount(5);
  const boxes = await tabs.evaluateAll(elements => elements.map(element => {
    const label = element.querySelector('.main-tab-label');
    return { right: element.getBoundingClientRect().right, height: element.offsetHeight,
      clipped: label.scrollWidth > label.clientWidth + 1 };
  }));
  const width = page.viewportSize().width;
  expect(boxes.every(box => box.right <= width + 1 && !box.clipped)).toBe(true);
  expect(new Set(boxes.map(box => box.height)).size).toBe(1);
  const cells = await page.getByRole('navigation', { name: 'Ideas views' }).getByRole('button')
    .evaluateAll(elements => elements.map(element => element.getBoundingClientRect().right));
  expect(Math.max(...cells)).toBeLessThanOrEqual(width + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  await page.locator('.app-header').screenshot({ path: testInfo.outputPath('header.png') });
});

test('sub-tab strips hide the scrollbar and reveal overflowing tabs', async ({ page }, testInfo) => {
  const mobile = testInfo.project.name === 'mobile';
  if (!mobile) await page.setViewportSize({ width: 1024, height: 800 });
  await page.goto('/#ideas');
  const nav = page.getByRole('navigation', { name: 'Ideas views' });
  const last = nav.getByRole('button', { name: /Options track record/ });
  if (mobile) {
    expect(await nav.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
    await expect(last).toBeInViewport({ ratio: 1 });
    await expect(page.locator('.tab-strip-arrow')).toHaveCount(0);
    return;
  }
  expect(await nav.evaluate(element => getComputedStyle(element).scrollbarWidth)).toBe('none');
  await expect(page.locator('.tab-strip-arrow.right')).toBeVisible();
  await expect(page.locator('.tab-strip-arrow.left')).toHaveCount(0);
  await page.locator('.tab-strip-arrow.right').click();
  await expect(page.locator('.tab-strip-arrow.left')).toBeVisible();
  await last.click();
  await expect(last).toHaveClass(/active/);
  await expect.poll(async () => {
    const [box, strip] = await Promise.all([last.boundingBox(), nav.boundingBox()]);
    return box.x >= strip.x && box.x + box.width <= strip.x + strip.width + 1;
  }).toBe(true);
  await page.locator('.tab-strip').first().screenshot({ path: testInfo.outputPath('tab-strip.png') });
});