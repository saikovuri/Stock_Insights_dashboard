// Mobile UI audit: screenshots every main view on a phone viewport and reports elements wider than the screen.
// Usage (from frontend/, local dev only; registers a throwaway user): node scripts/mobile-audit.mjs [baseUrl] [outDir] [desktop]
import { chromium, devices } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const base = process.argv[2] || 'http://localhost:5173';
const out = process.argv[3] || 'mobile-audit';
mkdirSync(out, { recursive: true });

const api = async (path, body, token) => {
  const res = await fetch(`${base}/api${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
};

const username = `mobileaudit${Date.now() % 100000}`;
let auth = await api('/auth/register', { username, password: 'audit-only-pass', display_name: 'Audit' });
const token = auth.token;
const csv = 'Symbol,Quantity,Price Paid\nAMD,300,120\nAAPL,50,180\nKO,100,60\nAMD Jan 15 \'27 $700 Call,-1,20\nNVDA Nov 20 \'26 $200 Put,-1,4\n';
await api('/portfolio/import', { csv, commit: true, kind: 'positions', account: 'Brokerage' }, token);
for (const t of ['NVDA', 'MSFT', 'TSLA']) await api('/watchlist', { ticker: t }, token);

const browser = await chromium.launch();
const context = await browser.newContext(process.argv[4] === 'desktop' ? { viewport: { width: 1440, height: 900 } } : { ...devices['Pixel 7'] });
await context.addInitScript(([t, r]) => {
  localStorage.setItem('token', t);
  if (r) localStorage.setItem('refresh_token', r);
  localStorage.setItem('stockpilot_tour_v1', 'done');
}, [token, auth.refresh_token]);
const page = await context.newPage();

async function report(name) {
  await page.waitForTimeout(2500);
  const overflow = await page.evaluate(() => {
    const width = document.documentElement.clientWidth;
    const bad = [];
    for (const el of document.querySelectorAll('body *')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.right > width + 1 && !el.closest('.table-scroll, .watchlist-rail, [data-scroll-x]')) {
        bad.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ').slice(0, 2).join('.')} right=${Math.round(r.right)}`);
      }
    }
    return { page: document.documentElement.scrollWidth > width + 1, sample: [...new Set(bad)].slice(0, 8) };
  });
  // Content hidden off to the side inside scroll boxes, and chips/badges split over two lines
  const hidden = await page.evaluate(() => {
    const scrollers = [];
    for (const el of document.querySelectorAll('body *')) {
      const style = getComputedStyle(el);
      if (!/(auto|scroll)/.test(style.overflowX) || el.clientWidth === 0) continue;
      if (el.scrollWidth <= el.clientWidth + 4 || el.closest('.tab-strip, .watchlist-rail, nav')) continue;
      const heads = [...el.querySelectorAll('th')].slice(0, 4).map(th => th.textContent.trim().slice(0, 14)).join('/');
      scrollers.push(`${el.tagName.toLowerCase()}.${String(el.className).split(' ')[0]} ${el.scrollWidth}>${el.clientWidth} [${heads}]`);
    }
    const wrapped = [];
    for (const el of document.querySelectorAll('[class*=chip], [class*=badge], [class*=pill], .tag')) {
      const r = el.getBoundingClientRect();
      const line = parseFloat(getComputedStyle(el).fontSize) * 1.9;
      if (r.height > line + 8 && el.textContent.trim().length < 40) wrapped.push(`${String(el.className).split(' ')[0]}:"${el.textContent.trim()}"`);
    }
    return { scrollers: [...new Set(scrollers)].slice(0, 8), wrapped: [...new Set(wrapped)].slice(0, 8) };
  });
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: true });
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  const view = page.viewportSize().height;
  for (let i = 0, y = 0; y < height && i < 6; i++, y += view) {
    await page.evaluate(top => window.scrollTo(0, top), y);
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${out}/${name}-${i}.png` });
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  console.log(`${name}: pageOverflow=${overflow.page} ${overflow.sample.join(' | ')}`);
  if (hidden.scrollers.length) console.log(`  sideways: ${hidden.scrollers.join(' | ')}`);
  if (hidden.wrapped.length) console.log(`  wrapped: ${hidden.wrapped.join(' | ')}`);
}

const click = async (role, name) => { const l = page.getByRole(role, { name }).first(); if (await l.count()) await l.click(); };

await page.goto(`${base}/#dashboard`); await page.waitForTimeout(4000); await report('01-dashboard-home');
await page.getByRole('combobox', { name: 'Ticker or company name' }).fill('SPG');
await page.keyboard.press('Enter');
await page.locator('.metrics-grid').first().waitFor({ timeout: 30000 }).catch(() => {});
await page.waitForTimeout(3000); await report('02-stock-overview');
await click('button', /Analysis/); await page.waitForTimeout(6000); await report('03-stock-analysis');
await click('button', /Fundamentals/); await page.waitForTimeout(5000); await report('04-stock-fundamentals');
await click('button', /News/); await page.waitForTimeout(5000); await report('05-stock-news');
await page.goto(`${base}/#ideas`); await page.waitForTimeout(6000); await report('06-ideas');
const ideasTab = async (name, file, wait = 6000) => {
  await page.getByRole('navigation', { name: 'Ideas views' }).getByRole('button', { name }).click().catch(() => {});
  await page.waitForTimeout(wait); await report(file);
};
await ideasTab(/In play/, '06a-ideas-inplay');
await ideasTab(/Setups/, '06b-ideas-setups');
await ideasTab(/Unusual options/, '06c-ideas-unusual', 20000);
await ideasTab(/Insider buying/, '06d-ideas-insiders', 10000);
await ideasTab(/Macro calendar/, '06e-ideas-macro');
await ideasTab(/Options track record/, '06f-ideas-track-record');
await ideasTab(/Wheel/, '07-ideas-wheel');
await page.goto(`${base}/#watchlist`); await page.waitForTimeout(8000); await report('08-watchlist');
await page.goto(`${base}/#portfolio`); await page.waitForTimeout(7000); await report('09-portfolio-holdings');
await click('button', /^Options/); await page.waitForTimeout(3000); await report('10-portfolio-options');
await click('button', 'Portfolio Risk'); await page.waitForTimeout(12000); await report('11-portfolio-risk');
await click('button', 'Income & Performance'); await page.waitForTimeout(6000); await report('12-portfolio-income');
await page.goto(`${base}/#journal`); await page.waitForTimeout(5000); await report('13-journal');
await page.keyboard.press('Control+k'); await page.waitForTimeout(500); await report('14-command-palette');
await browser.close();
