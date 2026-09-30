import { useState, useEffect, useLayoutEffect } from 'react';
import { createPortal } from 'react-dom';

export const TOUR_KEY = 'stockpilot_tour_v1';

const STEPS = [
  {
    title: 'Welcome to StockPilot 👋',
    body: 'Your AI co-pilot for researching stocks — charts, AI briefs, options and trade ideas in one place. Take a 30-second tour?',
    next: 'Show me around',
  },
  {
    sel: '.search-bar',
    title: 'Look up any stock',
    body: 'Type a ticker like AAPL and hit Analyze to get the chart, key levels, AI Brief, news, options and fundamentals.',
  },
  {
    sel: '.main-tabs',
    title: 'Five sections',
    body: (
      <ul className="tour-list">
        <li><b>Dashboard</b> — deep-dive one stock</li>
        <li><b>Ideas</b> — stocks in play, setups, unusual options, insider buying, strategy tester</li>
        <li><b>Watchlist</b> — track and screen your tickers</li>
        <li><b>Portfolio</b> — holdings, performance, dividends, taxes</li>
        <li><b>Journal</b> — plan trades and review what works</li>
      </ul>
    ),
  },
  {
    sel: '.profile-select',
    title: 'Pick your trading style',
    body: 'Day trader, swing or long-term: StockPilot tailors the chart, cards and AI analysis to how you trade. Change it anytime.',
  },
  {
    sel: '.btn-login',
    fallback: '.user-menu',
    title: 'Sign in for more (free)',
    body: 'Unlock AI Briefs and chat, price alerts to your phone, and sync your watchlist, portfolio and journal across devices.',
  },
  {
    title: 'One last tip',
    body: (
      <>
        Tap or hover any <span className="tip-icon tip-icon-static">?</span> for a plain-English explanation of the term.
        StockPilot is for research and education — not financial advice.
      </>
    ),
    next: "Let's go",
  },
];

function findTarget(step) {
  if (!step.sel) return null;
  const el = document.querySelector(step.sel) || (step.fallback && document.querySelector(step.fallback));
  return el && el.getClientRects().length ? el : null;
}

export default function Tour({ onClose }) {
  const [i, setI] = useState(0);
  const [rect, setRect] = useState(null);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;

  useLayoutEffect(() => {
    const el = findTarget(step);
    if (!el) { setRect(null); return; }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    const update = () => setRect(el.getBoundingClientRect());
    update();
    const t = setTimeout(update, 400);
    window.addEventListener('resize', update);
    window.addEventListener('scroll', update, true);
    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', update);
      window.removeEventListener('scroll', update, true);
    };
  }, [i]);

  useEffect(() => {
    const onKey = e => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight') setI(n => Math.min(n + 1, STEPS.length - 1));
      if (e.key === 'ArrowLeft') setI(n => Math.max(n - 1, 0));
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const pad = 6;
  const cardW = Math.min(340, window.innerWidth - 24);
  let cardStyle = { width: cardW };
  if (rect) {
    const left = Math.min(Math.max(12, rect.left + rect.width / 2 - cardW / 2), window.innerWidth - cardW - 12);
    const below = rect.bottom + 12 + 220 < window.innerHeight;
    cardStyle = below
      ? { ...cardStyle, left, top: rect.bottom + pad + 10 }
      : { ...cardStyle, left, bottom: window.innerHeight - rect.top + pad + 10 };
  }

  return createPortal(
    <div className="tour-root" role="dialog" aria-modal="true" aria-label="StockPilot tour">
      {rect
        ? <div className="tour-spot" style={{ left: rect.left - pad, top: rect.top - pad, width: rect.width + pad * 2, height: rect.height + pad * 2 }} />
        : <div className="tour-backdrop" />}
      <div className={`tour-card ${rect ? '' : 'tour-card-center'}`} style={cardStyle}>
        <div className="tour-step">{i + 1} / {STEPS.length}</div>
        <h3>{step.title}</h3>
        <div className="tour-body">{step.body}</div>
        <div className="tour-actions">
          {!last && <button className="link-btn tour-skip" onClick={onClose}>Skip</button>}
          <span style={{ flex: 1 }} />
          {i > 0 && <button className="btn-secondary" onClick={() => setI(i - 1)}>Back</button>}
          <button className="btn-primary" onClick={() => (last ? onClose() : setI(i + 1))}>
            {step.next || 'Next'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
